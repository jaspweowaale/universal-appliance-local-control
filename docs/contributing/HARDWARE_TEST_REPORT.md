# Hardware test report — template

Copy this into your pull request (or an issue) and fill it in. This report is
what lets a maintainer who has **never seen your appliance** judge your
claim, so specifics beat reassurance everywhere.

If you did not test on hardware, do not fill this in — just say
`hardware_tested: false` and claim `DECODED` or `SIMULATED`. That is a
perfectly good contribution.

**Before pasting: re-read [`DEVICE_CONTRIBUTION.md`](DEVICE_CONTRIBUTION.md)
§4 and sanitize.** No full MACs, no real IPs, no tokens, keys or device
secrets. Delete secrets rather than substituting them.

---

## 1. Appliance

| Field | Value |
|---|---|
| Marketing model | |
| Full model code (with regional suffix) | |
| Protocol model identifier | |
| Device class | |
| Region / market | |
| Appliance firmware | |
| **Wi-Fi module firmware** | |
| Wi-Fi module / chipset (if known) | |
| MAC OUI (**first 3 bytes only**) | |
| Purchase year (approx.) | |

## 2. Test environment

| Field | Value |
|---|---|
| UALC commit tested | |
| Profile / plugin tested | |
| Host OS and Python version | |
| Lua version (if Level 2) | |
| How the appliance reached UALC | e.g. DNS override / NAT redirect / SoftAP provisioning / appliance is a server |
| Home Assistant involved? | yes / no — and which integration, if any |
| Manufacturer cloud reachable during the test? | yes / no / partly |

## 3. What you did

Numbered steps, enough that someone with the same appliance could repeat
them. Include what you did **not** do.

1.
2.
3.

**Observation window:** _from … to …, total …_

**Did you send any commands to the appliance?** yes / no
If yes, list each one and what happened.

## 4. What you observed

### Decoded state

Paste real decoded output. Sanitized.

```
(paste)
```

### Cross-check against the vendor app or existing integration

The most valuable table in this report: does UALC's decode agree with what
the appliance *actually* shows?

| Field | UALC decoded | Vendor app / HA showed | Agrees? |
|---|---|---|---|
| | | | |
| | | | |

### Anything that did not work

Be specific. A precise failure is more useful than a vague success.

| Symptom | Frequency | What you think caused it |
|---|---|---|
| | | |

### Unknown or out-of-domain values

Did any field decode as `unknown` with a `*_raw` value? Those are findings —
list them. An enum value nobody has documented is new information.

| Field | Raw value | What the appliance/app was doing |
|---|---|---|
| | | |

## 5. Restart and reconnection

Short-lived success is not operational support.

| Check | Result |
|---|---|
| UALC restarted while the appliance stayed up — did it recover? | |
| Appliance power-cycled — did it reconnect? | |
| Appliance left running for an extended period — how long, and did it stay up? | |
| Integration/entity reload — did it re-authenticate successfully? | |

## 6. Cloud dependence — answer all three separately

These are not the same question, and conflating them is the main way a
project overstates cloud independence.

**(a) Operation.** Did the appliance keep working with the manufacturer cloud
**unreachable**?

* How did you block it? (firewall rule, DNS, unplugged WAN, …)
* **How did you confirm the block was effective?**
* For how long?

**(b) Credential origin.** Where did every credential UALC used come from?

| Credential (name only, never the value) | Origin | Could a factory-fresh unit get it without the cloud? |
|---|---|---|
| | | |

**(c) Commissioning.** Could a **brand-new** unit of this model be brought
under local control with no cloud contact at all? If you do not know, say
"unknown" — that is the honest and common answer.

> If (a) is yes but (b) says the credentials were cloud-issued, the correct
> level is `LOCAL_OPERATIONAL` **with a documented credential dependency** —
> not `CLOUD_INDEPENDENT`. See [`../SUPPORT_LEVELS.md`](../SUPPORT_LEVELS.md).

## 7. Risk and reversibility

| Question | Answer |
|---|---|
| Did you re-provision the appliance away from the vendor cloud? | |
| Did you restore normal cloud operation afterwards? How, and did you verify it? | |
| Anything that was irreversible, or needed re-pairing? | |
| Did you change any network configuration? Was it rolled back? | |
| Anything another person should be warned about before repeating this? | |

## 8. The claim you are making

| Field | Value |
|---|---|
| `support_status.level` | |
| `verification_source` | `community` (unless you are a maintainer) |
| `hardware_tested` | `true` |
| `known_limitations` to record | |

**Firmware compatibility:** this result applies to appliance firmware ____
and module firmware ____ **only**. I have not tested other versions.

## 9. Attestations

- [ ] I tested on an appliance I own or am authorised to test.
- [ ] I captured traffic only on my own network.
- [ ] I have sanitized everything pasted above: no full MACs, no real IPs, no
      serial numbers or device IDs, no account identifiers, **no tokens, keys,
      certificates or device secrets**.
- [ ] I have not included any manufacturer account credential, and understand
      UALC will never ask for one.
- [ ] My protocol knowledge is independently implemented, and I have recorded
      its provenance.
- [ ] I am claiming the lowest support level consistent with what I actually
      observed.
- [ ] I understand this will be recorded as **community-verified**, not
      maintainer-verified, until someone else independently reproduces it.
