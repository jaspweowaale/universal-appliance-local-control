"""UALC model profiles (Level 1 extension point).

A *profile* adds support for a new appliance model using declarative data
only -- no code. If a model speaks a protocol UALC already understands and
differs only in which field means what, a profile is all a contributor needs
to write, and UALC core does not change.

    devices/<manufacturer>/<MODEL_ID>.json   ->  ProfileAdapter(ProtocolAdapter)

A profile names a **codec** that is implemented here, in core, and supplies
only parameters and field maps to it. That is the whole security argument for
Level 1: a profile cannot express behaviour, so a malicious profile cannot do
anything a malicious *table of integers* could not do. Profiles are therefore
reviewable by reading them, and are not sandboxed -- they are data.

Enforced by `validate_profile`, not merely documented:
  * every codec/type/unit is drawn from a closed vocabulary;
  * no key may be credential-shaped, and no value may look like code or a
    shell command;
  * tags are hex strings in range, values are plain scalars;
  * unknown top-level keys are rejected, so a typo cannot silently disable a
    constraint.

This module is stdlib-only. The JSON Schema files under `schemas/` are the
normative published spec for editors and third-party tooling; the checks here
are what CI actually enforces, so that UALC does not gain a `jsonschema`
dependency just to validate contributions.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from base import ProtocolAdapter
from integration_contract import (
    AuthStatus,
    Direction,
    MessageType,
    StandardCommand,
    StandardMessage,
)

PROFILE_VERSIONS = {"1.0"}

SUPPORT_LEVELS = (
    "RESEARCH",
    "CAPTURED",
    "DECODED",
    "SIMULATED",
    "COMMUNITY_HARDWARE_TESTED",
    "MAINTAINER_HARDWARE_TESTED",
    "LOCAL_OPERATIONAL",
    "CLOUD_INDEPENDENT",
)

VERIFICATION_SOURCES = ("none", "community", "maintainer", "both")

FIELD_TYPES = ("enum", "integer", "boolean", "string")

DEVICE_CLASSES = (
    "air_purifier", "air_conditioner", "refrigerator", "vacuum", "washer",
    "dryer", "dishwasher", "water_heater", "dehumidifier", "oven", "other",
)

_CREDENTIAL_HINTS = (
    "password", "passwd", "secret", "token", "localkey", "local_key",
    "credential", "private_key", "apikey", "api_key", "passphrase", "duid",
)

# A profile is data. Anything that smells like an expression or a command is
# rejected outright rather than ignored, so a reviewer never has to wonder
# whether some field is evaluated somewhere.
_CODEISH = re.compile(
    r"(\$\{|\$\(|`|\beval\b|\bexec\b|\bimport\b|\b__[a-z]+__\b|"
    r"\blambda\b|\bos\.|\bsubprocess\b|;\s*rm\s|\brequire\s*\(|"
    r"\bloadstring\b|<%|%>|\{\{)",
    re.IGNORECASE,
)

_TOP_LEVEL_KEYS = {
    "profile_version", "model", "protocol", "fields", "commands",
    "support_status", "notes",
}


class ProfileError(ValueError):
    """A profile is structurally invalid or violates a safety rule."""


class UnsupportedDialect(ProfileError):
    """The frame is well-formed but belongs to a protocol variant this
    profile deliberately does not claim. Reported distinctly from a malformed
    frame so the two never get conflated in a support matrix."""


# ---------------------------------------------------------------------------
# Codecs
# ---------------------------------------------------------------------------


@dataclass
class TlvElement:
    tag: int
    value: int
    width: int


def decode_lg_thinq2_tlv(payload: bytes, params: dict[str, Any]
                         ) -> tuple[list[TlvElement], bool]:
    """Decode the LG ThinQ2 'A7' TLV body.

    Encoding (10-bit tag, variable-width big-endian value):
        tag  = (b0 << 2) | (b1 >> 6)
        lsel = (b1 >> 4) & 0x03         # 0 => value is the low nibble of b1
        value = b1 & 0x0f               if lsel == 0
                big-endian over lsel following bytes otherwise
        element width = 2 + lsel

    Returns (elements, truncated). A truncated trailing element yields
    everything decoded so far plus truncated=True rather than discarding an
    otherwise good frame -- the caller decides what that is worth.
    """
    prefix = params["envelope_prefix"]
    body_offset = params["tlv_body_offset"]
    trailer = params["trailer_bytes"]
    dialect_offset = params["dialect_offset"]
    dialect_byte = params["dialect_byte"]
    rejected = params.get("rejected_dialects", {})

    if len(payload) < body_offset + trailer:
        raise ProfileError(
            f"frame too short: {len(payload)} bytes, need at least "
            f"{body_offset + trailer}")

    prefix_at = params["envelope_prefix_offset"]
    actual = list(payload[prefix_at:prefix_at + len(prefix)])
    if actual != list(prefix):
        raise ProfileError(
            f"envelope prefix mismatch at offset {prefix_at}: "
            f"expected {prefix}, got {actual}")

    dialect = payload[dialect_offset]
    if dialect != dialect_byte:
        why = rejected.get(f"0x{dialect:02x}")
        raise UnsupportedDialect(
            f"unsupported dialect 0x{dialect:02x}"
            + (f": {why}" if why else ""))

    body = payload[body_offset:len(payload) - trailer]
    elements: list[TlvElement] = []
    i = 0
    while i < len(body):
        if i + 1 >= len(body):
            return elements, True
        b0, b1 = body[i], body[i + 1]
        tag = (b0 << 2) | (b1 >> 6)
        lsel = (b1 >> 4) & 0x03
        if lsel == 0:
            value = b1 & 0x0F
        else:
            # Element occupies body[i .. i+1+lsel]; refuse to read past the end.
            if i + 2 + lsel > len(body):
                return elements, True
            value = 0
            for k in range(1, lsel + 1):
                value = (value << 8) | body[i + 1 + k]
        elements.append(TlvElement(tag=tag, value=value, width=2 + lsel))
        i += 2 + lsel
    return elements, False


CODECS: dict[str, Callable[[bytes, dict[str, Any]],
                           tuple[list[TlvElement], bool]]] = {
    "lg_thinq2_tlv": decode_lg_thinq2_tlv,
}

# Parameters each codec accepts, with validators. Anything else is refused.
CODEC_PARAMS: dict[str, dict[str, Callable[[Any], bool]]] = {
    "lg_thinq2_tlv": {
        "envelope_prefix": lambda v: (
            isinstance(v, list) and 0 < len(v) <= 8
            and all(isinstance(x, int) and 0 <= x <= 255 for x in v)),
        "envelope_prefix_offset": lambda v: isinstance(v, int) and 0 <= v <= 64,
        "dialect_offset": lambda v: isinstance(v, int) and 0 <= v <= 64,
        "dialect_byte": lambda v: isinstance(v, int) and 0 <= v <= 255,
        "tlv_body_offset": lambda v: isinstance(v, int) and 0 <= v <= 64,
        "trailer_bytes": lambda v: isinstance(v, int) and 0 <= v <= 8,
        "full_state_min_elements": lambda v: isinstance(v, int) and v >= 1,
        "rejected_dialects": lambda v: (
            isinstance(v, dict)
            and all(isinstance(k, str) and isinstance(x, str)
                    for k, x in v.items())),
    },
}

_REQUIRED_CODEC_PARAMS = {
    "lg_thinq2_tlv": {
        "envelope_prefix", "envelope_prefix_offset", "dialect_offset",
        "dialect_byte", "tlv_body_offset", "trailer_bytes",
        "full_state_min_elements",
    },
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _scan_for_unsafe(obj: Any, path: str, errors: list[str],
                     depth: int = 0) -> None:
    if depth > 12:
        errors.append(f"{path}: nested too deeply")
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                errors.append(f"{path}: non-string key {key!r}")
                continue
            if key.lower() in _CREDENTIAL_HINTS:
                errors.append(
                    f"{path}.{key}: profiles must not contain credentials")
            _scan_for_unsafe(value, f"{path}.{key}", errors, depth + 1)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _scan_for_unsafe(item, f"{path}[{idx}]", errors, depth + 1)
    elif isinstance(obj, str):
        if _CODEISH.search(obj):
            errors.append(
                f"{path}: value looks like an executable expression or "
                f"command, which profiles must not contain: {obj[:60]!r}")
    elif not isinstance(obj, (int, float, bool)) and obj is not None:
        errors.append(f"{path}: unsupported value type "
                      f"{type(obj).__name__}")


def _parse_tag(raw: Any) -> int:
    if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,4}", raw):
        raise ProfileError(
            f"tag must be a hex string like '0x1f7', got {raw!r}")
    tag = int(raw, 16)
    if not 0 <= tag <= 0x3FF:
        raise ProfileError(
            f"tag {raw} out of range for a 10-bit tag space")
    return tag


def validate_profile(data: Any) -> list[str]:
    """Return a list of human-readable problems. Empty list means valid."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["profile must be a JSON object"]

    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        errors.append(f"unknown top-level keys: {sorted(unknown)}")

    version = data.get("profile_version")
    if version not in PROFILE_VERSIONS:
        errors.append(
            f"profile_version must be one of {sorted(PROFILE_VERSIONS)}, "
            f"got {version!r}")

    _scan_for_unsafe(data, "profile", errors)

    model = data.get("model")
    if not isinstance(model, dict):
        errors.append("model must be an object")
    else:
        for key in ("manufacturer", "model_id", "device_class"):
            if not isinstance(model.get(key), str) or not model[key]:
                errors.append(f"model.{key} must be a non-empty string")
        if isinstance(model.get("manufacturer"), str) and \
                not re.fullmatch(r"[a-z0-9_]+", model["manufacturer"]):
            errors.append(
                "model.manufacturer must be lowercase [a-z0-9_] "
                f"(got {model['manufacturer']!r})")
        if model.get("device_class") not in DEVICE_CLASSES:
            errors.append(
                f"model.device_class must be one of {list(DEVICE_CLASSES)}, "
                f"got {model.get('device_class')!r}")
        fw = model.get("firmware_ranges", [])
        if not isinstance(fw, list) or \
                not all(isinstance(x, str) for x in fw):
            errors.append("model.firmware_ranges must be a list of strings")

    protocol = data.get("protocol")
    if not isinstance(protocol, dict):
        errors.append("protocol must be an object")
    else:
        if not isinstance(protocol.get("family"), str):
            errors.append("protocol.family must be a string")
        codec = protocol.get("codec")
        if codec not in CODECS:
            errors.append(
                f"protocol.codec must be one of {sorted(CODECS)}, "
                f"got {codec!r}. A genuinely new protocol is a Level 3 "
                f"contribution, not a profile.")
        else:
            params = protocol.get("parameters")
            if not isinstance(params, dict):
                errors.append("protocol.parameters must be an object")
            else:
                allowed = CODEC_PARAMS[codec]
                for key, value in params.items():
                    check = allowed.get(key)
                    if check is None:
                        errors.append(
                            f"protocol.parameters.{key} is not a recognised "
                            f"parameter for codec {codec!r}")
                    elif not check(value):
                        errors.append(
                            f"protocol.parameters.{key} has an invalid "
                            f"value: {value!r}")
                missing = _REQUIRED_CODEC_PARAMS[codec] - set(params)
                if missing:
                    errors.append(
                        f"protocol.parameters missing required: "
                        f"{sorted(missing)}")

    fields = data.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("fields must be a non-empty list")
    else:
        seen_tags: set[int] = set()
        seen_names: set[str] = set()
        for idx, item in enumerate(fields):
            where = f"fields[{idx}]"
            if not isinstance(item, dict):
                errors.append(f"{where} must be an object")
                continue
            try:
                tag = _parse_tag(item.get("tag"))
            except ProfileError as exc:
                errors.append(f"{where}: {exc}")
                tag = None
            if tag is not None:
                if tag in seen_tags:
                    errors.append(f"{where}: duplicate tag {item['tag']}")
                seen_tags.add(tag)
            name = item.get("name")
            if not isinstance(name, str) or \
                    not re.fullmatch(r"[a-z][a-z0-9_]*", name or ""):
                errors.append(
                    f"{where}.name must be snake_case [a-z][a-z0-9_]*, "
                    f"got {name!r}")
            else:
                if name in seen_names:
                    errors.append(f"{where}: duplicate name {name!r}")
                seen_names.add(name)
            ftype = item.get("type")
            if ftype not in FIELD_TYPES:
                errors.append(
                    f"{where}.type must be one of {list(FIELD_TYPES)}, "
                    f"got {ftype!r}")
            if ftype == "enum":
                values = item.get("values")
                if not isinstance(values, dict) or not values:
                    errors.append(f"{where}.values must be a non-empty object "
                                  f"for an enum field")
                else:
                    for raw_key, mapped in values.items():
                        if not re.fullmatch(r"\d+", str(raw_key)):
                            errors.append(
                                f"{where}.values key {raw_key!r} must be a "
                                f"decimal integer string")
                        if not isinstance(mapped, str) or not mapped:
                            errors.append(
                                f"{where}.values[{raw_key}] must be a "
                                f"non-empty string")
            if "unit" in item and not isinstance(item["unit"], str):
                errors.append(f"{where}.unit must be a string")
            if "writable" in item and not isinstance(item["writable"], bool):
                errors.append(f"{where}.writable must be a boolean")

    commands = data.get("commands", [])
    if not isinstance(commands, list):
        errors.append("commands must be a list")
    elif commands:
        # Declarative command *encoding* is not part of profile v1.0 on
        # purpose: getting a frame wrong can reach real hardware. Until a
        # codec declares an encoder, commands may only be declared as
        # unsupported documentation.
        errors.append(
            "commands must be empty in profile_version 1.0: declarative "
            "command encoding is not yet supported. Use a Level 2 Lua "
            "handler or a Level 3 adapter to send frames.")

    status = data.get("support_status")
    if not isinstance(status, dict):
        errors.append("support_status must be an object")
    else:
        if status.get("level") not in SUPPORT_LEVELS:
            errors.append(
                f"support_status.level must be one of {list(SUPPORT_LEVELS)}, "
                f"got {status.get('level')!r}")
        if status.get("verification_source") not in VERIFICATION_SOURCES:
            errors.append(
                f"support_status.verification_source must be one of "
                f"{list(VERIFICATION_SOURCES)}, "
                f"got {status.get('verification_source')!r}")
        if not isinstance(status.get("hardware_tested"), bool):
            errors.append("support_status.hardware_tested must be a boolean")
        # The honesty rule, enforced in code rather than trusted to reviewers.
        level = status.get("level")
        hw = status.get("hardware_tested")
        src = status.get("verification_source")
        if level in ("COMMUNITY_HARDWARE_TESTED",
                     "MAINTAINER_HARDWARE_TESTED",
                     "LOCAL_OPERATIONAL", "CLOUD_INDEPENDENT") and hw is False:
            errors.append(
                f"support_status: level {level!r} asserts hardware testing "
                f"but hardware_tested is false")
        if level == "MAINTAINER_HARDWARE_TESTED" and src not in \
                ("maintainer", "both"):
            errors.append(
                "support_status: MAINTAINER_HARDWARE_TESTED requires "
                "verification_source 'maintainer' or 'both'")
        if level == "COMMUNITY_HARDWARE_TESTED" and src not in \
                ("community", "both"):
            errors.append(
                "support_status: COMMUNITY_HARDWARE_TESTED requires "
                "verification_source 'community' or 'both'")
        if hw is True and src == "none":
            errors.append(
                "support_status: hardware_tested is true but "
                "verification_source is 'none'")

    return errors


