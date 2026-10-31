# Changelog

## [Unreleased] — targeting v0.1.0-alpha

Not yet publicly released. This repository is currently **private**.

### Added
- `router/`: manufacturer-independent TCP/TLS pass-through proxy with per-device policy routing, health-checked automatic cloud fallback, and connection metadata recording.
- `translator/`: adapter-based protocol translator, `HomeAssistantInterface`, credential isolation store, command ack/timeout tracker.
- `translator/adapters/roborock_b01.py`: first protocol adapter, for Roborock's "B01" device family.
- `integration_contract.py`: shared `StandardMessage`/`StandardCommand`/`StandardEventKind` contract between the two projects.
- `testing_infra/`: a from-scratch minimal MQTT 3.1.1 broker and self-signed test certificate generator, used only by this repo's own integration test.
- `examples/demo_end_to_end.py`: a complete simulated device→router→translator→consumer round trip.
- 5 test suites, 65 checks total, all passing against a clean install.

### Known limitations (see `docs/ARCHITECTURE.md`)
- No real-device validation beyond the Roborock adapter's runtime encode/decode path (which reuses `python-roborock`'s own production code).
- `python-roborock` dependency is GPL-3.0-only; project's own code is MIT — unresolved licensing question for public release.
- Bootstrap/session-establishment code is intentionally not included (see `SECURITY.md`).
