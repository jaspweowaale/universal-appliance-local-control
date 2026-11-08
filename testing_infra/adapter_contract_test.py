"""Cross-language adapter contract test.

Runs ONE set of language-neutral cases (testing_infra/contract_fixtures.py)
against TWO independent implementations of the same device:

    Level 1  devices/lg/AIR_910604_WW.json              -> ProfileAdapter  (Python, data-driven)
    Level 2  plugins/lua/examples/lg_air_910604_ww/     -> LuaProtocolAdapter (Lua subprocess)

and asserts they produce identical results. This is the acceptance test for
the claim that a community contributor can add device support in Lua, without
touching UALC core, and be held to the same contract as Python code.

If no `lua` interpreter is on PATH the Lua half SKIPS rather than fails, so a
contributor can always run the Python half.

Run:
    PYTHONPATH=translator:testing_infra:. python testing_infra/adapter_contract_test.py
"""
from __future__ import annotations

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, os.path.join(ROOT, "translator"), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from contract_fixtures import contract_cases  # noqa: E402
from integration_contract import MessageType, StandardCommand  # noqa: E402
from lua_host import (  # noqa: E402
    LuaHostError,
    LuaPlugin,
    LuaProtocolAdapter,
    PluginLimits,
    lua_available,
)
from profiles import ProfileAdapter, load_profile  # noqa: E402

PROFILE_PATH = os.path.join(ROOT, "devices", "lg", "AIR_910604_WW.json")
HANDLER_PATH = os.path.join(ROOT, "plugins", "lua", "examples",
                            "lg_air_910604_ww", "handler.lua")
SDK_PATH = os.path.join(ROOT, "plugins", "lua", "ualc_sdk.lua")

DEVICE_ID = "contract-test-device"