# ---------------------------------------------------------------------------
# Profile objects
# ---------------------------------------------------------------------------


@dataclass
class ProfileField:
    tag: int
    name: str
    type: str
    values: dict[int, str] = field(default_factory=dict)
    unit: str | None = None
    writable: bool = False


@dataclass
class Profile:
    manufacturer: str
    model_id: str
    device_class: str
    protocol_family: str
    codec: str
    parameters: dict[str, Any]
    fields: dict[int, ProfileField]
    support_level: str
    verification_source: str
    hardware_tested: bool
    known_limitations: list[str] = field(default_factory=list)
    source_path: str | None = None

    @property
    def readable_names(self) -> list[str]:
        return sorted(f.name for f in self.fields.values())


def profile_from_dict(data: dict[str, Any],
                      source_path: str | None = None) -> Profile:
    errors = validate_profile(data)
    if errors:
        where = f" ({source_path})" if source_path else ""
        raise ProfileError(
            f"invalid profile{where}:\n  - " + "\n  - ".join(errors))

    fields: dict[int, ProfileField] = {}
    for item in data["fields"]:
        tag = _parse_tag(item["tag"])
        fields[tag] = ProfileField(
            tag=tag,
            name=item["name"],
            type=item["type"],
            values={int(k): v for k, v in (item.get("values") or {}).items()},
            unit=item.get("unit"),
            writable=bool(item.get("writable", False)),
        )

    status = data["support_status"]
    return Profile(
        manufacturer=data["model"]["manufacturer"],
        model_id=data["model"]["model_id"],
        device_class=data["model"]["device_class"],
        protocol_family=data["protocol"]["family"],
        codec=data["protocol"]["codec"],
        parameters=dict(data["protocol"]["parameters"]),
        fields=fields,
        support_level=status["level"],
        verification_source=status["verification_source"],
        hardware_tested=bool(status["hardware_tested"]),
        known_limitations=list(status.get("known_limitations", [])),
        source_path=source_path,
    )


