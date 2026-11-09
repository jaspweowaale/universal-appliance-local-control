# UALC support matrix

Two independent axes, never combined: **support level** (how far the work
got) and **verification source** (who observed it, on what hardware).
Definitions and the rules the validator enforces:
[`SUPPORT_LEVELS.md`](SUPPORT_LEVELS.md).

**Nothing in this repository has been verified on physical hardware by a
maintainer *through UALC itself*.** The one hardware-verified appliance below
was verified through a separate, pre-existing integration, and that
distinction is kept explicit rather than blurred.

Last updated: 08 11 2026.

## Devices

| Device | Manufacturer | Protocol family | Level | Extension level | Verification source | Hardware tested | Evidence |
|---|---|---|---|---|---|---|---|
| Roborock Q10 (`roborock.vacuum.ss09`) | Roborock | B01 (MQTT/DPS) | `SIMULATED` | 3 — Python adapter | `none` | no | `testing_infra/b01_cloudfree_integration_test.py` (5/5), `b01_bridge_test.py` (9/9) — python-roborock's own device simulator over a real local MQTT/TLS broker |
| LG PuriCare 360 (`AIR_910604_WW`) | LG | `thinq2_tlv` | `DECODED` | 1 — profile **and** 2 — Lua handler | `none` | no | `devices/lg/AIR_910604_WW.json`, `plugins/lua/examples/lg_air_910604_ww/`, `adapter_contract_test.py` (86/86). **Fixtures are synthetic, not captured.** |
| Toshiba GR-RF900WI | Toshiba (Midea OEM) | Midea M-Smart V3 | `LOCAL_OPERATIONAL` | not yet a UALC adapter | `maintainer` | **yes** | Verified on hardware via the separate `midea_ac_lan` integration with WAN egress blocked: 19 sensors stayed live, local re-authentication on cached credentials succeeded. **Not implemented in UALC.** Lives at [toshiba-tsmartlife-local](https://github.com/jaspweowaale/toshiba-tsmartlife-local). |

### Why no device is `CLOUD_INDEPENDENT`

The Toshiba fridge is the closest, and it illustrates exactly why the level
is withheld. It **operates** with the manufacturer cloud unreachable —
verified on hardware. But its LAN token and key were **minted by Midea's
cloud** and cannot be derived locally, so a factory-fresh unit could not be
commissioned without the cloud. Operation is cloud-free; commissioning is
not. That is `LOCAL_OPERATIONAL` with a documented credential dependency, and
calling it `CLOUD_INDEPENDENT` would be the exact overstatement
`SUPPORT_LEVELS.md` exists to prevent.

## Framework

| Component | State | Evidence |
|---|---|---|
| Router — manufacturer-independent TCP/TLS relay | implemented, offline-tested | `test_router_offline.py` 8/8, `test_router_hardening.py` 13/13 |
| Translator — adapter registry, HA interface, credential store | implemented, offline-tested | `test_translator_offline.py` 15/15, `test_translator_hardening.py` 21/21 |
| Cross-project integration over real MQTT 3.1.1 + TLS | implemented, offline-tested | `task4_integration_test.py` 8/8 |
| **Level 1 — declarative model profiles** | implemented, offline-tested | `profile_validation_test.py` 32/32 |
| **Level 2 — Lua plugin host + sandbox** | implemented, offline-tested, **experimental, disabled by default** | `plugin_security_test.py` 26/26 (+2 documented non-guarantees) |
| **Language-neutral plugin contract** | implemented, offline-tested | `adapter_contract_test.py` 86/86 incl. Python↔Lua equivalence |
| Level 3 — Python protocol adapters | implemented | `translator/adapters/` |

**Total: 223 checks passing** (79 pre-existing + 144 new), Python 3.11.18,
Lua 5.5.1. Every suite is offline: no manufacturer cloud is contacted and no
physical appliance is involved.

## Protocol codecs available to Level-1 profiles

| Codec | Family | Devices using it | Notes |
|---|---|---|---|
| `lg_thinq2_tlv` | LG ThinQ2 TLV | 1 | 10-bit tag TLV, `0xA7` dialect. The `0x87` dialect is explicitly rejected, not silently mis-decoded. |

A new codec is a **Level 3** contribution. One codec is the honest current
answer and is the main thing limiting Level 1's usefulness — see
[`ROADMAP.md`](ROADMAP.md).

## What is not supported

Stated plainly so the matrix is not read as a capability list:

* **No appliance is controllable through UALC on real hardware today.** Not
  one.
* The Roborock B01 path works against a simulator. Real `ss09` operation is
  blocked on a device-held bootstrap secret that cannot be obtained
  non-invasively, plus unverified TLS trust behaviour.
* The LG purifier work **decodes only**. It cannot send a frame: the outbound
  checksum polynomial is unverified, so `build_outbound` is deliberately
  unimplemented at both Level 1 and Level 2.
* The Toshiba fridge is hardware-verified but **through a different project**.
* No device profile or plugin here has `firmware_ranges` populated — meaning
  firmware compatibility is **unknown**, not universal.

## Contributing a device

Adding a brand or model the maintainers do not own is the intended path, not
an exception. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) and
[`contributing/DEVICE_CONTRIBUTION.md`](contributing/DEVICE_CONTRIBUTION.md).
Validating somebody else's untested model, because you happen to own that
appliance, is equally valuable — it is what moves a row from `none` to
`community`.
