# Contributing to UALC

**UALC is built on the assumption that the maintainers do not own your
appliance.** That is not an apology — it is the design constraint the whole
architecture is shaped around. You have the hardware in your house; we do
not. The project's job is to make your observations usable by everyone else
without requiring us to buy a copy of your washing machine.

So: adding support for a brand, model or protocol **we have never touched**
is a first-class contribution, not an edge case.

New here? Start with [`docs/contributing/DEVICE_CONTRIBUTION.md`](docs/contributing/DEVICE_CONTRIBUTION.md).

## What you can contribute

| | What | Needs hardware? | Needs code? |
|---|---|---|---|
| 1 | A new **model profile** for an already-supported protocol | no (fixtures are enough) | no — JSON only |
| 2 | A **Lua device handler** for model-specific decoding | no | Lua |
| 3 | A new **protocol adapter** (genuinely new protocol) | usually yes | Python |
| 4 | **Verified protocol mappings** — "tag 0x1f9 value 16 means auto" | yes | no |
| 5 | **Sanitized protocol captures** as fixtures | yes | no |
| 6 | **Test fixtures** for an existing model | no | no |
| 7 | **Authentication / provisioning documentation** | varies | no |
| 8 | **Improvements** to an existing model's support | no | maybe |
| 9 | **Firmware compatibility reports** — "works/breaks on x.y.z" | yes | no |
| 10 | **Hardware validation** of someone else's untested work | yes | no |

Items 4, 5, 7, 9 and 10 need **no programming at all** and are among the most
valuable things anyone can send us, because they are the things we
structurally cannot produce ourselves. Validating a contribution somebody
else wrote but could never test is a real contribution with your name on it.

## The three extension levels

Pick the lowest one that works. Most contributions are Level 1.

| Level | You write | Runs as | Use when |
|---|---|---|---|
| **1 — Model profile** | `devices/<vendor>/<MODEL>.json` | data, interpreted by core | your appliance speaks a supported protocol and differs only in field meanings |
| **2 — Lua handler** | `plugins/lua/<vendor>_<model>/` | isolated subprocess | you need device-specific logic, quirks, or conditional decoding |
| **3 — Protocol adapter** | `translator/adapters/<name>.py` | in UALC core | the protocol itself is new |

Specs: [model profile](docs/MODEL_PROFILE_SPEC.md) ·
[plugin manifest & wire contract](docs/PLUGIN_MANIFEST_SPEC.md) ·
[Lua architecture & security](docs/LUA_PLUGIN_ARCHITECTURE.md)

**You should not need to modify the universal router or the Home Assistant
interface to add a compatible model.** If you find yourself having to, say so
in your PR — that is a bug in our abstraction, and we would rather fix it
than have you work around it.

## Honesty about status is not optional

UALC tracks *how far the work got* separately from *who verified it, on
what*. See [`docs/SUPPORT_LEVELS.md`](docs/SUPPORT_LEVELS.md). The rules are
**enforced by the validator**, so an overstated claim fails CI:

* a plugin that passes offline tests is **not** "working on hardware";
* your hardware test is `COMMUNITY_HARDWARE_TESTED`, never
  `MAINTAINER_HARDWARE_TESTED`;
* a device running locally on **cloud-issued credentials** is not
  `CLOUD_INDEPENDENT`;
* synthetic fixtures are not captures.

A contribution marked `DECODED`, `verification_source: none`,
`hardware_tested: false` is a **good** contribution. Nobody is asking you to
overstate it. Fill in `known_limitations` and we will merge it for what it is.

## Before you open a pull request

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Level 1 — profile validation (loads every file under devices/)
PYTHONPATH=translator:testing_infra:. .venv/bin/python testing_infra/profile_validation_test.py

# Cross-language adapter contract (Python profile vs Lua handler)
PYTHONPATH=translator:testing_infra:. .venv/bin/python testing_infra/adapter_contract_test.py

# Lua sandbox and host behaviour
PYTHONPATH=translator:testing_infra:. .venv/bin/python testing_infra/plugin_security_test.py
```

The Lua suites **skip cleanly** if you have no `lua` on PATH, so you can
always run the Python half. Install Lua 5.4+ to exercise them.

Existing framework suites must also still pass — see the README.

Then fill in the [pull request template](.github/PULL_REQUEST_TEMPLATE.md).
For hardware results use the
[hardware test report template](docs/contributing/HARDWARE_TEST_REPORT.md).

## Privacy and safety rules

These are hard requirements, not preferences.

1. **Never commit credentials.** No tokens, device secrets, local keys, cloud
   passwords, certificates or API keys — not in code, not in fixtures, not in
   a capture, not in a screenshot. The profile validator rejects
   credential-shaped keys outright.
2. **We will never ask for your manufacturer account credentials**, and you
   must never put them in an issue or PR. If a task appears to need them,
   that is a design problem for us to solve, not a thing for you to hand over.
3. **Sanitize captures before committing.** Strip MAC and IP addresses,
   serial numbers, device IDs, account identifiers, Wi-Fi SSIDs, geolocation
   and timestamps that identify you. Use RFC 5737 documentation addresses
   (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) and obviously-fake
   identifiers. Details:
   [`DEVICE_CONTRIBUTION.md`](docs/contributing/DEVICE_CONTRIBUTION.md) §4.
4. **Only capture traffic on networks and devices you own or are authorised
   to test.**
5. **Do not include third-party captures** you do not have the right to
   redistribute.

## Licensing

UALC's own code is **MIT**. Contributions are accepted under MIT — opening a
PR means you are licensing your contribution that way (inbound = outbound,
no CLA).

**Check the licence of anything you learn from.** Reimplementing a documented
wire format is fine; a protocol is not a copyrightable expression. Copying
another project's decoder, its comments or its captured fixtures is not —
especially from a GPL project, which would be incompatible with MIT. If your
understanding came from someone else's work:

* implement it independently;
* record where the knowledge came from in `source_provenance` (plugin) or
  `notes` (profile);
* say so in the PR, so we can check rather than guess.

See `THIRD_PARTY_NOTICES.md` and the reference plugin's header for worked
examples. We would much rather have an awkward conversation about provenance
than a licence violation in the tree.

## Reviewing executable contributions

Lua handlers are **executable code from someone we may not know**, so they go
through [`docs/PLUGIN_REVIEW_POLICY.md`](docs/PLUGIN_REVIEW_POLICY.md):
reviewed by reading, sandboxed at runtime, `enabled_by_default: false`, and
never run on the machine hosting production Home Assistant. There is **no
plugin marketplace and no automatic execution of community code.** That is a
deliberate permanent choice, not a missing feature.

## Conduct

See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
