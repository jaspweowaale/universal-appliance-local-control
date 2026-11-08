# Architecture

## Two independent projects, one shared contract

**`router/`** — manufacturer-independent TCP/TLS pass-through proxy.
`models.py` (connection metadata), `policy.py` (per-device policy table,
ambiguous matches fail closed rather than guess), `proxy.py`
(`ApplianceRouter` — relays bytes byte-for-byte, never inspects or
terminates TLS, health-checks upstreams, automatically rolls back to the
manufacturer's cloud after repeated local-endpoint failures, isolated per
device). Contains no manufacturer-specific code anywhere — verified by
inspection, not just by absence of a failing test.

**`translator/`** — adapter-based protocol translation. `base.py`
(`ProtocolAdapter` interface), `registry.py`, `ha_interface.py`
(`HomeAssistantInterface` — the one thing a consumer needs to import),
`credential_store.py` (per-device + per-manufacturer isolation, reports
field *presence* only, never values), `command_tracker.py` (generic
command-acknowledgement/timeout bookkeeping), `adapters/roborock_b01.py`
(first and only adapter).

They communicate only through `integration_contract.py`'s `StandardMessage`
envelope (device_id, protocol_adapter, direction, message_type, payload,
correlation_id, auth_status, timestamp). Neither project imports the other.

## What's proven vs. what's still open

**Proven, with real tests (65 checks across 5 suites, all passing against a
clean `pip install -r requirements.txt`):**
- The router's pass-through, isolation, health-check, and rollback logic — under concurrent connections, long-lived sessions, abrupt disconnects, backpressure, and partial reads/writes.
- The translator's message parsing/building, credential isolation, malformed-input handling, duplicate/reorder tolerance, and command-ack/timeout tracking.
- Real MQTT 3.1.1 wire framing (CONNECT/CONNACK/SUBSCRIBE/SUBACK/PUBLISH) and real TLS (self-signed test certificate) passing through the router without the router ever terminating TLS itself — proven against a from-scratch minimal test broker (`testing_infra/minimal_mqtt_broker.py`), not a production MQTT broker.
- The Roborock adapter's runtime encode/decode path — this reuses `python-roborock`'s own shipped, already-in-production code (the same library the real Home Assistant Roborock integration uses), not something invented for this project.

**Not proven, explicitly:**
- That any real device will ever connect to a local endpoint built with this project. Doing that requires solving TLS certificate trust and device-specific bootstrap/session establishment for the target device — neither is addressed here (see `SECURITY.md` for why the bootstrap layer specifically is out of scope).
- `testing_infra/minimal_mqtt_broker.py` is explicitly test infrastructure, not something to run in production — it implements QoS 0 only, exact-topic matching only, and has not been security-reviewed as a real broker.

## Adding a new manufacturer or device

1. Implement `ProtocolAdapter` (`translator/base.py`) in a new file under `translator/adapters/`.
2. Register it with `AdapterRegistry`.
3. Nothing in `router/` changes — it never needed to know about any manufacturer in the first place.

## Blockers to public release (tracked here, not just in commit messages)

