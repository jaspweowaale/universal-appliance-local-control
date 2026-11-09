# UALC roadmap

Priorities are ordered by **what unblocks contributors**, not by what is most
interesting to build. UALC's bottleneck has never been code — it is hardware
access, and the only scalable fix is making other people's appliances
contributable.

Status vocabulary: [`SUPPORT_LEVELS.md`](SUPPORT_LEVELS.md).

## Done

| | Evidence |
|---|---|
| Manufacturer-independent TCP/TLS router, zero device-specific code | `router/`, 21 checks |
| Adapter-based translator with a stable `StandardMessage` envelope | `translator/`, `integration_contract.py`, 36 checks |
| Roborock B01 command path, cloud-free, over real local MQTT/TLS | `testing_infra/b01_*`, 14 checks — **simulator only, never a real ss09** |
| **Level 1: declarative model profiles** | `translator/profiles.py`, 32 checks |
| **Level 2: Lua plugin host + sandbox** | `translator/lua_host.py`, `plugins/lua/ualc_sdk.lua`, 26 security checks |
| **Language-neutral plugin contract, proven by equivalence test** | `testing_infra/adapter_contract_test.py`, 86 checks |
| Contribution infrastructure: specs, guides, templates, review policy | `CONTRIBUTING.md`, `docs/contributing/` |

## Next — contributor-facing (no hardware needed)

1. **A second codec, so Level 1 serves more than one family.** Right now
   `lg_thinq2_tlv` is the only profile codec, which means Level 1 only helps
   LG ThinQ2 contributors. A Midea V3 codec is the obvious second (see
   below), followed by a generic length-prefixed-record codec covering the
   AABB-style framing common to several appliance families.
2. **Make the repository installable as a package.** The current flat layout
   needs `PYTHONPATH=translator:testing_infra:.` to import anything, which is
   a real papercut for a contributor and a trap in CI. A `pyproject.toml`
   with a proper package layout — without moving files unnecessarily — is
   high value and low risk.
3. **Extend `StandardCommand` beyond vacuum vocabulary.** It is currently
   `GET_STATUS / START / PAUSE / DOCK / GET_MAP`, which fits a robot vacuum
   and nothing else. Air purifiers, ACs and fridges need set-point and
   mode-selection commands. Additive, backward-compatible, and blocking any
   write-capable non-vacuum contribution.
4. **A contributor scaffold** — `python tools/new_profile.py <vendor> <model>`
   producing a skeleton profile, a fixture stub and a test case.
5. **CI matrix across Lua 5.4 and 5.5**, so a handler is not accidentally
   tied to one minor version.

## Next — hardware-gated (needs someone who owns the appliance)

These are stated as open questions rather than planned work, because we
cannot schedule hardware we do not have.

| Family | What is needed | Who could do it |
|---|---|---|
| Roborock B01 / ss09 | real-device validation of the cloud-free command path; the device-held bootstrap secret problem | anyone with a Q10 willing to test |
| LG ThinQ2 purifier | a real sanitized capture to replace the synthetic fixtures; whether `0x1f9` reports the full enum on a non-Korean SKU | any PuriCare 360 owner |
| Toshiba / Midea V3 | long-horizon credential-revocation behaviour under a cloud block | already hardware-verified for operation; needs time, not access |

## Candidate manufacturer expansion

Ranked by **protocol reuse × documentation availability × contributor
accessibility × verifiability**, which is deliberately not the same as "most
popular brand".

| Candidate | Reuse | Docs | Contributors | Verifiable | Notes |
|---|---|---|---|---|---|
| **Midea V3 family** (Toshiba, Midea, Comfee, Pioneer, some Electrolux/Carrier OEM) | **high** | high | **very high** | high | Best first expansion by a distance. One protocol, dozens of rebadged appliances, an appliance-as-server model that needs no redirect, and this project already has hardware-verified local control of one. A `midea_v3` codec would make Level 1 immediately useful to a large group. |
| **LG ThinQ2 TLV** (purifiers, ACs, dehumidifiers, washers) | high | medium | high | medium | One codec already exists. The `0x87` AC dialect is adjacent to the `0xA7` dialect already implemented. Caveat: regional SKU variation behind a shared model id is a demonstrated hazard here. |
| **Tuya / local-key devices** | medium | high | very high | high | Enormous device population and a well-documented local protocol. Different in kind: per-device local keys are cloud-issued, so it would mostly land at `LOCAL_OPERATIONAL`, not `CLOUD_INDEPENDENT`. Worth doing with that framing stated up front. |
| **ESPHome-adjacent / already-local devices** | n/a | n/a | n/a | n/a | **Deliberately out of scope.** These are already local; UALC adds nothing. |
| **Roborock B01** | low | medium | low | **low** | Already implemented, but blocked on a device-held secret and unverifiable without physical access. Not a growth area. |
| **Dyson, Samsung, Bosch/Siemens Home Connect** | unknown | varies | medium | unknown | Plausible, entirely unresearched here. Would be Level 3 work. Listed as candidates, **not** as planned support. |

### What we will not do

**We will not claim support for a brand because its devices use a similar
chip or the same cloud platform.** A shared Wi-Fi module, a shared OEM or a
shared MQTT broker is not evidence of a shared local protocol — this project
has already been burned by assuming a shared *model identifier* implied a
shared protocol. Every manufacturer entry in the status matrix has to be
earned by a decoded frame, and every hardware claim by a hardware report.

## Versions

| Version | Contents | Gate |
|---|---|---|
| `0.1.0-alpha` | current framework + Roborock B01 offline + Lua/profile extension points | no real-hardware device support of any kind yet |
| `0.2.0-alpha` | second profile codec, installable package, extended `StandardCommand` | contributor ergonomics |
| `0.3.0` | first `COMMUNITY_HARDWARE_TESTED` device from a contributor | needs one real contributor with real hardware |
| `1.0.0` | at least one `LOCAL_OPERATIONAL` device verified by someone other than its author, and a stable plugin API | independent reproduction |

**`1.0.0` is deliberately gated on independent reproduction, not on feature
count.** A framework that claims to control appliances should be able to
point at one somebody else confirmed.
