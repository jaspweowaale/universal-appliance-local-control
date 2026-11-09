"""Validation tests for UALC Level-1 model profiles.

Two jobs:

 1. Every profile actually committed under `devices/` must load and validate.
    A contributed profile that is broken should fail CI, not fail later on
    somebody's appliance.

 2. The safety and honesty rules must be *enforced*, not merely written in a
    contributing guide. In particular the support-status rules from
    docs/SUPPORT_LEVELS.md: a profile cannot claim hardware testing it did
    not have, and cannot claim maintainer verification for a community
    contribution.

Run:
    PYTHONPATH=translator:testing_infra:. python testing_infra/profile_validation_test.py
"""
from __future__ import annotations

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, os.path.join(ROOT, "translator"), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from profiles import (  # noqa: E402
    ProfileError,
    discover_profiles,
    profile_from_dict,
    validate_profile,
)

DEVICES_ROOT = os.path.join(ROOT, "devices")
REFERENCE = os.path.join(DEVICES_ROOT, "lg", "AIR_910604_WW.json")

_passed = 0
_failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS {label}")
    else:
        _failed += 1
        print(f"  FAIL {label}: {detail}")


def expect_rejected(label: str, mutate, needle: str = "") -> None:
    """Apply `mutate` to a copy of the reference profile and require that
    validation rejects it -- ideally naming the reason."""
    with open(REFERENCE, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    data = copy.deepcopy(data)
    mutate(data)
    errors = validate_profile(data)
    if not errors:
        check(label, False, "validator accepted it")
        return
    if needle and not any(needle.lower() in e.lower() for e in errors):
        check(label, False,
              f"rejected, but no error mentioned {needle!r}: {errors}")
        return
    check(label, True)


def main() -> int:
    print("UALC profile validation test")
    print("=" * 64)

    # -- 1. Committed profiles all validate ------------------------------
    print("\nCHECK_GROUP_1  every committed profile validates")
    profiles = discover_profiles(DEVICES_ROOT)
    check("at least one profile is shipped", len(profiles) >= 1,
          f"found {len(profiles)}")
    for profile in profiles:
        check(f"{profile.manufacturer}/{profile.model_id} validates", True)
        check(f"{profile.manufacturer}/{profile.model_id} declares a known "
              f"support level",
              profile.support_level in (
                  "RESEARCH", "CAPTURED", "DECODED", "SIMULATED",
                  "COMMUNITY_HARDWARE_TESTED", "MAINTAINER_HARDWARE_TESTED",
                  "LOCAL_OPERATIONAL", "CLOUD_INDEPENDENT"),
              f"got {profile.support_level!r}")

    # -- 2. Structural rules ---------------------------------------------
    print("\nCHECK_GROUP_2  structural rules enforced")
    expect_rejected("rejects an unknown profile_version",
                    lambda d: d.update(profile_version="9.9"),
                    "profile_version")
    expect_rejected("rejects an unknown top-level key",
                    lambda d: d.update(sneaky_extra=1),
                    "unknown top-level")
    expect_rejected("rejects a decimal tag instead of a hex string",
                    lambda d: d["fields"][0].update(tag=503),
                    "hex string")
    expect_rejected("rejects an out-of-range tag",
                    lambda d: d["fields"][0].update(tag="0x4ff"),
                    "range")
    expect_rejected("rejects a duplicate tag",
                    lambda d: d["fields"].append(dict(d["fields"][0])),
                    "duplicate")
    expect_rejected("rejects a non-snake_case field name",
                    lambda d: d["fields"][0].update(name="PowerState"),
                    "snake_case")
    expect_rejected("rejects an unknown field type",
                    lambda d: d["fields"][0].update(type="blob"),
                    "type")
    expect_rejected("rejects an enum with no values",
                    lambda d: d["fields"][1].update(values={}),
                    "values")
    expect_rejected("rejects an unknown device_class",
                    lambda d: d["model"].update(device_class="toaster"),
                    "device_class")
    expect_rejected("rejects a non-lowercase manufacturer",
                    lambda d: d["model"].update(manufacturer="LG"),
                    "lowercase")
    expect_rejected("rejects an empty fields list",
                    lambda d: d.update(fields=[]),
                    "fields")

    # -- 3. A profile is data, never behaviour ---------------------------
    print("\nCHECK_GROUP_3  profiles cannot smuggle in behaviour")
    expect_rejected("rejects an unknown codec (that is a Level-3 change)",
                    lambda d: d["protocol"].update(codec="my_own_codec"),
                    "codec")
    expect_rejected("rejects an unrecognised codec parameter",
                    lambda d: d["protocol"]["parameters"].update(
                        shell_command="rm -rf /"),
                    "not a recognised")
    expect_rejected("rejects a shell-command-looking value",
                    lambda d: d["model"].update(
                        marketing_names=["$(curl http://x)"]),
                    "executable expression")
    expect_rejected("rejects a template-expression-looking value",
                    lambda d: d.update(notes="value is {{ 7*7 }}"),
                    "executable expression")
    expect_rejected("rejects a Lua loadstring-looking value",
                    lambda d: d.update(notes="loadstring('os.exit()')"),
                    "executable expression")
    expect_rejected("rejects an embedded credential key",
                    lambda d: d["model"].update(token="abc123"),
                    "credentials")
    expect_rejected("rejects a nested embedded credential",
                    lambda d: d["protocol"].update(
                        parameters={**d["protocol"]["parameters"],
                                    "password": "x"}),
                    "credential")
    expect_rejected("rejects declarative command encoding in v1.0",
                    lambda d: d.update(
                        commands=[{"name": "start", "frame": "00ff"}]),
                    "commands must be empty")

    # -- 4. Honest support status, enforced in code ----------------------
    print("\nCHECK_GROUP_4  support-status honesty rules enforced")
    expect_rejected(
        "rejects MAINTAINER_HARDWARE_TESTED with hardware_tested=false",
        lambda d: d["support_status"].update(
            level="MAINTAINER_HARDWARE_TESTED", verification_source="maintainer",
            hardware_tested=False),
        "asserts hardware testing")
    expect_rejected(
        "rejects COMMUNITY_HARDWARE_TESTED claiming maintainer verification",
        lambda d: d["support_status"].update(
            level="COMMUNITY_HARDWARE_TESTED", verification_source="maintainer",
            hardware_tested=True),
        "requires verification_source")
    expect_rejected(
        "rejects MAINTAINER_HARDWARE_TESTED claiming community verification",
        lambda d: d["support_status"].update(
            level="MAINTAINER_HARDWARE_TESTED", verification_source="community",
            hardware_tested=True),
        "requires verification_source")
    expect_rejected(
        "rejects hardware_tested=true with verification_source 'none'",
        lambda d: d["support_status"].update(hardware_tested=True),
        "verification_source is 'none'")
    expect_rejected(
        "rejects CLOUD_INDEPENDENT without hardware testing",
        lambda d: d["support_status"].update(
            level="CLOUD_INDEPENDENT", verification_source="maintainer",
            hardware_tested=False),
        "asserts hardware testing")
    expect_rejected(
        "rejects an invented support level",
        lambda d: d["support_status"].update(level="TOTALLY_WORKS"),
        "level")
    expect_rejected(
        "rejects an invented verification source",
        lambda d: d["support_status"].update(verification_source="vibes"),
        "verification_source")

    # A legitimate community hardware claim must still be accepted, or the
    # rules above would make community contribution impossible.
    with open(REFERENCE, "r", encoding="utf-8") as handle:
        good = copy.deepcopy(json.load(handle))
    good["support_status"].update(level="COMMUNITY_HARDWARE_TESTED",
                                 verification_source="community",
                                 hardware_tested=True)
    check("accepts a well-formed COMMUNITY_HARDWARE_TESTED claim",
          validate_profile(good) == [],
          f"errors: {validate_profile(good)}")

    good2 = copy.deepcopy(good)
    good2["support_status"].update(level="MAINTAINER_HARDWARE_TESTED",
                                   verification_source="both")
    check("accepts MAINTAINER_HARDWARE_TESTED with source 'both'",
          validate_profile(good2) == [],
          f"errors: {validate_profile(good2)}")

    # -- 5. profile_from_dict refuses invalid input -----------------------
    print("\nCHECK_GROUP_5  loader refuses invalid input")
    broken = copy.deepcopy(good)
    broken["fields"][0]["tag"] = "nope"
    try:
        profile_from_dict(broken)
        check("profile_from_dict raises on an invalid profile", False,
              "it returned a Profile")
    except ProfileError as exc:
        check("profile_from_dict raises on an invalid profile",
              "tag" in str(exc), f"message was {exc}")

    # -- 6. Schema / validator agreement (optional) -----------------------
    # The JSON Schema under schemas/ is the published spec; the Python
    # validator is what CI enforces. They must agree. This check runs only if
    # `jsonschema` happens to be installed -- UALC does not depend on it, and
    # will not gain a dependency just to validate contributions.
    print("\nCHECK_GROUP_6  schemas/ agrees with the Python validator "
          "(optional)")
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        print("  SKIP jsonschema not installed; schemas/ not cross-checked. "
              "Install it locally if you edit schemas/.")
    else:
        schema_path = os.path.join(ROOT, "schemas", "model_profile.schema.json")
        with open(schema_path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        for profile_file in sorted(
                os.path.join(dirpath, name)
                for dirpath, _d, files in os.walk(DEVICES_ROOT)
                for name in files if name.endswith(".json")):
            with open(profile_file, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
            try:
                jsonschema.validate(doc, schema)
                check(f"{os.path.basename(profile_file)} satisfies the "
                      f"published schema", True)
            except jsonschema.ValidationError as exc:
                check(f"{os.path.basename(profile_file)} satisfies the "
                      f"published schema", False, str(exc).splitlines()[0])
        # And a document the Python validator rejects must also fail the
        # schema, or the published spec is laxer than reality.
        bad = copy.deepcopy(good)
        bad["fields"][0]["tag"] = "503"
        schema_rejected = False
        try:
            jsonschema.validate(bad, schema)
        except jsonschema.ValidationError:
            schema_rejected = True
        check("schema also rejects what the validator rejects",
              schema_rejected and validate_profile(bad) != [],
              "the published schema is laxer than the Python validator")

    print("\n" + "=" * 64)
    print(f"passed={_passed} failed={_failed}")
    if _failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
