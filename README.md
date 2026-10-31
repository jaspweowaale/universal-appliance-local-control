# Universal Appliance Local Control

**Status: pre-alpha, private development repository. Not ready for production use with any real device.**

Reusable infrastructure for operating cloud-dependent smart-home appliances
locally, without the manufacturer's cloud, from Home Assistant or anything
else. Two independent components:

- **`router/`** — a manufacturer-independent TCP/TLS pass-through proxy.
  Routes connections by source IP/MAC/destination/protocol, relays bytes
  byte-for-byte without ever inspecting or terminating TLS, health-checks
  upstreams, and automatically falls back to the manufacturer's cloud if a
  local endpoint becomes unhealthy. Contains **zero manufacturer-specific
  code**.
- **`translator/`** — an adapter-based protocol translator. Converts
  manufacturer-specific device messages into a standardized event/command
  format (`integration_contract.py`) that a consumer like Home Assistant can
  use without knowing anything about the underlying protocol. One adapter
  so far: `translator/adapters/roborock_b01.py` (Roborock's "B01" protocol
  family).

They communicate only through the shared `StandardMessage` envelope in
`integration_contract.py` — neither imports the other.

## What this is NOT (yet)

This repository does not currently give you local control of any real
device. Development/testing was done entirely against:
- synthetic loopback traffic,
- a from-scratch minimal MQTT broker (`testing_infra/minimal_mqtt_broker.py`
  — test infrastructure only, not a production broker),
- a self-signed test certificate.

The Roborock B01 adapter's *runtime* encode/decode logic reuses
`python-roborock`'s own shipped, production code — the real Home Assistant
Roborock integration uses the same library. That part is solid. What's
missing is everything needed to get a real device to trust a local endpoint
in the first place (TLS certificate trust, bootstrap/session establishment,
device-specific credentials) — see `docs/ARCHITECTURE.md` for exactly what's
proven vs. what's still an open question, and `SECURITY.md` for why the
bootstrap layer specifically is deliberately not included here.

## Install

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`router/` and `translator/` (minus the Roborock adapter) have **zero**
third-party dependencies. `python-roborock` (`>=7.12.0`, Apache-2.0 — see
`THIRD_PARTY_NOTICES.md` for the verified license history) is only needed
if you use the Roborock adapter.

## Run the tests

```
PYTHONPATH=router:. .venv/bin/python router/test_router_offline.py
PYTHONPATH=router:. .venv/bin/python router/test_router_hardening.py
PYTHONPATH=translator:translator/adapters:. .venv/bin/python translator/test_translator_offline.py
PYTHONPATH=translator:translator/adapters:. .venv/bin/python translator/test_translator_hardening.py
PYTHONPATH=testing_infra:.:router:translator .venv/bin/python testing_infra/task4_integration_test.py
```

All five suites (65 checks total) pass against a clean `requirements.txt`
install, verified before every push to this repo.

## Adding a new manufacturer/device

Implement `translator/base.py`'s `ProtocolAdapter` interface in a new file
under `translator/adapters/`, register it, and it works with the existing
router and `HomeAssistantInterface` unchanged. See
`translator/adapters/roborock_b01.py` for a complete example and
`docs/ARCHITECTURE.md` for the design rationale.

## Example

`examples/demo_end_to_end.py` runs a complete simulated flow — fake device →
router → fake local endpoint → translator → simulated Home Assistant
consumer → standardized command → back through the router to the device —
entirely on loopback with synthetic data.

## License

This project's own code is MIT-licensed — see `LICENSE`. Third-party
dependencies and their licenses are listed in `THIRD_PARTY_NOTICES.md`
(`python-roborock`, pinned `>=7.12.0`, is Apache-2.0).
