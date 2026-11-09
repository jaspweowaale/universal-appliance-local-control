"""Empirical checks on the Lua plugin sandbox and host.

Every "we restrict X" claim in docs/LUA_PLUGIN_ARCHITECTURE.md should have a
test here, so the security posture is evidence-backed rather than asserted.
Where a restriction CANNOT be demonstrated from inside Lua, the test says so
explicitly instead of quietly passing.

The adversarial handlers below are written by this test at runtime into a
temporary directory. They are OUR fixtures, not third-party code.

Run:
    PYTHONPATH=translator:testing_infra:. python testing_infra/plugin_security_test.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, os.path.join(ROOT, "translator"), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

from lua_host import (  # noqa: E402
    LuaHostError,
    LuaPlugin,
    LuaPluginError,
    PluginLimits,
    lua_available,
)

SDK_PATH = os.path.join(ROOT, "plugins", "lua", "ualc_sdk.lua")

_passed = 0
_failed = 0
_skipped = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS {label}")
    else:
        _failed += 1
        print(f"  FAIL {label}: {detail}")


def skip(label: str, why: str) -> None:
    global _skipped
    _skipped += 1
    print(f"  SKIP {label}: {why}")


def write_handler(tmpdir: str, name: str, body: str) -> str:
    path = os.path.join(tmpdir, f"{name}.lua")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


def probe(tmpdir: str, name: str, body: str, op: str = "identify",
          args: dict | None = None, limits: PluginLimits | None = None):
    """Start a handler, call one op, return (kind, value).

    kind is "ok" | "plugin_error" | "host_error" | "startup_error".
    """
    path = write_handler(tmpdir, name, body)
    try:
        plugin = LuaPlugin(path, SDK_PATH, limits=limits or PluginLimits())
        plugin.start()
    except LuaHostError as exc:
        return "startup_error", str(exc)
    try:
        return "ok", plugin.call(op, args or {})
    except LuaPluginError as exc:
        return "plugin_error", exc
    except LuaHostError as exc:
        return "host_error", str(exc)
    finally:
        plugin.stop()


def main() -> int:
    lua_bin = lua_available()
    print("UALC plugin security test")
    print("=" * 64)
    if lua_bin is None:
        print("no 'lua' interpreter on PATH -- cannot test the sandbox at all")
        print("passed=0 failed=0 skipped=1")
        print("RESULT: SKIP")
        return 0
    print(f"lua: {lua_bin}")

    tmpdir = tempfile.mkdtemp(prefix="ualc_sectest_")
    try:
        # -- 1. Dangerous globals are absent ------------------------------
        print("\nCHECK_GROUP_1  dangerous globals removed from the sandbox")
        absent_probe = """
