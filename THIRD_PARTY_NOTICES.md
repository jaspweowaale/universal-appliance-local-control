# Third-Party Notices

## python-roborock

- **Used by:** `translator/adapters/roborock_b01.py` (`roborock.protocols.b01_q10_protocol`, `roborock.data.b01_q10.b01_q10_code_mappings`, `roborock.roborock_message`)
- **License: GPL-3.0-only.**
- **Not vendored.** This repository declares it as a runtime dependency (`requirements.txt`) and imports it; no `python-roborock` source code is copied into this repository.
- **Why this matters:** GPL-3.0 is a strong copyleft license. This project's own code is MIT-licensed, but **the Roborock adapter has a hard runtime dependency on a GPL-3.0 library**. Anyone distributing this project together with `python-roborock` (e.g. as a bundled application, not just "import it from pip") should get their own legal read on what that means for their specific distribution — this notice is informational, not legal advice, and this is flagged as an **open item for the maintainer to resolve before any public release** (see `docs/ARCHITECTURE.md`, "Blockers to public release").
- Project: https://github.com/Python-roborock/python-roborock

## Python-roborock/local_roborock_server

- **Not a dependency of this repository. Not vendored. No code from it is included here.**
- Referenced only in documentation (`translator/adapters/roborock_b01.py`'s module docstring, `docs/ARCHITECTURE.md`) as prior art this project's author studied while researching the Roborock B01 protocol.
- That project is MIT-licensed (copyright Luke Lashley) — noted here for completeness, but since nothing from it is included in this repo, no further obligation applies.
- Its PR #96 (a draft, as of this writing paused pending a responsible-disclosure process on the bootstrap mechanism it implements) is specifically **not** reproduced here — see `SECURITY.md`.
- Project: https://github.com/Python-roborock/local_roborock_server

## aiomqtt

- **Used by:** `testing_infra/task4_integration_test.py` (test infrastructure only, not part of the core router/translator)
- License: BSD-3-Clause (not currently bundled or modified; declared in `requirements.txt`)
- Project: https://github.com/empicano/aiomqtt

## cryptography

- **Used by:** `testing_infra/gen_test_cert.py` (test infrastructure only — generates a self-signed test certificate, never used for anything beyond this repo's own test suite)
- License: Apache-2.0 / BSD (dual), per the `cryptography` project's own terms
- Project: https://github.com/pyca/cryptography
