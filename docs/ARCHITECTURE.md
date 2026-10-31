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

1. **GPL-3.0 dependency.** `python-roborock` (used only by the Roborock adapter) is GPL-3.0-only; this project's own code is MIT. See `THIRD_PARTY_NOTICES.md`. Needs a deliberate decision (e.g. making the Roborock adapter a separate, clearly-GPL-licensed optional package, or accepting the dependency with clear documentation) before a public release under a project-wide MIT claim would be accurate.
2. **No real-device validation of anything beyond the runtime encode/decode path.** The router and translator are solid in isolation; nothing here has been shown to work against a real appliance.
3. **`testing_infra/minimal_mqtt_broker.py` needs a clear, loud "do not use in production" marker** if it's ever referenced outside this repo's own test suite.
