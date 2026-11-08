"""UALC Lua plugin host (Level 2 extension point).

Runs a community Lua device handler as an **isolated subprocess** and speaks
NDJSON to it over stdio. The Lua side is `plugins/lua/ualc_sdk.lua`; the wire
contract is documented in `docs/PLUGIN_MANIFEST_SPEC.md`.

Why a subprocess and not an in-process Lua binding (e.g. lupa):
  * no new Python dependency -- this module is stdlib-only;
  * a crash, hang or memory blow-up in a community handler cannot take the
    UALC core down with it;
  * the OS, not the Lua interpreter, enforces the limits that actually matter.

Security posture, stated honestly (see docs/LUA_PLUGIN_ARCHITECTURE.md S6):
this is **defence in depth, not a sandbox strong enough for arbitrary hostile
code**. It raises the cost of a malicious plugin considerably; it does not
reduce it to zero. Community plugins are reviewed before being enabled, are
disabled by default, and are never run in the production Home Assistant
process. For genuinely untrusted code, run the host inside a container or VM.

Specifically enforced here:
  * separate process, no shell;
  * POSIX rlimits: CPU time, address space, open files, child processes, and
    RLIMIT_FSIZE=0 so the handler cannot create or extend any file;
  * a wall-clock timeout per request and a hard kill on overrun;
  * a cap on response size, so a handler cannot exhaust host memory by
    replying with an enormous line;
  * strict validation of everything coming back before it reaches
    StandardMessage;
  * **no credential is ever passed into a plugin.** The contract has no field
    for one. Authentication stays in UALC core / the Python adapter layer.

Not enforced here, and not claimed:
  * no network namespace isolation (Lua's stdlib has no sockets and
    package.loadlib is removed, but that is a Lua-level argument, not an OS
    one);
  * rlimits are POSIX-only -- on Windows this host runs the plugin with
    timeouts and output caps but WITHOUT rlimits, which is weaker;
  * RLIMIT_AS is honoured inconsistently by some allocators/platforms.
"""
from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from base import ProtocolAdapter
from integration_contract import (
    AuthStatus,
    Direction,
    MessageType,
    StandardCommand,
    StandardMessage,
)

# Distros name the interpreter differently (`lua`, `lua5.4`, `lua54`), so the
# binary is configurable. Set UALC_LUA_BINARY if yours is not called `lua`.
DEFAULT_LUA_BINARY = os.environ.get("UALC_LUA_BINARY") or "lua"

# Conservative defaults. A reviewer may raise them per plugin, in the manifest.
DEFAULT_LIMITS = {
    "cpu_seconds": 2,
    "address_space_bytes": 256 * 1024 * 1024,
    "open_files": 16,
    "max_processes": 0,          # no fork/exec from inside the handler
    "request_timeout_seconds": 5.0,
    "max_response_bytes": 256 * 1024,
}

PLUGIN_ERROR_CODES = {
    "UNSUPPORTED_MODEL",
    "UNSUPPORTED_PROTOCOL_VERSION",
    "MALFORMED_FRAME",
    "UNSUPPORTED_COMMAND",
    "INVALID_PARAMS",
    "FIRMWARE_INCOMPATIBLE",
    "NOT_IMPLEMENTED",
    "INTERNAL_ERROR",
}


