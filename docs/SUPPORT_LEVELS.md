# UALC device support levels

Two independent axes. Conflating them is the most common way an open-source
device project ends up overstating what it does, so UALC keeps them apart and
**enforces the separation in code** (`translator/profiles.py`,
`validate_profile`), not just in review.

* **Support level** — how far the work has got.
* **Verification source** — *who* observed it, on *what*.

A high support level with `verification_source: community` is not a maintainer
claim. A passing offline test suite is not a hardware claim. A device running
locally on cloud-issued credentials is not cloud-independent.

## Support levels

In increasing order. Each level assumes the ones before it.

| Level | Means | Minimum evidence |
|---|---|---|
| `RESEARCH` | We know the appliance exists and have some idea of its protocol family. | A written note identifying model, firmware and suspected protocol. |
| `CAPTURED` | Real protocol traffic has been observed and sanitized. | A sanitized capture or frame log committed as a fixture, with how it was obtained. |
| `DECODED` | Frames can be parsed into named fields. | A profile or handler plus offline tests over fixtures. |
| `SIMULATED` | A full request/response cycle works against a simulator or local broker, not a device. | A passing integration test with no appliance in the loop. |
| `COMMUNITY_HARDWARE_TESTED` | A contributor ran it against their own physical appliance and reported results. | A completed hardware test report (see template) referenced from the PR. |
| `MAINTAINER_HARDWARE_TESTED` | A maintainer ran it against an appliance they have. | Same report, produced by a maintainer. |
| `LOCAL_OPERATIONAL` | The appliance is genuinely usable locally — read **and**, where applicable, control — over a sustained period. | Hardware report covering a stated observation window, including a restart/reconnect. |
| `CLOUD_INDEPENDENT` | Operates with the manufacturer cloud **unreachable**, and does not depend on credentials the cloud must mint. | Hardware report with cloud egress actually blocked, **plus** an explicit statement of where every credential came from. |

## Verification source

| Value | Means |
|---|---|
| `none` | Nobody has run this against hardware. Desk work, fixtures, simulators. |
| `community` | A contributor reported hardware results. Not independently reproduced by a maintainer. |
| `maintainer` | A maintainer observed it on hardware they control. |
| `both` | Independently observed by a contributor **and** a maintainer. |

## Rules the validator enforces

A profile is rejected at load time, so CI fails rather than a wrong claim
shipping:

1. Any level from `COMMUNITY_HARDWARE_TESTED` upward requires
   `hardware_tested: true`.
2. `MAINTAINER_HARDWARE_TESTED` requires `verification_source` of
   `maintainer` or `both`.
3. `COMMUNITY_HARDWARE_TESTED` requires `verification_source` of `community`
   or `both`.
4. `hardware_tested: true` is incompatible with `verification_source: none`.
5. Levels and sources outside these lists are rejected — no invented values.

Covered by `testing_infra/profile_validation_test.py`, group 4.

## The cloud-independence trap

`CLOUD_INDEPENDENT` is the easiest level to claim wrongly, and UALC has
already hit the distinction in practice, so it gets its own rules.

Three separable questions:

1. **Operation** — does it work while the cloud is unreachable?
2. **Credential origin** — were the credentials it uses *minted* by the
   cloud?
3. **Commissioning** — could a *new* appliance be brought up with no cloud
   contact at all?

A device can pass (1) and fail (2) and (3). That is **not**
`CLOUD_INDEPENDENT`; it is `LOCAL_OPERATIONAL` with a documented credential
dependency. A worked example from this project's own history: the Toshiba /
Midea V3 refrigerator keeps working with its WAN egress blocked — verified on
hardware — but the LAN token and key were issued by Midea's cloud and cannot
be derived locally. Operation is cloud-free; commissioning is not. The status
matrix must say both.

If you are reaching for `CLOUD_INDEPENDENT`, state in the hardware report:

* what you blocked, how, and how you confirmed the block;
* how long you observed;
* **where each credential came from**, and whether a factory-fresh unit could
  obtain one without the cloud;
* whether a restart/re-authentication was exercised while blocked.

## What must always be visible

Every profile and plugin manifest carries `known_limitations`. Use it. State:

* operations not implemented and why;
* whether fixtures are **synthetic** or **captured from a device**;
* checks deliberately skipped (e.g. an unvalidated checksum);
* firmware or regional variants the work does **not** claim.

A shared model identifier is not evidence of a shared protocol. Neither is a
shared Wi-Fi chipset or a shared cloud platform. Claim the models you tested.
