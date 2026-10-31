# Third-Party Notices

## python-roborock

- **Used by:** `translator/adapters/roborock_b01.py` (`roborock.protocols.b01_q10_protocol`, `roborock.data.b01_q10.b01_q10_code_mappings`, `roborock.roborock_message`)
- **License: Apache-2.0** (for the version range this project depends on — see below).
- **Not vendored.** This repository declares it as a runtime dependency (`requirements.txt`, pinned `>=7.12.0`) and imports it; no `python-roborock` source code is copied into this repository — verified directly (only `import`/`from ... import` statements, no duplicated function bodies or data tables).
- **License history, verified against the actual upstream source, not assumed:** `python-roborock` was GPL-3.0-only through v5.15.2, then relicensed to Apache-2.0 at **v5.34.0 (2026-07-20, PR #890, commit `a304471`, "Change license to apache 2.0")**. Confirmed independently via (a) PyPI's per-version `license_expression` metadata across the version range, and (b) the actual `LICENSE` file and `pyproject.toml` at the `v7.12.0` git tag (`license = "Apache-2.0"`). Authors per that tag's `pyproject.toml`: humbertogontijo, Lash-L, allenporter.
- **This project depends on `>=7.12.0` specifically** (not just "latest") — comfortably inside the Apache-2.0 era, and the exact version this adapter was developed and tested against. Apache-2.0 does not impose copyleft requirements on dependents that merely `import` the library (as this project does) rather than redistribute its source — the main ongoing obligation is preserving this attribution notice, which this file does.
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
