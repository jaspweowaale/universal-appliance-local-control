# UALC plugin manifest and wire contract — API version 1.0

This is the language-neutral interface between **UALC Core** (Python) and a
**community adapter**. Lua is the first non-Python implementation; nothing in
this document is Lua-specific, and a plugin in another language that speaks
the same NDJSON protocol would work unchanged.

Normative schema: [`../schemas/plugin_manifest.schema.json`](../schemas/plugin_manifest.schema.json).
Reference plugin: [`../plugins/lua/examples/lg_air_910604_ww/`](../plugins/lua/examples/lg_air_910604_ww/).
Design rationale and security limits: [`LUA_PLUGIN_ARCHITECTURE.md`](LUA_PLUGIN_ARCHITECTURE.md).

## 1. Layout

```
plugins/lua/<vendor>_<model>/
    manifest.json      identity, capabilities, limits, honest status
    handler.lua        the implementation
    README.md          what it does, what it does not, how it was verified
```

## 2. Manifest

### `plugin`

| Key | Required | Notes |
|---|---|---|
| `id` | yes | stable, dotted, lowercase: `<vendor>.<family>.<model>` |
| `name` | yes | human-readable |
| `version` | yes | semver of the plugin itself |
| `language` | yes | `lua` (the only executable language in 1.0) |
| `entrypoint` | yes | path relative to the manifest |
| `maintainers` | yes | GitHub handles — who to ask when an appliance misbehaves |
| `license` | yes | must be MIT-compatible; see §8 |
| `source_provenance` | yes | where the protocol knowledge came from. **If your work derives from someone else's code, say so here and in the PR.** |

### `requires`

| Key | Required | Notes |
|---|---|---|
| `min_ualc_api_version` | yes | refuse to load on an older core |
| `max_ualc_api_version` | no | e.g. `"1.x"` |
| `lua_version` | for Lua | e.g. `"5.4+"` |

### `supports`

```json
"supports": {
  "manufacturers": ["lg"],
  "protocol_families": ["thinq2_tlv"],
  "models": [
    {
      "model_id": "AIR_910604_WW",
      "marketing_names": ["PuriCare 360"],
      "device_class": "air_purifier",
      "firmware_ranges": [],
      "notes": "regional SKUs behind this id differ in their mode enum"
    }
  ]
}
```

**`firmware_ranges: []` means "unknown", not "all".** Claim the models and
firmware you actually observed. A shared model id, chipset or cloud platform
is not evidence of a shared local protocol — UALC has already seen the same
LG ThinQ model id behave differently across regions.

### `operations`

The list of operation names your handler implements. Must match what
`describe` returns. A plugin declares its surface; the host never assumes a
uniform one.

### `capabilities`

| Key | Notes |
|---|---|
| `read` | field names your handler can decode |
| `write` | field names it can encode. `[]` for a decoder — a legitimate, common case |
| `partial_state_updates` | true if you distinguish delta frames from full state |
| `reports_incompatibility` | true if you return `UNSUPPORTED_*` rather than guessing |

### `authentication`

```json
"authentication": {
  "required": false,
  "handled_by": "ualc_core",
  "plugin_receives_credentials": false
}
```

`plugin_receives_credentials` **must be `false`**. There is no mechanism to
set it true. Authentication stays in UALC core; the host refuses to forward
credential-shaped keys even if a caller passes them
(`plugin_security_test.py`, group 8). If your appliance needs a per-device
secret to decode its traffic, that is a core change and a Level-3
conversation, not a plugin field.

### `permissions`

Declare intent explicitly, so a reviewer can compare it with the diff. In
1.0 every value must be `"none"` — the sandbox provides no mechanism to grant
any of them. They exist so a plugin that *wants* more is visibly asking.

```json
"permissions": {"filesystem": "none", "network": "none",
                "subprocess": "none", "environment": "none"}
```

### `limits`

Optional per-plugin overrides of the host defaults
(`cpu_seconds` 2, `address_space_bytes` 256 MiB, `open_files` 16,
`request_timeout_seconds` 5.0, `max_response_bytes` 256 KiB). A reviewer may
raise them; a plugin cannot raise them for itself at runtime.

### `support_status`

Same vocabulary as a model profile — see [`SUPPORT_LEVELS.md`](SUPPORT_LEVELS.md).
Include `fixtures: "synthetic" | "captured"` and a populated
`known_limitations`.

### `enabled_by_default`

**Must be `false`** for community plugins. Experimental executable
contributions stay off until someone turns them on deliberately.

## 3. Wire protocol

NDJSON over stdin/stdout: one JSON object per line, UTF-8, no embedded
newlines. stderr is for diagnostics and is captured by the host on failure.

**Request:**

```json
{"id":"7","op":"parse_inbound","args":{"device_id":"d1","topic":"t","payload_hex":"0000040000..."}}
```

**Success:**

```json
{"id":"7","ok":true,"result":{ ... }}
```

**Failure:**

```json
{"id":"7","ok":false,"error":{"code":"MALFORMED_FRAME","message":"...","details":null}}
```

Rules the host enforces:

* `id` must be echoed exactly; a mismatch is a host error, not a retry;
* `ok` must be a real boolean;
* `code` must be from the closed set below — an unknown code is rejected
  outright, so a plugin cannot invent `ROOT_ACCESS_GRANTED`;
* the response line is capped (default 256 KiB) and the cap is applied while
  reading, so an oversized reply cannot exhaust host memory;
* binary is **lowercase hex** in `payload_hex`, because JSON has no byte type.

### Error codes