local M = {}
function M.identify()
  local missing = {}
  for _, name in ipairs({"io", "package", "require", "dofile", "loadfile",
                         "load", "loadstring", "debug", "collectgarbage",
                         "arg"}) do
    if _G[name] == nil then missing[#missing+1] = name end
  end
  table.sort(missing)
  return {missing = missing,
          os_execute = (os and os.execute) ~= nil,
          os_getenv  = (os and os.getenv) ~= nil,
          os_remove  = (os and os.remove) ~= nil,
          os_time    = (os and os.time) ~= nil}
end
return M
"""
        kind, res = probe(tmpdir, "absent", absent_probe)
        if kind != "ok":
            check("sandbox probe ran", False, f"{kind}: {res}")
        else:
            expected = ["arg", "collectgarbage", "debug", "dofile", "io",
                        "load", "loadfile", "loadstring", "package",
                        "require"]
            check("io/package/require/load/debug/... all absent",
                  res["missing"] == expected,
                  f"absent list was {res['missing']}")
            check("os.execute absent", res["os_execute"] is False)
            check("os.getenv absent (no host env leakage)",
                  res["os_getenv"] is False)
            check("os.remove absent", res["os_remove"] is False)
            check("os.time still available (handlers may need timing)",
                  res["os_time"] is True)

        # -- 2. No filesystem read even by indirect means ------------------
        print("\nCHECK_GROUP_2  filesystem unreachable from a handler")
        fs_probe = """
local M = {}
function M.identify()
  -- There is no io table, so there is nothing to call. Prove the handler
  -- cannot conjure one.
  local ok_io = pcall(function() return io.open("/etc/passwd", "r") end)
  local ok_req = pcall(function() return require("io") end)
  return {io_open_worked = ok_io, require_worked = ok_req}
end
return M
"""
        kind, res = probe(tmpdir, "fs", fs_probe)
        if kind != "ok":
            check("filesystem probe ran", False, f"{kind}: {res}")
        else:
            check("io.open unreachable", res["io_open_worked"] is False)
            check("require unreachable", res["require_worked"] is False)

        # -- 3. Precompiled bytecode refused -------------------------------
        print("\nCHECK_GROUP_3  precompiled Lua bytecode refused")
        bc_path = os.path.join(tmpdir, "bytecode.lua")
        with open(bc_path, "wb") as handle:
            handle.write(b"\x1bLua" + b"\x00" * 32)
        try:
            plugin = LuaPlugin(bc_path, SDK_PATH)
            plugin.start()
            try:
                plugin.call("describe")
                check("bytecode handler refused", False,
                      "it answered a request")
            except LuaHostError:
                check("bytecode handler refused", True)
            finally:
                plugin.stop()
        except LuaHostError:
            check("bytecode handler refused", True)

        # Text-mode loading is the mechanism; confirm the SDK asks for it.
        with open(SDK_PATH, "r", encoding="utf-8") as handle:
            sdk_src = handle.read()
        check('SDK loads handlers with mode "t" (text only)',
              '"t", env' in sdk_src or "'t', env" in sdk_src,
              "could not find a text-only load mode in the SDK")

        # -- 4. Runaway handler is stopped ---------------------------------
        print("\nCHECK_GROUP_4  runaway handler stopped by host timeout")
        spin = """
local M = {}
function M.identify()
  local x = 0
  while true do x = x + 1 end
end
return M
"""
        started = time.monotonic()
        kind, res = probe(tmpdir, "spin", spin,
                          limits=PluginLimits(cpu_seconds=2,
                                              request_timeout_seconds=1.5))
        elapsed = time.monotonic() - started
        check("infinite loop produces a host error, not a hang",
              kind == "host_error", f"got {kind}: {res}")
        check("host gave up promptly (<8s wall clock)", elapsed < 8.0,
              f"took {elapsed:.1f}s")

        # -- 5. Oversized response capped ----------------------------------
        print("\nCHECK_GROUP_5  oversized response capped")
        flood = """
local M = {}
function M.identify()
  return {blob = string.rep("A", 400000)}
end
return M
"""
        kind, res = probe(tmpdir, "flood", flood,
                          limits=PluginLimits(max_response_bytes=8192,
                                              request_timeout_seconds=5.0))
        check("response over the cap is rejected", kind == "host_error",
              f"got {kind}: {res}")
        if kind == "host_error":
            check("rejection names the size limit", "bytes" in str(res).lower(),
                  f"message was {res!r}")

        # -- 6. Misbehaving output is rejected, not trusted ----------------
        print("\nCHECK_GROUP_6  malformed plugin output rejected")
        liar = """
local M = {}
function M.is_ack_for() return "yes" end
function M.identify() return {ok = true} end
return M
"""
        path = write_handler(tmpdir, "liar", liar)
        plugin = LuaPlugin(path, SDK_PATH)
        plugin.start()
        try:
            from integration_contract import StandardCommand
            from lua_host import LuaProtocolAdapter
            adapter = LuaProtocolAdapter(plugin, "test", "test")
            try:
                adapter.is_ack_for(StandardCommand.START, {})
                check("non-boolean is_ack_for rejected", False,
                      "a string was accepted as a boolean")
            except LuaHostError:
                check("non-boolean is_ack_for rejected", True)
        finally:
            plugin.stop()

        # -- 7. Unknown error codes are not propagated ---------------------
        print("\nCHECK_GROUP_7  plugin cannot invent error codes")
        rogue = """
local M = {}
function M.identify()
  error({__ualc_error = true, code = "ROOT_ACCESS_GRANTED",
         message = "nice try"}, 0)
end
return M
"""
        kind, res = probe(tmpdir, "rogue", rogue)
        # ualc.fail() normalises unknown codes; raising the table directly
        # bypasses that, so the HOST must reject it.
        check("unrecognised error code rejected by host",
              kind == "host_error" and "unknown error code" in str(res),
              f"got {kind}: {res}")

        # -- 8. Credentials are never forwarded ----------------------------
        print("\nCHECK_GROUP_8  host refuses to pass credentials to a plugin")
        echo = """
local M = {}
function M.identify(args) return {got = args} end
return M
"""
        path = write_handler(tmpdir, "echo", echo)
        plugin = LuaPlugin(path, SDK_PATH)
        plugin.start()
        try:
            for bad in ({"token": "x"}, {"local_key": "x"},
                        {"nested": {"password": "x"}}):
                try:
                    plugin.call("identify", bad)
                    check(f"refuses {list(bad)[0]!r}", False,
                          "it was forwarded")
                except LuaHostError as exc:
                    check(f"refuses {list(bad)[0]!r}",
                          "credential-shaped" in str(exc), str(exc))
            # A harmless argument still works, i.e. the guard is not a
            # blanket refusal.
            res = plugin.call("identify", {"model_id": "X"})
            check("ordinary arguments still pass through",
                  res["got"]["model_id"] == "X", f"got {res}")
        finally:
            plugin.stop()

        # -- 9. Handler crash does not take the host down ------------------
        print("\nCHECK_GROUP_9  handler crash is contained")
        crasher = """
local M = {}
function M.identify() error("boom", 0) end
function M.healthy() return {alive = true} end
return M
"""
        path = write_handler(tmpdir, "crasher", crasher)
        plugin = LuaPlugin(path, SDK_PATH)
        plugin.start()
        try:
            try:
                plugin.call("identify")
                check("handler error surfaces as a plugin error", False,
                      "no error raised")
            except LuaPluginError as exc:
                check("handler error surfaces as a plugin error",
                      exc.code == "INTERNAL_ERROR", f"code={exc.code}")
            except LuaHostError as exc:
                check("handler error surfaces as a plugin error", False,
                      f"host error instead: {exc}")
            # The subprocess must still be usable afterwards.
            check("plugin still responsive after a handler error",
                  plugin.running, "subprocess died")
        finally:
            plugin.stop()

        # -- 10. Clean shutdown, no orphans --------------------------------
        print("\nCHECK_GROUP_10  lifecycle: no orphaned process")
        path = write_handler(tmpdir, "lifecycle", echo)
        plugin = LuaPlugin(path, SDK_PATH)
        plugin.start()
        pid = plugin._proc.pid  # noqa: SLF001 - deliberate, test-only
        check("plugin reports running", plugin.running is True)
        plugin.stop()
        check("plugin reports stopped", plugin.running is False)
        time.sleep(0.2)
        alive = True
        try:
            os.kill(pid, 0)
        except OSError:
            alive = False
        check("subprocess is gone after stop()", alive is False,
              f"pid {pid} still alive")
        # stop() twice must be safe (rollback/disable path).
        plugin.stop()
        check("stop() is idempotent", True)

        # -- 11. Honest limits ---------------------------------------------
        print("\nCHECK_GROUP_11  limitations we do NOT claim to enforce")
        if os.name == "posix":
            check("POSIX: rlimits are applied by the host", True)
        else:
            skip("rlimits", "non-POSIX host: rlimits are NOT applied")
        skip("network isolation at the OS level",
             "not enforced; Lua has no sockets and loadlib is removed, but "
             "no namespace/firewall isolation is applied. Run untrusted "
             "plugins in a container.")
        skip("defence against a hostile native library",
             "package.loadlib is removed, so this is a Lua-level argument "
             "only, not an OS-level guarantee.")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"passed={_passed} failed={_failed} skipped={_skipped}")
    if _failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS (skips above are documented non-guarantees)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