def load_profile(path: str) -> Profile:
    with open(path, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ProfileError(f"{path}: not valid JSON: {exc}") from exc
    return profile_from_dict(data, source_path=path)


def discover_profiles(root: str) -> list[Profile]:
    """Load every profile under a devices/ tree. Used by CI so that an
    invalid contributed profile fails the build rather than failing at
    runtime on someone's appliance."""
    found: list[Profile] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if name.endswith(".json") and not name.startswith("_"):
                found.append(load_profile(os.path.join(dirpath, name)))
    return found


# ---------------------------------------------------------------------------
# Profile-driven adapter
# ---------------------------------------------------------------------------


class ProfileAdapter(ProtocolAdapter):
    """Turns a declarative Profile into a working ProtocolAdapter.

    Read-only by construction: profile v1.0 cannot declare command encoding,
    so `build_outbound` always raises NotImplementedError. That is the point
    of separating Level 1 from Levels 2 and 3 -- a contributor can make a
    model observable without being able to make UALC emit a frame.
    """

    def __init__(self, profile: Profile):
        self.profile = profile
        self.manufacturer = profile.manufacturer
        self.protocol_family = profile.protocol_family
        self._decode = CODECS[profile.codec]

    def parse_inbound(self, device_id: str, topic: str,
                      payload: bytes) -> StandardMessage:
        try:
            elements, truncated = self._decode(payload, self.profile.parameters)
        except UnsupportedDialect as exc:
            return self._error(device_id, "UNSUPPORTED_PROTOCOL_VERSION",
                               str(exc))
        except ProfileError as exc:
            return self._error(device_id, "MALFORMED_FRAME", str(exc))

        if not elements:
            return self._error(device_id, "MALFORMED_FRAME",
                               "no decodable elements")

        state: dict[str, Any] = {}
        unknown = 0
        for element in elements:
            spec = self.profile.fields.get(element.tag)
            if spec is None:
                unknown += 1
                continue
            if spec.type == "enum":
                mapped = spec.values.get(element.value)
                if mapped is None:
                    # Report, never silently coerce: a value outside the
                    # documented domain is a finding about the appliance.
                    state[spec.name] = "unknown"
                    state[f"{spec.name}_raw"] = element.value
                else:
                    state[spec.name] = mapped
            elif spec.type == "boolean":
                state[spec.name] = bool(element.value)
            elif spec.type == "string":
                state[spec.name] = str(element.value)
            else:
                state[spec.name] = element.value

        if unknown:
            state["unknown_tag_count"] = unknown
        if truncated:
            state["frame_truncated"] = True

        minimum = self.profile.parameters.get("full_state_min_elements", 1)
        return StandardMessage(
            device_id=device_id,
            protocol_adapter=self.adapter_name,
            direction=Direction.INBOUND,
            message_type=MessageType.DEVICE_EVENT,
            payload={
                "event_kind": "status",
                "state": state,
                "partial": len(elements) < minimum,
                "model_id": self.profile.model_id,
            },
            # A profile decodes bytes. It verifies nothing.
            auth_status=AuthStatus.UNVERIFIED,
        )

    def build_outbound(self, device_id: str,
                       command: StandardCommand) -> tuple[str, bytes]:
        raise NotImplementedError(
            f"profile {self.profile.model_id!r} is declarative and read-only; "
            f"declarative command encoding is not supported in profile "
            f"version 1.0")

    def supported_commands(self) -> set[StandardCommand]:
        return set()

    def is_ack_for(self, command: StandardCommand,
                   inbound_payload: dict) -> bool:
        return False

    @property
    def adapter_name(self) -> str:
        return f"profile:{self.profile.manufacturer}_{self.profile.model_id}"

    def _error(self, device_id: str, code: str, message: str
               ) -> StandardMessage:
        return StandardMessage(
            device_id=device_id,
            protocol_adapter=self.adapter_name,
            direction=Direction.INBOUND,
            message_type=MessageType.ADAPTER_ERROR,
            payload={"code": code, "message": message},
            auth_status=AuthStatus.NOT_APPLICABLE,
        )