| Code | Use for |
|---|---|
| `UNSUPPORTED_MODEL` | not a model this plugin claims |
| `UNSUPPORTED_PROTOCOL_VERSION` | well-formed, but a variant/dialect you do not claim |
| `MALFORMED_FRAME` | structurally broken input |
| `UNSUPPORTED_COMMAND` | command this model cannot do |
| `INVALID_PARAMS` | bad arguments |
| `FIRMWARE_INCOMPATIBLE` | recognised model, firmware you know differs |
| `NOT_IMPLEMENTED` | operation deliberately absent |
| `INTERNAL_ERROR` | your bug |

Keep `UNSUPPORTED_PROTOCOL_VERSION` and `MALFORMED_FRAME` distinct. "I cannot
read this" and "this is corrupt" lead to different conclusions in a support
matrix.

## 4. Operations

All optional. Omit what your appliance cannot do.

### `describe` → object

```json
{"api_version":"1.0","manufacturer":"lg","protocol_family":"thinq2_tlv",
 "models":["AIR_910604_WW"],"operations":["describe","identify", ...],
 "support_level":"DECODED","verification_source":"none","notes":"..."}
```

If you do not implement it, the SDK synthesises one from your handler's keys.

### `identify` → object

Args `{"model_id": "...", "hints": {...}}`.
Return `{"supported":true,"model_id":"...","confidence":"exact"}` or
`{"supported":false,"model_id":"...","reason":"..."}`.
**Do not claim models you have not seen.**

### `parse_inbound` / `decode_state` → object

Args `{"device_id","topic","payload_hex"}`.

```json
{"model_id":"AIR_910604_WW","event_kind":"status",
 "state":{"power":"on","pm25":10},"partial":false}
```

* `state` values must be scalars, or maps/lists of scalars. Type-checked.
* `partial: true` means "this is a delta". The host will not treat absent
  fields as cleared. Getting this wrong wipes known state on every change
  notification.
* For an unmapped enum value emit `"<field>": "unknown"` and
  `"<field>_raw": <int>`. Report; do not coerce.
* To refuse a frame, call `ualc.fail("MALFORMED_FRAME", "...")`. The host
  converts it to an `ADAPTER_ERROR` message rather than treating it as a
  crash.

**You cannot set `auth_status`.** UALC core builds the `StandardMessage` and
always marks plugin-decoded state `UNVERIFIED`. A decoder decodes; it does
not authenticate.

### `supported_commands` → array of `StandardCommand` names

`[]` is valid and honest for a decoder. Names unknown to this UALC version
are ignored rather than causing a load failure, so a newer plugin still works
on an older core.

### `validate_command` → object

Args `{"command","params"}` → `{"valid":bool,"reason":"..."}`.
Called **before** anything is encoded or sent.

### `build_outbound` → object

Args `{"device_id","command","params"}` →
`{"topic":"...","payload_hex":"..."}`.

Only implement this if you have **verified** the frame format, including any
checksum. If you have not, leave it out: the host raises
`NotImplementedError`, which is correct behaviour. The reference plugin
deliberately omits it for exactly this reason.

### `describe_controls` → object

```json
{"readable":["power","pm25"],"writable":[],
 "enums":{"power":["on","off"]}}
```

### `is_ack_for` → boolean

Args `{"command","payload"}`. Must return a real boolean; anything else is
rejected by the host.

## 5. Lifecycle

1. **Load** — host reads the manifest, checks `min_ualc_api_version`, checks
   `enabled_by_default` / operator opt-in.
2. **Start** — one subprocess per device (or device group). Per-device
   isolation is the default so a handler cannot carry state or a fault
   between appliances.
3. **Handshake** — host calls `describe`, records the operation set.
4. **Serve** — one request at a time per process; the host enforces the
   timeout.
5. **Fault** — a plugin error becomes `ADAPTER_ERROR`; a host error (hang,
   bad output, closed pipe) stops the subprocess and surfaces upward.
6. **Stop** — close stdin, then terminate, then kill. Idempotent, leaves no
   orphan (`plugin_security_test.py`, group 10).

## 6. Compatibility checks

| Check | When | Failure |
|---|---|---|
| `min_ualc_api_version` vs core | load | refuse to load |
| `describe.api_version` vs core | handshake | refuse to load |
| `operations` vs manifest | handshake | refuse to load |
| `identify(model_id)` | device appears | device is not routed to this plugin |
| `firmware_ranges` | device appears | warn; a plugin may return `FIRMWARE_INCOMPATIBLE` itself |
| response shape | every call | host error, plugin stopped |

## 7. The SDK available to your handler

Inside the sandbox you have `ualc.API_VERSION`, `ualc.array(t)`,
`ualc.hex_to_bytes`, `ualc.bytes_to_hex`, `ualc.fail(code, message, details)`,
`ualc.ERROR_CODES`, plus `json.encode`/`decode`, and the standard
`string`/`table`/`math`/`utf8`/`coroutine` libraries and `os.time`/`clock`/
`difftime`.

Not available, by design: `io`, `os.execute`, `os.getenv`, `os.remove`,
`package`, `require`, `load`, `loadstring`, `dofile`, `loadfile`, `debug`,
`collectgarbage`, `arg`. Precompiled bytecode is refused. See
`LUA_PLUGIN_ARCHITECTURE.md` §6 for what this does and does not guarantee.

## 8. Licensing

UALC is MIT. A plugin must be MIT-compatible.

**Do not port GPL code into a plugin.** Reimplementing a documented wire
format from a field list is fine — a protocol is not a copyrightable
expression. Copying someone's decoder, their comments, or their captured
fixtures is not. If your knowledge came from a GPL project, implement
independently, record it in `source_provenance`, and say so in the PR. The
reference plugin's header is a worked example.