class LuaPluginError(RuntimeError):
    """A plugin returned a structured {"ok": false, "error": {...}} response."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


class LuaHostError(RuntimeError):
    """The host could not get a usable answer: crash, hang, bad output."""


def lua_available(binary: str = DEFAULT_LUA_BINARY) -> str | None:
    """Absolute path to a usable Lua interpreter, or None.

    Callers use this to skip Lua tests cleanly rather than fail them: a
    contributor without Lua installed must still be able to run the Python
    half of the suite.
    """
    return shutil.which(binary)


@dataclass(frozen=True)
class PluginLimits:
    cpu_seconds: int = DEFAULT_LIMITS["cpu_seconds"]
    address_space_bytes: int = DEFAULT_LIMITS["address_space_bytes"]
    open_files: int = DEFAULT_LIMITS["open_files"]
    max_processes: int = DEFAULT_LIMITS["max_processes"]
    request_timeout_seconds: float = DEFAULT_LIMITS["request_timeout_seconds"]
    max_response_bytes: int = DEFAULT_LIMITS["max_response_bytes"]


def _apply_rlimits(limits: PluginLimits):
    """Build a preexec_fn applying rlimits in the child, or None on Windows.

    preexec_fn runs between fork and exec; it must only call async-signal-safe
    things. setrlimit qualifies. (It is also why this host should not be used
    from a heavily threaded parent without care -- documented, not hidden.)
    """
    if os.name != "posix":
        return None

    import resource

    def _preexec():
        resource.setrlimit(resource.RLIMIT_CPU,
                           (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NOFILE,
                           (limits.open_files, limits.open_files))
        # RLIMIT_FSIZE = 0: the handler cannot create or grow a file. Writing
        # to the stdout *pipe* is unaffected, because a pipe is not a file
        # subject to this limit.
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC,
                               (limits.max_processes, limits.max_processes))
        except (ValueError, OSError):
            # Not available or not permitted everywhere; the other limits and
            # the removal of os.execute/package.loadlib still apply.
            pass
        try:
            resource.setrlimit(resource.RLIMIT_AS,
                               (limits.address_space_bytes,
                                limits.address_space_bytes))
        except (ValueError, OSError):
            pass

    return _preexec


class LuaPlugin:
    """A running Lua handler. One subprocess per plugin instance.

    Per-device isolation: instantiate one LuaPlugin per device (or per device
    group) rather than sharing one across devices, so a handler cannot carry
    state -- or a fault -- from one appliance to another.
    """

    def __init__(
        self,
        handler_path: str,
        sdk_path: str,
        lua_binary: str = DEFAULT_LUA_BINARY,
        limits: PluginLimits | None = None,
        env: dict[str, str] | None = None,
    ):
        self.handler_path = os.path.abspath(handler_path)
        self.sdk_path = os.path.abspath(sdk_path)
        self.limits = limits or PluginLimits()
        self._seq = 0
        self._proc: subprocess.Popen | None = None
        self._selector: selectors.BaseSelector | None = None

        for p in (self.handler_path, self.sdk_path):
            if not os.path.isfile(p):
                raise LuaHostError(f"not a file: {p}")

        resolved = shutil.which(lua_binary) or lua_binary
        # Minimal environment: nothing about the host leaks in, and no
        # LUA_PATH/LUA_CPATH that could pull in arbitrary modules.
        self._env = {
            "PATH": "/usr/bin:/bin",
            "LUA_PATH": "",
            "LUA_CPATH": "",
            "LC_ALL": "C",
        }
        if env:
            self._env.update(env)
        self._argv = [resolved, self.sdk_path, self.handler_path]

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._proc is not None:
            raise LuaHostError("plugin already started")
        try:
            self._proc = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(self.sdk_path) or ".",
                env=self._env,
                preexec_fn=_apply_rlimits(self.limits),
                close_fds=True,
                shell=False,
                bufsize=0,
            )
        except (OSError, ValueError) as exc:
            raise LuaHostError(f"could not start Lua plugin: {exc}") from exc
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._proc.stdout, selectors.EVENT_READ)

    def stop(self, timeout: float = 2.0) -> None:
        """Safe disabling: close stdin so the handler's read loop ends, then
        escalate to terminate/kill. Always leaves no process behind."""
        if self._proc is None:
            return
        if self._selector is not None:
            try:
                self._selector.close()
            except Exception:
                pass
            self._selector = None
        proc, self._proc = self._proc, None
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=timeout)

    def __enter__(self) -> "LuaPlugin":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- request/response --------------------------------------------------

    def _read_line(self, deadline: float) -> bytes:
        """Read one newline-terminated response, bounded by time and size."""
        assert self._proc is not None and self._selector is not None
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LuaHostError(
                    f"plugin timed out after "
                    f"{self.limits.request_timeout_seconds:g}s")
            if not self._selector.select(timeout=remaining):
                continue
            byte = self._proc.stdout.read(1)
            if byte == b"":
                raise LuaHostError(
                    "plugin closed its output stream "
                    f"(exit code {self._proc.poll()}); "
                    f"stderr: {self._drain_stderr()[:400]!r}")
            if byte == b"\n":
                return b"".join(chunks)
            chunks.append(byte)
            total += 1
            if total > self.limits.max_response_bytes:
                raise LuaHostError(
                    f"plugin response exceeded "
                    f"{self.limits.max_response_bytes} bytes")

    def _drain_stderr(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            os.set_blocking(self._proc.stderr.fileno(), False)
            data = self._proc.stderr.read() or b""
        except Exception:
            return ""
        return data.decode("utf-8", "replace")

    def call(self, op: str, args: dict[str, Any] | None = None) -> Any:
        """Invoke one plugin operation. Raises LuaPluginError for a
        structured plugin-side failure, LuaHostError for a broken plugin."""
        if not self.running:
            raise LuaHostError("plugin is not running")
        self._seq += 1
        request = {"id": str(self._seq), "op": op, "args": args or {}}

        # Refuse to forward anything credential-shaped into a plugin, even if
        # a caller mistakenly supplies it. Belt and braces around the contract.
        _assert_no_credentials(request["args"])

        line = json.dumps(request, separators=(",", ":"),
                          allow_nan=False).encode()
        deadline = time.monotonic() + self.limits.request_timeout_seconds
        try:
            self._proc.stdin.write(line + b"\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise LuaHostError(
                f"plugin stdin unusable: {exc}; "
                f"stderr: {self._drain_stderr()[:400]!r}") from exc

        try:
            raw = self._read_line(deadline)
        except LuaHostError:
            self.stop()
            raise

        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LuaHostError(f"plugin emitted invalid JSON: {exc}") from exc
        if not isinstance(response, dict):
            raise LuaHostError("plugin response was not a JSON object")
        if response.get("id") != request["id"]:
            raise LuaHostError(
                f"plugin response id mismatch: sent {request['id']!r}, "
                f"got {response.get('id')!r}")

        if response.get("ok") is True:
            return response.get("result")
        if response.get("ok") is False:
            err = response.get("error")
            if not isinstance(err, dict):
                raise LuaHostError("plugin error response had no error object")
            code = err.get("code")
            if code not in PLUGIN_ERROR_CODES:
                raise LuaHostError(f"plugin used unknown error code {code!r}")
            raise LuaPluginError(code, str(err.get("message", "")),
                                 err.get("details"))
        raise LuaHostError("plugin response had no boolean 'ok' field")

    # -- convenience -------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        result = self.call("describe")
        if not isinstance(result, dict):
            raise LuaHostError("describe did not return an object")
        ops = result.get("operations")
        if not isinstance(ops, list) or not all(isinstance(o, str) for o in ops):
            raise LuaHostError("describe.operations must be a list of strings")
        return result


_CREDENTIAL_HINTS = (
    "password", "passwd", "secret", "token", "localkey", "local_key",
    "credential", "private_key", "apikey", "api_key", "passphrase",
)


def _assert_no_credentials(obj: Any, _depth: int = 0) -> None:
    if _depth > 12:
        raise LuaHostError("plugin arguments nested too deeply")
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() in _CREDENTIAL_HINTS:
                raise LuaHostError(
                    f"refusing to pass credential-shaped key {key!r} "
                    "to a plugin")
            _assert_no_credentials(value, _depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_credentials(item, _depth + 1)


class LuaProtocolAdapter(ProtocolAdapter):
    """Presents a Lua plugin as an ordinary UALC ProtocolAdapter.

    This is the whole point of the design: the router, the registry and
    `HomeAssistantInterface` cannot tell a Lua-backed device from a
    Python-backed one, so adding a Lua handler needs no change to UALC core.

    A plugin declares which operations it implements; anything it does not
    implement raises NotImplementedError, matching the existing Python
    adapter contract rather than inventing a second convention.
    """

    def __init__(self, plugin: LuaPlugin, manufacturer: str,
                 protocol_family: str):
        self.plugin = plugin
        self.manufacturer = manufacturer
        self.protocol_family = protocol_family
        self._operations = set(plugin.describe().get("operations", []))

    def implements(self, op: str) -> bool:
        return op in self._operations

    def _require(self, op: str) -> None:
        if not self.implements(op):
            raise NotImplementedError(
                f"Lua plugin for {self.manufacturer}/{self.protocol_family} "
                f"does not implement {op!r}")

    def parse_inbound(self, device_id: str, topic: str,
                      payload: bytes) -> StandardMessage:
        self._require("parse_inbound")
        try:
            result = self.plugin.call("parse_inbound", {
                "device_id": device_id,
                "topic": topic,
                "payload_hex": payload.hex(),
            })
        except LuaPluginError as exc:
            # A plugin reporting "I cannot read this" is a normal outcome, not
            # a crash: surface it as ADAPTER_ERROR, exactly as the Python
            # adapters do.
            return StandardMessage(
                device_id=device_id,
                protocol_adapter=self._adapter_name(),
                direction=Direction.INBOUND,
                message_type=MessageType.ADAPTER_ERROR,
                payload={"code": exc.code, "message": exc.message,
                         "details": exc.details},
                auth_status=AuthStatus.NOT_APPLICABLE,
            )

        if not isinstance(result, dict):
            raise LuaHostError("parse_inbound did not return an object")
        state = result.get("state", {})
        if not isinstance(state, dict):
            raise LuaHostError("parse_inbound.state must be an object")
        _assert_json_scalars(state)

        return StandardMessage(
            device_id=device_id,
            protocol_adapter=self._adapter_name(),
            direction=Direction.INBOUND,
            message_type=MessageType.DEVICE_EVENT,
            payload={
                "event_kind": result.get("event_kind", "status"),
                "state": state,
                "partial": bool(result.get("partial", False)),
                "model_id": result.get("model_id"),
            },
            # A Lua handler decodes bytes; it does not verify credentials, so
            # it must never be able to claim VERIFIED.
            auth_status=AuthStatus.UNVERIFIED,
        )

    def build_outbound(self, device_id: str,
                       command: StandardCommand) -> tuple[str, bytes]:
        self._require("build_outbound")
        try:
            result = self.plugin.call("build_outbound", {
                "device_id": device_id,
                "command": command.value,
                "params": {},
            })
        except LuaPluginError as exc:
            if exc.code in ("UNSUPPORTED_COMMAND", "NOT_IMPLEMENTED"):
                raise NotImplementedError(
                    f"plugin does not support {command.value}: "
                    f"{exc.message}") from exc
            raise
        if not isinstance(result, dict):
            raise LuaHostError("build_outbound did not return an object")
        topic = result.get("topic")
        payload_hex = result.get("payload_hex")
        if not isinstance(topic, str):
            raise LuaHostError("build_outbound.topic must be a string")
        if not isinstance(payload_hex, str):
            raise LuaHostError("build_outbound.payload_hex must be a string")
        try:
            payload = bytes.fromhex(payload_hex)
        except ValueError as exc:
            raise LuaHostError(
                f"build_outbound.payload_hex is not valid hex: {exc}") from exc
        return topic, payload

    def supported_commands(self) -> set[StandardCommand]:
        if not self.implements("supported_commands"):
            return set()
        result = self.plugin.call("supported_commands")
        if not isinstance(result, list):
            raise LuaHostError("supported_commands did not return a list")
        out: set[StandardCommand] = set()
        for name in result:
            try:
                out.add(StandardCommand(name))
            except ValueError:
                # Forward-compatibility: a newer plugin may name a command
                # this UALC version has never heard of. Ignore it rather than
                # refuse to load the plugin at all.
                continue
        return out

    def is_ack_for(self, command: StandardCommand,
                   inbound_payload: dict) -> bool:
        self._require("is_ack_for")
        result = self.plugin.call("is_ack_for", {
            "command": command.value,
            "payload": inbound_payload,
        })
        if not isinstance(result, bool):
            raise LuaHostError("is_ack_for must return a boolean")
        return result

    def validate_command(self, command: str,
                         params: dict[str, Any]) -> dict[str, Any]:
        """Optional op, beyond the base ProtocolAdapter interface: ask the
        plugin to check parameters before anything is encoded or sent."""
        self._require("validate_command")
        result = self.plugin.call("validate_command",
                                  {"command": command, "params": params})
        if not isinstance(result, dict):
            raise LuaHostError("validate_command did not return an object")
        return result

    def _adapter_name(self) -> str:
        return f"lua:{self.manufacturer}_{self.protocol_family}"


def _assert_json_scalars(state: dict[str, Any], _depth: int = 0) -> None:
    """Device state must be plain scalars/containers of scalars. Keeps a
    plugin from smuggling something structurally surprising into the
    StandardMessage payload."""
    if _depth > 6:
        raise LuaHostError("plugin state nested too deeply")
    for key, value in state.items():
        if not isinstance(key, str):
            raise LuaHostError("plugin state keys must be strings")
        if isinstance(value, dict):
            _assert_json_scalars(value, _depth + 1)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _assert_json_scalars(item, _depth + 1)
                elif not isinstance(item, (str, int, float, bool)) \
                        and item is not None:
                    raise LuaHostError(
                        f"plugin state list item has unsupported type "
                        f"{type(item).__name__}")
        elif not isinstance(value, (str, int, float, bool)) and value is not None:
            raise LuaHostError(
                f"plugin state key {key!r} has unsupported type "
                f"{type(value).__name__}")


def default_sdk_path() -> str:
    """Path to plugins/lua/ualc_sdk.lua relative to the repository root."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "plugins", "lua", "ualc_sdk.lua")


if __name__ == "__main__":  # tiny manual smoke aid, not a test
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <handler.lua>", file=sys.stderr)
        raise SystemExit(2)
    if not lua_available():
        print("no 'lua' interpreter on PATH", file=sys.stderr)
        raise SystemExit(1)
    with LuaPlugin(sys.argv[1], default_sdk_path()) as p:
        print(json.dumps(p.describe(), indent=2))
