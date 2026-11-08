# Writing a UALC Lua device handler

Level 2 of the [extension hierarchy](../../CONTRIBUTING.md). Use it when a
declarative [model profile](../MODEL_PROFILE_SPEC.md) cannot express what
your appliance does — conditional decoding, quirks, state that depends on
another field.

**Try Level 1 first.** If your appliance differs from a supported one only in
which tag means what, a profile is less code, needs no sandbox, and is
reviewed by reading it.

Wire contract: [`../PLUGIN_MANIFEST_SPEC.md`](../PLUGIN_MANIFEST_SPEC.md).
Why it is built this way, and the security limits:
[`../LUA_PLUGIN_ARCHITECTURE.md`](../LUA_PLUGIN_ARCHITECTURE.md).

## Requirements

* Lua **5.4 or newer** (5.5 is what we test on). No third-party Lua libraries
  — the SDK gives you JSON and hex helpers precisely so you do not need any.
* `lua` on your PATH for the tests. Without it the Lua suites skip.

## Start from the reference

```
plugins/lua/examples/lg_air_910604_ww/
    handler.lua      read this top to bottom; it is commented for exactly this purpose
    manifest.json
```

Copy it to `plugins/lua/<vendor>_<model>/` and work from there.

## Shape of a handler

```lua
local M = {}

function M.describe()
  return {
    api_version = ualc.API_VERSION,
    manufacturer = "acme",
    protocol_family = "acme_binary",
    models = ualc.array({"ACME-1234"}),
    operations = ualc.array({"describe", "identify", "parse_inbound"}),
    support_level = "DECODED",
    verification_source = "none",
  }
end

function M.identify(args)
  if args.model_id == "ACME-1234" then
    return {supported = true, model_id = args.model_id, confidence = "exact"}
  end
  return {supported = false, model_id = args.model_id,
          reason = "this handler claims only ACME-1234"}
end

function M.parse_inbound(args)
  local bytes = ualc.hex_to_bytes(args.payload_hex)
  if #bytes < 4 then
    ualc.fail("MALFORMED_FRAME", "need at least 4 bytes, got " .. #bytes)
  end
  return {
    model_id = "ACME-1234",
    event_kind = "status",
    state = {power = (bytes[1] == 1) and "on" or "off"},
    partial = false,
  }
end

return M   -- a table of operations. Nothing else.
```

Your handler must `return` a table. Implement only the operations your
appliance actually supports — a partial set is normal and the host enforces
it correctly. The reference handler implements eight of nine operations and
deliberately omits `build_outbound`.

## Rules that will bite you if you ignore them

**Set `partial` correctly.** `partial = true` means "this frame is a delta".
Get it wrong and every change notification wipes the state the host already
knew. If your appliance sends both full-state and single-field frames, you
must distinguish them — usually by element count or a frame-type byte.

**Report unmapped enum values, never coerce them.**

```lua
state.mode = MODES[raw]
if state.mode == nil then
  state.mode = "unknown"
  state.mode_raw = raw          -- so the real value survives into the report
end
```

A value nobody has documented is a finding about the appliance. Clamping it
to the nearest known mode invents confidence you have not earned.

**Fail structurally, not by crashing.** `ualc.fail(code, message)` becomes an
`ADAPTER_ERROR` the host handles cleanly. A bare Lua `error()` becomes
`INTERNAL_ERROR` — which is a bug report about you, not about the appliance.
Keep `MALFORMED_FRAME` ("this is corrupt") distinct from
`UNSUPPORTED_PROTOCOL_VERSION` ("well-formed, but a variant I do not claim").

**Only implement `build_outbound` if you have verified the frame format,
including any checksum.** Leaving it out is correct and the host raises
`NotImplementedError`. Emitting unverified bytes at real hardware is the one
thing a handler must not do.

**Do not claim sibling models.** Same model id across regions has already
been observed to differ. Claim what you tested.

**You cannot set `auth_status`.** UALC core builds the `StandardMessage` and
always marks plugin-decoded state `UNVERIFIED`. Decoding is not
authentication.

## What the sandbox gives you

Available: `ualc.API_VERSION`, `ualc.array`, `ualc.hex_to_bytes`,
`ualc.bytes_to_hex`, `ualc.fail`, `ualc.ERROR_CODES`, `json.encode`/`decode`,
and `string` · `table` · `math` · `utf8` · `coroutine` ·
`os.time`/`clock`/`difftime`.

**Not** available: `io`, `os.execute`, `os.getenv`, `os.remove`, `package`,
`require`, `load`, `loadstring`, `dofile`, `loadfile`, `debug`,
`collectgarbage`, `arg`. Precompiled bytecode is refused.

So: no file access, no network, no subprocesses, no host environment, no
reading other devices' data. If your handler seems to need any of those, it
is not a Level-2 contribution — open an issue and let us talk about it.

Your handler also runs under a CPU limit, a memory limit, a per-request
timeout and a response-size cap (defaults in the manifest spec). Decode
frames; do not mine bitcoin.

## Bit arithmetic

Lua 5.4+ has native operators — use them rather than `bit32` (which does not
exist here):

```lua
local tag  = (b0 << 2) | (b1 >> 6)
local lsel = (b1 >> 4) & 0x03
local low  = b1 & 0x0f
```

Beware `//` (floor division) versus `/` (always float). Use `//` for byte
maths so you do not accidentally produce `3.0` where the contract expects an
integer.

## Arrays versus objects

Lua cannot distinguish an empty list from an empty map. Wrap sequences you
want encoded as JSON arrays:

```lua
operations = ualc.array({"describe", "identify"})
readable   = ualc.array({})     -- encodes as [], not {}
```

A plain non-empty table with keys `1..n` is detected as an array
automatically; empty tables default to `{}`.

## Test it

Add your frames to `testing_infra/contract_fixtures.py` as `ContractCase`
entries, then:

```bash
PYTHONPATH=translator:testing_infra:. python testing_infra/adapter_contract_test.py
PYTHONPATH=translator:testing_infra:. python testing_infra/plugin_security_test.py
```

Quick manual look at what your handler advertises:

```bash
PYTHONPATH=translator:. python translator/lua_host.py plugins/lua/<yours>/handler.lua
```

If you also write a Level-1 profile for the same device, the contract test
will compare the two and require they agree — a cheap, strong check on both.
The reference device does exactly this, and writing it caught two real
divergences (a truthiness test on `power`, and a bounds check in the Python
codec) before either shipped.

## Submitting

Your plugin stays `enabled_by_default: false`, is reviewed by reading
([policy](../PLUGIN_REVIEW_POLICY.md)), and is recorded at the support level
your evidence supports — `DECODED` with synthetic fixtures, `CAPTURED` with
real ones, `COMMUNITY_HARDWARE_TESTED` only with a
[hardware test report](HARDWARE_TEST_REPORT.md).

Then follow [`DEVICE_CONTRIBUTION.md`](DEVICE_CONTRIBUTION.md) step 10.
