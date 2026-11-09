# UALC — Universal Appliance Local Control

**An open, modular, manufacturer-independent framework for monitoring and
controlling smart-home appliances locally, reducing or eliminating dependence
on manufacturer cloud services wherever that is technically feasible.**

> **Status: pre-alpha.** The framework is offline-tested (223 checks). **No
> appliance is controllable through UALC on real hardware today** — not one.
> Per-device maturity is tracked honestly in
> [`docs/STATUS_MATRIX.md`](docs/STATUS_MATRIX.md); please read it before
> expecting anything to work.

## Mission

UALC aims to provide an open, modular, manufacturer-independent framework that
allows smart-home appliances to be monitored and controlled locally, reducing
or eliminating dependence on manufacturer cloud services wherever technically
feasible. It is intended to support multiple appliance categories,
manufacturers, protocol families and models.

**UALC is explicitly not limited to the devices owned by its original
developer.** The architecture exists so that someone who owns an appliance we
have never touched can contribute working support for it — and so that we can
accept that contribution without having to trust it with our house, and
without pretending we verified something we could not.

That constraint is the premise of the project, not a caveat on it.

For the reasoning behind the project -- local ownership, longevity, why it avoids
firmware replacement, and its current limits -- see [docs/WHY_UALC.md](docs/WHY_UALC.md).

## Community contributions are a primary development goal

**UALC is designed so other developers can add support for appliance brands
and models that the core maintainers do not own or have access to.** The
bottleneck has never been code — it is hardware access, and the only
scalable fix is making other people's appliances contributable.

You can contribute a model, a protocol adapter, a verified protocol mapping, a
Lua device handler, a sanitized capture, test fixtures, authentication and
provisioning documentation, improvements to an existing model, a firmware
compatibility report, or hardware validation of somebody else's untested work.
Several of those need **no programming at all**, and they are among the most
valuable things we can receive because they are what we structurally cannot
produce ourselves.

Start here: [**CONTRIBUTING.md**](CONTRIBUTING.md) ·
[**Adding a device**](docs/contributing/DEVICE_CONTRIBUTION.md)

## The three extension levels

Contributors pick the **lowest** level that works. Most contributions are
Level 1 and require no code.

| Level | You write | Runs as | Use when |
|---|---|---|---|
| **1 — Model profile** | `devices/<vendor>/<MODEL>.json` | data, interpreted by core | your appliance speaks a supported protocol and differs only in which field means what |
| **2 — Lua handler** | `plugins/lua/<vendor>_<model>/` | **isolated subprocess**, sandboxed | you need device-specific logic, quirks or conditional decoding |
| **3 — Protocol adapter** | `translator/adapters/<name>.py` | in UALC core | the protocol itself is genuinely new |

**Adding a compatible model should never require changing the universal router
or the Home Assistant interface.** If it does, that is a bug in our
abstraction — tell us.

Specs: [model profile](docs/MODEL_PROFILE_SPEC.md) ·
[plugin manifest & wire contract](docs/PLUGIN_MANIFEST_SPEC.md) ·
[Lua architecture & security](docs/LUA_PLUGIN_ARCHITECTURE.md) ·
[support levels](docs/SUPPORT_LEVELS.md) ·
[review policy](docs/PLUGIN_REVIEW_POLICY.md) · [roadmap](docs/ROADMAP.md)

## Architecture

```
  appliance
     |  local protocol
     v
  router/      (Python)  manufacturer-independent TCP/TLS relay.
     |                   Byte-for-byte; never inspects or terminates TLS.
     |                   Zero device-specific code.
     v
  translator/  (Python)  ===== UALC CORE, TRUSTED =====
     |                   picks an adapter for (manufacturer, protocol_family)
     |
     |   ProfileAdapter        LuaProtocolAdapter        RoborockB01Adapter
     |   (L1, data)            (L2)                      (L3)
     |                              |  NDJSON over stdio
     |              - - - - - - - - | - - - - - - - -  process boundary
     |                              v
     |                   lua subprocess, sandboxed   <-- UNTRUSTED
     |                   ualc_sdk.lua + community handler.lua
     |                              |  validated result
     |      StandardMessage  <------+
     v
  ha_interface.py  ->  MQTT / a Home Assistant integration  ->  Home Assistant
```

The two halves communicate only through the `StandardMessage` envelope in
[`integration_contract.py`](integration_contract.py) — neither imports the
other. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Home Assistant does not run Lua, and nothing here asks it to.** Lua runs in
a separate OS process on the UALC host; UALC core, in Python, validates the
result and builds the `StandardMessage`. Home Assistant sees an ordinary
message and cannot tell which level produced it.

## Security posture for community code

Community Lua handlers are **untrusted executable code** and are treated that
way:

* separate OS process — a hang, crash or memory blow-up cannot take core down;
* sandboxed `_ENV` with no `io`, `os.execute`, `require`, `package`, `load`,
  `debug`; precompiled bytecode refused;
* POSIX rlimits (CPU, address space, open files, no file creation, no fork),
  a per-request wall-clock timeout, and a response-size cap;
* **no credential is ever passed to a plugin** — the contract has no field for
  one, and the host refuses credential-shaped keys;