_passed = 0
_failed = 0
_skipped = 0
_results: list[tuple[str, str, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        _results.append(("PASS", label, ""))
    else:
        _failed += 1
        _results.append(("FAIL", label, detail))
        print(f"  FAIL {label}: {detail}")


def skip(label: str, why: str) -> None:
    global _skipped
    _skipped += 1
    _results.append(("SKIP", label, why))
    print(f"  SKIP {label}: {why}")


def observe(adapter, case) -> dict:
    """Reduce an adapter's StandardMessage to the comparable facts."""
    msg = adapter.parse_inbound(DEVICE_ID, "test/topic", case.payload)
    if msg.message_type is MessageType.ADAPTER_ERROR:
        return {"error_code": msg.payload.get("code")}
    return {
        "state": dict(msg.payload.get("state") or {}),
        "partial": bool(msg.payload.get("partial")),
        "model_id": msg.payload.get("model_id"),
        "auth_status": msg.auth_status.value,
    }


def run_cases(kind: str, adapter) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for case in contract_cases():
        label = f"[{kind}] {case.name}"
        try:
            got = observe(adapter, case)
        except Exception as exc:  # noqa: BLE001 - a raise is itself a failure
            check(label, False,
                  f"raised {type(exc).__name__}: {exc}")
            continue
        seen[case.name] = got

        if case.expect_error_code is not None:
            check(label + " -> error code",
                  got.get("error_code") == case.expect_error_code,
                  f"expected {case.expect_error_code}, got {got}")
            continue

        if "error_code" in got:
            check(label, False,
                  f"expected a decode, got error {got['error_code']}")
            continue

        if case.expect_state is not None:
            check(label + " -> state",
                  got["state"] == case.expect_state,
                  f"expected {case.expect_state}, got {got['state']}")
        if case.expect_partial is not None:
            check(label + " -> partial",
                  got["partial"] == case.expect_partial,
                  f"expected partial={case.expect_partial}, "
                  f"got {got['partial']}")
        # A decoder must never be able to assert that a payload was
        # authenticated; only UALC core can do that.
        check(label + " -> auth not claimed",
              got["auth_status"] == "unverified",
              f"auth_status was {got['auth_status']!r}, expected 'unverified'")
    return seen


def main() -> int:
    print("UALC adapter contract test")
    print("=" * 64)

    # --- Level 1: declarative profile ------------------------------------
    print("\nCHECK_GROUP_1  Level-1 declarative profile (Python)")
    profile = load_profile(PROFILE_PATH)
    check("profile loads and validates", profile.model_id == "AIR_910604_WW",
          f"model_id was {profile.model_id!r}")
    check("profile declares no hardware testing",
          profile.hardware_tested is False and profile.support_level == "DECODED",
          f"level={profile.support_level} hw={profile.hardware_tested}")
    python_adapter = ProfileAdapter(profile)
    python_results = run_cases("profile", python_adapter)

    print("\nCHECK_GROUP_2  Level-1 profile is read-only by construction")
    check("supported_commands is empty",
          python_adapter.supported_commands() == set(),
          f"got {python_adapter.supported_commands()}")
    try:
        python_adapter.build_outbound(DEVICE_ID, StandardCommand.GET_STATUS)
        check("build_outbound refuses", False, "it returned instead of raising")
    except NotImplementedError:
        check("build_outbound refuses", True)

    # --- Level 2: Lua handler --------------------------------------------
    print("\nCHECK_GROUP_3  Level-2 Lua handler (subprocess)")
    lua_bin = lua_available()
    lua_results: dict[str, dict] = {}
    if lua_bin is None:
        skip("lua handler cases",
             "no 'lua' interpreter on PATH; Python half still ran")
    else:
        print(f"  using {lua_bin}")
        with LuaPlugin(HANDLER_PATH, SDK_PATH,
                       limits=PluginLimits()) as plugin:
            described = plugin.describe()
            check("plugin describes itself",
                  described.get("manufacturer") == "lg"
                  and described.get("protocol_family") == "thinq2_tlv",
                  f"got {described}")
            check("plugin declares a partial operation set "
                  "(no build_outbound)",
                  "parse_inbound" in described["operations"]
                  and "build_outbound" not in described["operations"],
                  f"operations={described.get('operations')}")
            check("plugin reports its own honest status",
                  described.get("support_level") == "DECODED"
                  and described.get("verification_source") == "none",
                  f"got level={described.get('support_level')!r} "
                  f"source={described.get('verification_source')!r}")

            lua_adapter = LuaProtocolAdapter(plugin, "lg", "thinq2_tlv")
            lua_results = run_cases("lua", lua_adapter)

            print("\nCHECK_GROUP_4  Lua capability declaration is enforced")
            check("supported_commands is empty",
                  lua_adapter.supported_commands() == set(),
                  f"got {lua_adapter.supported_commands()}")
            try:
                lua_adapter.build_outbound(DEVICE_ID,
                                           StandardCommand.GET_STATUS)
                check("undeclared build_outbound raises NotImplementedError",
                      False, "it returned instead of raising")
            except NotImplementedError:
                check("undeclared build_outbound raises NotImplementedError",
                      True)

            check("identify accepts its own model",
                  plugin.call("identify",
                              {"model_id": "AIR_910604_WW"})["supported"]
                  is True)
            check("identify refuses a model it does not claim",
                  plugin.call("identify",
                              {"model_id": "AIR_911111_WW"})["supported"]
                  is False,
                  "a handler must not claim sibling models")

    # --- Equivalence ------------------------------------------------------
    print("\nCHECK_GROUP_5  Python and Lua agree (language-neutral contract)")
    if not lua_results:
        skip("python/lua equivalence", "Lua half did not run")
    else:
        for name, py in python_results.items():
            lua = lua_results.get(name)
            if lua is None:
                check(f"equivalence: {name}", False, "missing Lua result")
                continue
            # model_id is reported by both; compare the decode-relevant parts.
            py_cmp = {k: v for k, v in py.items() if k != "model_id"}
            lua_cmp = {k: v for k, v in lua.items() if k != "model_id"}
            check(f"equivalence: {name}", py_cmp == lua_cmp,
                  f"python={py_cmp} lua={lua_cmp}")

    print("\n" + "=" * 64)
    print(f"passed={_passed} failed={_failed} skipped={_skipped}")
    if _failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS" + (" (with skips)" if _skipped else ""))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LuaHostError as exc:
        traceback.print_exc()
        print(f"\nLua host error: {exc}")
        raise SystemExit(2)
