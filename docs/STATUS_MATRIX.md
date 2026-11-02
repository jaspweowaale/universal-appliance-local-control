# Status matrix

Evidence levels (not combined):
- **IMPLEMENTED** — working code exists.
- **TESTED OFFLINE** — repeatable tests vs fixtures/simulators.
- **VERIFIED ON HARDWARE** — observed against the real appliance.
- **VERIFIED CLOUD-FREE** — confirmed operating with the manufacturer cloud unavailable.
- **PUBLICATION READY** — sanitized, licensed, independently reproducible.

## Roborock Q10 (roborock.vacuum.ss09 / B01)
| Capability | Level | Evidence |
|---|---|---|
| B01 protocol model (DPS envelope, code map) | IMPLEMENTED (python-roborock) | `b01_q10_protocol`, `b01_q10_code_mappings` |
| Outbound command encoding | IMPLEMENTED (python-roborock) | `encode_mqtt_payload` |
| Command→broker→device-model→decode | TESTED OFFLINE | `testing_infra/b01_cloudfree_integration_test.py` (5/5) |
| HA-side adapter: correlation/timeout/errors | IMPLEMENTED + TESTED OFFLINE | `translator/adapters/b01_local_bridge.py`, `testing_infra/b01_bridge_test.py` (7/7) |
| Real ss09 command/telemetry | NOT ACHIEVED | needs device transport (secret/session creds, TLS trust, redirect) |
| Cloud-independent ss09 operation | NOT ACHIEVED | same blockers |

## Toshiba GR-RF900WI (Midea M-Smart V3)
| Capability | Level | Evidence |
|---|---|---|
| Local temperature/status read (TCP 6444) | VERIFIED ON HARDWARE | live in production HA; `sensor.242992069879584_*` |
| Local control (8370 handshake with token/key) | VERIFIED ON HARDWARE | prod |
| Reuse cloud-issued LAN creds (Level A) | VERIFIED CLOUD-FREE | handshake is local-only; creds recovered + 2-of-3 recovery tested |
| Permanent LAN-only after registration (Level B) | PARTIAL (untested on HW) | client has no cred expiry/refresh; device-side revocation unknown — firewall experiment prepared |
| Independent credential generation (Level C) | NOT ACHIEVED / research | token/key minted server-side; device-side validation mechanism unanalyzed |

## Publication
| Item | Level |
|---|---|
| universal-appliance-local-control (framework + B01 + tests) | git-history/licensing audit PASS; docs added; **approval-gated** (private) |
| toshiba-tsmartlife-local | separate repo, already public |
