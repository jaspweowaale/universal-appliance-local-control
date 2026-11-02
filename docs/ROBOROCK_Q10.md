# Roborock Q10 (B01) — local / cloud-replacement research

Honest status of this project's Roborock work. Read the four maturity levels below before
assuming anything is "done" — most of this is **offline-tested only**.

## Device
- Model: `roborock.vacuum.ss09` (Roborock Q10), protocol family **B01**.
- Cloud transport observed on the real device: **MQTT over TLS to Roborock's AWS broker**
  (device → `*.iot.roborock.com` / an AWS IoT endpoint on `:8883`). The device is an outbound
  MQTT *client*; it runs no accepted local control listener (a direct TCP connect to the legacy
  `:58867` A01/V1 port is reset by this B01 device).

## Four maturity levels (do not conflate)

### 1. Protocol reversed — YES (library + analysis)
B01 Q10 uses a DPS (data-point) command model. The MQTT payload envelope is plain JSON:
`{"dps": {"<code>": params}}`. Commands/among the code map (`roborock.data.b01_q10`):
`REQUEST_DPS=102`, `START_CLEAN=201`, `PAUSE=204`, `STOP=206`, `FAN_LEVEL=123`, `WATER_LEVEL=124`, …
Encoding/decoding is provided by **python-roborock** (`roborock.protocols.b01_q10_protocol`:
`encode_mqtt_payload`, `encode_clean_params`, `decode_rpc_response`). This project does **not**
re-implement the protocol; it reuses that library.

### 2. Offline / simulator tested — YES (this repo)
Two cloud-free tests (localhost MQTT-TLS broker only, no Roborock cloud):
- `testing_infra/b01_cloudfree_integration_test.py` — command → local broker → python-roborock
  `Q10VacuumSimulator` → decoded response. **5/5** (REQUEST_DPS→status dump; START_CLEAN→CLEANING;
  PAUSE/STOP state transitions).
- `testing_infra/b01_bridge_test.py` — the `B01LocalBridge` HA-side adapter
  (`translator/adapters/b01_local_bridge.py`): full command loop, **request correlation** by DP
  code, **timeout** (`B01CommandTimeout`), and **error handling** (malformed inbound survives).
  **7/7**.

These validate the command/response path + local-broker wiring over real MQTT framing and TLS
**against python-roborock's own device model** — the strongest independent anchor available
offline is the shared `B01_Q10_DP` code table. They do **not** use a captured real-device payload.

### 3. Actual hardware verified — NO
No command or telemetry has been exchanged with a physical ss09 through this stack. All level-2
results are against a simulator.

### 4. Cloud-independent hardware operation — NO (blocked)
To make the real ss09 talk to a local replacement broker you must satisfy its outbound cloud
connection locally. Missing / unknown inputs:

| Need | Status |
|---|---|
| `duid`, `localKey` | have (HA storage) |
| B01 bootstrap `secret` (32-char, per-device) | **missing** — on-device `device.json` only; not in the cloud account API, app, or python-roborock; not derivable |
| Activation `session`/`token` (reconnect MQTT creds) | **missing** |
| Device trusts a substituted TLS cert (HTTPS bootstrap + MQTT `:8883`) | **unknown** (sc05 trusts public CAs; ss09 + pinning unverified) |
| ss09 uses HMAC-v1 bootstrap (not RSA-v2 → HTTP 501) | **unknown** (sc05-only) |
| Endpoint redirection (local DNS) | requires owner authorization |

## Architecture (Route B)
`local_roborock_server` as the **device-facing** replacement cloud (emulates the Roborock
MQTT broker + HTTP bootstrap; B01 region/NC + inbound decode implemented and 25/25 offline
tests pass, validated on **sc05** hardware — **not** ss09). python-roborock supplies the
protocol/client. `B01LocalBridge` (this repo) is the thin HA-side command/response adapter.

## Reproduce the offline tests
```bash
python -m venv .venv && . .venv/bin/activate
pip install "python-roborock>=7.12.0" aiomqtt cryptography
python testing_infra/b01_cloudfree_integration_test.py   # 5/5
python testing_infra/b01_bridge_test.py                  # 7/7
# (uses a self-signed cert on 127.0.0.1 and a bundled minimal MQTT broker; no cloud, no device)
```

## Known limitations / open questions
See the repo issues: ss09 reconnect-vs-bootstrap; B01 TLS trust/pinning; real-hardware
validation of the encoder; local_roborock_server ss09 support; (Toshiba items live in the
separate Toshiba repo).

## References & licenses
- python-roborock — Apache-2.0 (v5.34.0+), not vendored, pinned `>=7.12.0`. Authors:
  humbertogontijo, Lash-L, allenporter. https://github.com/Python-roborock/python-roborock
- local_roborock_server — referenced prior art. https://github.com/Python-roborock/local_roborock_server
- This project — MIT.
