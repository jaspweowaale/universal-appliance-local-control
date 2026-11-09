---
name: Device support request / offer
about: Propose support for an appliance, or offer to help with one
title: "[device] <manufacturer> <model> — <device class>"
labels: device-support
---

<!--
Please read docs/contributing/DEVICE_CONTRIBUTION.md first — steps 1 and 2 are
most of what this form asks for.

NEVER post credentials, tokens, device secrets, local keys, full MAC
addresses, serial numbers, account identifiers or unsanitized captures.
We will never ask for your manufacturer account credentials.
-->

## What I am offering

- [ ] I own this appliance and can **test** on it
- [ ] I own it and can **capture** its traffic
- [ ] I can write a profile / handler but **cannot** test on hardware
- [ ] I am **requesting** support and cannot test
- [ ] I can **validate someone else's untested work** on my appliance ← very welcome

<!-- Be honest here; it is the single most useful field in this form. UALC
     cannot buy appliances, so "I own it and can test" changes what is
     possible. "I'm requesting support" is also a fine answer. -->

## Appliance

| Field | Value |
|---|---|
| Marketing model | |
| Full model code (with regional suffix) | |
| Protocol model identifier (from the vendor app / cloud / HA diagnostics) | |
| Device class | |
| Region / market | |
| Appliance firmware | |
| **Wi-Fi module firmware** | |
| MAC OUI (**first 3 bytes only**) | |
| Approx. purchase year | |

## How it currently works

| Question | Answer |
|---|---|
| Does it work in Home Assistant today? Which integration? | |
| Is that integration cloud-based or local? | |
| What does the appliance connect to — hostnames and ports, if you know? | |
| Does the appliance listen on any port itself? | |
| Does any public reverse-engineering of this family exist? (link) | |

## Protocol family

If you have an idea, say so and how you concluded it. "No idea" is fine.

## What you most want to be able to do locally

<!-- e.g. "read temperature", "turn it off", "stop it phoning home". Helps
     prioritise, and sometimes reading is much easier than controlling. -->

## Anything else

<!-- Partial findings, odd behaviour, things you already tried and that
     failed. Negative results are genuinely useful here. -->

---

<!--
What happens next, so expectations are clear:

* If UALC already has a codec for this protocol family, a Level-1 JSON profile
  may be all it takes — and you may be able to write it yourself with no code.
* If not, it needs a Lua handler (Level 2) or a Python adapter (Level 3).
* Maintainers CANNOT verify your appliance. Anything you contribute will be
  recorded as community-verified, and that is normal and fine.
* A request with nobody who owns the appliance may stay open a long time.
  That is not neglect — it is the hardware-access constraint this project is
  built around.
-->