1. ~~GPL-3.0 dependency.~~ **Resolved 2026-10-31.** `python-roborock` relicensed GPL-3.0-only → Apache-2.0 at v5.34.0 (2026-07-20, PR #890); this project now pins `>=7.12.0`, verified Apache-2.0 directly against that tag's `LICENSE`/`pyproject.toml`. An MIT project depending on an Apache-2.0 library via plain `import` (not vendoring) is a standard, unproblematic combination — see `THIRD_PARTY_NOTICES.md`.
2. **No real-device validation of anything beyond the runtime encode/decode path.** The router and translator are solid in isolation; nothing here has been shown to work against a real appliance.
3. **`testing_infra/minimal_mqtt_broker.py` needs a clear, loud "do not use in production" marker** if it's ever referenced outside this repo's own test suite.

---

# UALC extension architecture (added 08 11 2026)

Everything above describes the two original components. This section describes
how **appliance support** is added on top of them — the part that makes UALC
usable for devices the maintainers do not own.

Naming: the project is **Universal Appliance Local Control**, abbreviated
**UALC** throughout. "Project 1" is the router (Level 0 transport); "Project 2"
is the translator, which is UALC core plus the three extension levels below.

## Three extension levels

| Level | Artefact | Executes as | Trust | Needs a UALC core change? |
|---|---|---|---|---|
| **0** | `router/` | Python, in core | trusted | — (transport, never per-device) |
| **1** | `devices/<vendor>/<MODEL>.json` | **data**, interpreted by `translator/profiles.py` | data, validated | **no** |
| **2** | `plugins/lua/<vendor>_<model>/` | **separate OS process**, sandboxed, via `translator/lua_host.py` | **untrusted** | **no** |
| **3** | `translator/adapters/<name>.py` | Python, in core | trusted after review | yes (one registry entry) |

The design rule that makes this work: **all three levels present themselves to
the rest of UALC as an ordinary `ProtocolAdapter`** (`translator/base.py`).
`ProfileAdapter` and `LuaProtocolAdapter` implement the same four abstract
methods as the hand-written `RoborockB01Adapter`. The router, the registry and
`HomeAssistantInterface` cannot tell them apart, so nothing downstream changes
when a new device arrives.

A contributor adding a *compatible model* should therefore never need to touch
the router or the Home Assistant interface. If they do, that is a defect in
the abstraction.

## Trust boundary

```
  TRUSTED (UALC core, Python)                 UNTRUSTED (community code)
  ---------------------------                 --------------------------
  router/          transport
  translator/      adapter dispatch
                   credential_store  <--- never reachable from a plugin
                   ha_interface
                   StandardMessage construction
                   output validation
        |
        |  NDJSON over stdin/stdout
        v
  - - - - - - - - - - process boundary - - - - - - - - - - - - - -
                                              lua subprocess
                                                ualc_sdk.lua   (core, trusted)
                                                handler.lua    (community)
```

Properties that follow from putting the boundary here rather than at an API
surface:

* A plugin **cannot construct a `StandardMessage`.** It returns decoded
  values; Python builds the envelope and forces
  `auth_status = UNVERIFIED`. A decoder therefore cannot assert that anything
  was authenticated.
* A plugin **cannot see credentials.** The wire contract has no credential
  field, and the host refuses to forward credential-shaped keys even if a
  caller mistakenly supplies one.
* A plugin **cannot address a device it was not invoked for.** It is handed
  one `device_id` per call, and the host runs one subprocess per device.
* A plugin **cannot hang or crash the core** — a timeout or a dead pipe
  becomes a host error, and the subprocess is replaced.

Limits of this, stated rather than glossed over: no OS-level network
isolation, rlimits are POSIX-only, and the Lua sandbox is defence in depth
rather than a boundary that would hold against a determined attacker. Full
treatment in [`LUA_PLUGIN_ARCHITECTURE.md`](LUA_PLUGIN_ARCHITECTURE.md) §6.

## Where the per-device knowledge lives

| Knowledge | Lives in | Why |
|---|---|---|
| How to move bytes | `router/` | identical for every appliance |
| How to frame/deframe a protocol family | a **codec** in `translator/profiles.py`, or a Level-3 adapter | shared by many models |
| Which tag means what, for one model | a **Level-1 profile** | the common case, and it is pure data |
| Model-specific logic and quirks | a **Level-2 Lua handler** | needs behaviour a table cannot express |
| Credentials, sessions, auth | UALC core only | never delegated to community code |
| The Home Assistant boundary | `ha_interface.py` | one place, unchanged by new devices |

## Honest-status plumbing

Support level and verification source are part of the **data model**, not
prose in a README: they are fields in every profile and manifest, and
`validate_profile()` rejects internally inconsistent claims at load time, so
an overstated claim fails CI. Vocabulary and rules:
[`SUPPORT_LEVELS.md`](SUPPORT_LEVELS.md).

## Known architectural debt

Recorded here rather than discovered later:

1. **The repository is not an installable package.** Imports rely on
   `PYTHONPATH=translator:testing_infra:.`, which is a papercut for
   contributors and a trap in CI. A `pyproject.toml` with a proper package
   layout is the single highest-value cleanup. Not done here deliberately —
   it would be a large restructuring, and the brief asked for minimal,
   backward-compatible change.
2. **`StandardCommand` is vacuum-shaped.** `GET_STATUS / START / PAUSE / DOCK
   / GET_MAP` does not fit purifiers, ACs or fridges. Extending it is additive
   and backward-compatible, and it blocks any write-capable non-vacuum
   contribution.
3. **Only one Level-1 codec exists** (`lg_thinq2_tlv`), so Level 1 currently
   only helps LG ThinQ2 contributors. A second codec is the main thing that
   would widen Level 1's usefulness.
4. **No declarative command encoding.** Profiles are read-only by design,
   because a wrong frame reaches real hardware. Revisit only with a codec
   that can validate what it emits.

See [`ROADMAP.md`](ROADMAP.md) for how these are prioritised.
