# UALC model profile specification — version 1.0

A **model profile** adds support for an appliance model using declarative
data only. If your appliance speaks a protocol UALC already understands and
differs only in which field means what, this is all you need to write, and
**no UALC source file changes**.

Normative schema: [`../schemas/model_profile.schema.json`](../schemas/model_profile.schema.json).
What CI actually enforces: `validate_profile()` in `translator/profiles.py`
(stdlib-only, so UALC gains no `jsonschema` dependency). The two are kept in
agreement; if they ever disagree, the Python validator wins and the schema is
the bug.

Location: `devices/<manufacturer>/<MODEL_ID>.json`
Reference: [`../devices/lg/AIR_910604_WW.json`](../devices/lg/AIR_910604_WW.json)

## Hard rules

A profile is **data, not behaviour**. Enforced at load time:

* no executable expressions — anything matching `${`, `$(`, backticks,
  `eval`, `exec`, `import`, `lambda`, `os.`, `subprocess`, `require(`,
  `loadstring`, `<%`, `{{` is rejected anywhere in the document;
* no credentials — any key named like `password`, `token`, `secret`,
  `local_key`, `api_key`, `passphrase`, `duid` … is rejected;
* no shell commands, no file paths to execute, no URLs to fetch;
* unknown top-level keys are rejected, so a typo cannot silently disable a
  constraint;
* `codec` must name a codec implemented in UALC core. A genuinely new
  protocol is a **Level 3** contribution, not a profile.

Because of these, profiles are **not** sandboxed — they cannot express
anything to sandbox. Review them by reading them.

## Document structure

```json
{
  "profile_version": "1.0",
  "model":    { ... },
  "protocol": { ... },
  "fields":   [ ... ],
  "commands": [],
  "support_status": { ... },
  "notes": "free text"
}
```

### `model`

| Key | Required | Notes |
|---|---|---|
| `manufacturer` | yes | lowercase `[a-z0-9_]+`; must match the `devices/<dir>` name |
| `model_id` | yes | the identifier the appliance or its cloud reports, verbatim |
| `device_class` | yes | one of `air_purifier`, `air_conditioner`, `refrigerator`, `vacuum`, `washer`, `dryer`, `dishwasher`, `water_heater`, `dehumidifier`, `oven`, `other` |
| `marketing_names` | no | list of strings, for humans |
| `firmware_ranges` | no | list of strings. **Empty means "unknown", not "all".** |

### `protocol`

| Key | Required | Notes |
|---|---|---|
| `family` | yes | protocol family, e.g. `thinq2_tlv` |
| `codec` | yes | a codec name implemented in `translator/profiles.py` → `CODECS` |
| `parameters` | yes | codec-specific; every key is validated against a closed list |

Codecs available in 1.0:

#### `lg_thinq2_tlv`

LG ThinQ2 TLV frames. Parameters, all required unless noted:

| Parameter | Type | Meaning |
|---|---|---|
| `envelope_prefix` | list of 1–8 bytes | fixed byte sequence that identifies the frame |
| `envelope_prefix_offset` | int 0–64 | where that sequence starts |
| `dialect_offset` | int 0–64 | offset of the appliance-class marker byte |
| `dialect_byte` | int 0–255 | the marker value this profile claims |
| `tlv_body_offset` | int 0–64 | first byte of the TLV body |
| `trailer_bytes` | int 0–8 | trailing bytes to ignore (checksum) |
| `full_state_min_elements` | int ≥ 1 | element count at or above which a frame counts as a full state rather than a delta |
| `rejected_dialects` | object (optional) | `{"0x87": "why"}` — produces `UNSUPPORTED_PROTOCOL_VERSION` with your explanation instead of a bare parse failure |

TLV element encoding, so a reviewer can verify a profile without a device:

```
tag   = (b0 << 2) | (b1 >> 6)          10-bit tag
lsel  = (b1 >> 4) & 0x03               0 => value is the low nibble of b1
value = (b1 & 0x0f)                    if lsel == 0
        big-endian over lsel bytes     otherwise
width = 2 + lsel
```

### `fields`

Non-empty list. One entry per tag you can name.

| Key | Required | Notes |
|---|---|---|
| `tag` | yes | **hex string** like `"0x1f7"`, within the 10-bit space `0x000`–`0x3ff`. Unique. |
| `name` | yes | snake_case `[a-z][a-z0-9_]*`. Unique. Becomes the key in decoded state. |
| `type` | yes | `enum`, `integer`, `boolean`, `string` |
| `values` | for `enum` | `{"13": "clean_booster", ...}` — decimal-string keys, non-empty string values |
| `unit` | no | free text, e.g. `"ug/m3"`, `"h"` |
| `writable` | no | boolean, documentation only in 1.0 |

**Out-of-domain enum values are reported, never coerced.** A raw value with no
mapping decodes as `"<name>": "unknown"` plus `"<name>_raw": <int>`. This is
deliberate: a value nobody has documented is a finding about the appliance,
and silently clamping it to the nearest known mode manufactures confidence
you have not earned.

Unrecognised tags do not fail the frame; they increment
`unknown_tag_count` in the decoded state so you can see there is more to map.

### `commands`

**Must be empty in 1.0.** Declarative command *encoding* is not supported,
on purpose: a wrong frame reaches real hardware. To send commands, write a
Level-2 Lua handler or a Level-3 Python adapter. `ProfileAdapter.build_outbound`
always raises `NotImplementedError`.

### `support_status`

| Key | Required | Notes |
|---|---|---|
| `level` | yes | see [`SUPPORT_LEVELS.md`](SUPPORT_LEVELS.md) |
| `verification_source` | yes | `none`, `community`, `maintainer`, `both` |
| `hardware_tested` | yes | boolean |
| `known_limitations` | strongly recommended | list of strings; say what you did **not** do |

Cross-field honesty rules are enforced — see `SUPPORT_LEVELS.md`. A new
profile with no hardware behind it is `DECODED` / `none` / `false`, and that
is a perfectly good contribution.

## Decoded output

A profile produces a `StandardMessage` with:

```python
payload = {
    "event_kind": "status",
    "state": {...},        # your field names -> decoded values
    "partial": bool,       # fewer elements than full_state_min_elements
    "model_id": "...",
}
auth_status = AuthStatus.UNVERIFIED   # always; a decoder verifies nothing
```

`partial` matters: on a partial frame the host must **not** treat absent
fields as cleared. A single-tag change notification carries one field, and
everything else the host already knew stays known.

## Validate your profile

```bash
PYTHONPATH=translator:testing_infra:. python testing_infra/profile_validation_test.py
```

This loads every file under `devices/` — so a broken contributed profile
fails CI rather than failing later on somebody's appliance.

To exercise your profile against frames, add cases to
`testing_infra/contract_fixtures.py` and run
`testing_infra/adapter_contract_test.py`.

## YAML

JSON is the committed format. YAML input is acceptable in a pull request if
you prefer writing it; a maintainer will convert it, because adding a YAML
parser would add a dependency to an otherwise stdlib-only core. The schema is
identical either way.