* a plugin cannot mint a `StandardMessage` or claim a payload was
  authenticated;
* reviewed by a human before merge, `enabled_by_default: false`, and **no
  plugin marketplace or automatic execution of community code** — permanently.

**Lua is not secure because it is a scripting language.** The isolation above
is something we build, and it is defence in depth rather than a boundary that
would hold against a determined attacker. The honest limits — no OS-level
network isolation, rlimits POSIX-only, `RLIMIT_AS` best-effort — are
enumerated in [`docs/LUA_PLUGIN_ARCHITECTURE.md`](docs/LUA_PLUGIN_ARCHITECTURE.md)
§6, and the security tests report them as explicit skips rather than passing
silently. Do not run unreviewed plugins on the machine hosting your production
Home Assistant.

## Honest status, enforced in code

UALC tracks *how far the work got* separately from *who verified it, on what*
— and the validator **rejects** overstated claims at load time, so a wrong
claim fails CI rather than shipping:

* offline tests passing is **not** hardware validation;
* a contributor's hardware test is `COMMUNITY_HARDWARE_TESTED`, never
  `MAINTAINER_HARDWARE_TESTED`;
* a device operating locally on **cloud-issued credentials** is **not**
  `CLOUD_INDEPENDENT`;
* synthetic fixtures are not captures;
* an empty `firmware_ranges` means *unknown*, not *all*.

See [`docs/SUPPORT_LEVELS.md`](docs/SUPPORT_LEVELS.md).

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`router/`, `translator/profiles.py` and `translator/lua_host.py` have **zero**
third-party dependencies. `python-roborock` (`>=7.12.0`, Apache-2.0 — see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)) is needed only for the
Roborock adapter. Lua 5.4+ is needed only to run Lua plugins; without it the
Lua test suites skip cleanly instead of failing.

## Run the tests

```bash
# Framework (pre-existing)
PYTHONPATH=router:. .venv/bin/python router/test_router_offline.py                       # 8
PYTHONPATH=router:. .venv/bin/python router/test_router_hardening.py                     # 13
PYTHONPATH=translator:translator/adapters:. .venv/bin/python translator/test_translator_offline.py    # 15
PYTHONPATH=translator:translator/adapters:. .venv/bin/python translator/test_translator_hardening.py  # 21
PYTHONPATH=testing_infra:.:router:translator .venv/bin/python testing_infra/task4_integration_test.py # 8

# Roborock B01, cloud-free, against a simulator
PYTHONPATH=testing_infra:.:router:translator .venv/bin/python testing_infra/b01_cloudfree_integration_test.py  # 5
PYTHONPATH=testing_infra:.:router:translator .venv/bin/python testing_infra/b01_bridge_test.py                 # 9

# Extension points
PYTHONPATH=translator:testing_infra:. .venv/bin/python testing_infra/profile_validation_test.py  # 32
PYTHONPATH=translator:testing_infra:. .venv/bin/python testing_infra/adapter_contract_test.py    # 86
PYTHONPATH=translator:testing_infra:. .venv/bin/python testing_infra/plugin_security_test.py     # 26
```

**223 checks**, all offline. No manufacturer cloud is contacted; no physical
appliance is involved. Verified on Python 3.11.18 and Lua 5.5.1.

`adapter_contract_test.py` is the one worth understanding: it runs **one** set
of language-neutral cases against **both** a declarative Level-1 profile and a
Level-2 Lua handler for the same device, and requires they agree. That
equivalence is the evidence that the plugin contract is genuinely
language-neutral rather than Python with a Lua afterthought.

## Repository layout

```
router/            Level 0  manufacturer-independent transport
translator/        UALC core: adapters, registry, HA interface, credentials
  profiles.py        Level 1  declarative model profiles
  lua_host.py        Level 2  Lua subprocess host
  adapters/          Level 3  Python protocol adapters
plugins/lua/       Lua SDK + sandbox, and community handlers
devices/           Level 1 model profiles, by manufacturer
  community/         contributions awaiting a manufacturer directory
schemas/           normative JSON Schemas for profiles and manifests
testing_infra/     test brokers, fixtures, contract/security/validation suites
docs/              specs, architecture, roadmap, support matrix
  contributing/      contributor guides and templates
examples/          end-to-end demo with synthetic data
```

## License

UALC's own code is **MIT** — see [`LICENSE`](LICENSE). Contributions are
accepted under MIT (inbound = outbound, no CLA). Third-party dependencies and
their verified licences are in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

**Check the licence of anything you learn from.** Reimplementing a documented
wire format is fine; copying another project's decoder, comments or captured
fixtures is not — particularly from a GPL project, which is incompatible with
MIT. Record where your protocol knowledge came from; see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Related

* [toshiba-tsmartlife-local](https://github.com/jaspweowaale/toshiba-tsmartlife-local)
  — Toshiba/Midea V3 local control, hardware-verified, separate repository.
  UALC does not duplicate it.

## Support Independent Development

This project is independently researched and maintained.

If you find the work useful, you can support continued research, testing,
documentation, hosting, and development through Ko-fi.

**Support:** https://ko-fi.com/jasperwaale

Contributions are voluntary and do not influence technical findings or project
decisions.
