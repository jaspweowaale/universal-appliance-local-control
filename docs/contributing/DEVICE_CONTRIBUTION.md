# Adding support for an appliance we do not own

The complete workflow, from "I have a smart appliance and no local control"
to a merged contribution. Ten steps. Steps 1–7 need **no hardware access
beyond your own appliance** and no permission from us; step 8 is optional.

Read [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md) first for the rules
(privacy, licensing, honesty-about-status).

---

## 1. Identify the appliance exactly

Vague identification is the single most common reason a contribution cannot
be used by anyone else. Record, verbatim:

| Fact | Where to find it |
|---|---|
| Marketing model | the rating plate, usually inside a door or on the back |
| **Full model code** including regional suffix (illustrative shape: `XY60ABCD0.EFGH` — base model plus a regional suffix) | rating plate; the suffix matters |
| **Protocol model identifier** (e.g. `AIR_910604_WW`) | vendor app device info; cloud API; your HA integration's diagnostics |
| Device class | air purifier, fridge, AC … |
| Appliance firmware version | app → device info |
| **Wi-Fi module firmware** (e.g. `clip_hna_v1.9.237_RT`) | app device info; often differs from appliance firmware and matters more |
| Wi-Fi module / chipset if visible | module label, FCC ID lookup, or the firmware string |
| Region / market | affects feature sets and enum domains |
| MAC OUI (first 3 bytes only) | your router. **The first three bytes only — never the full MAC.** |

> Two units with the **same protocol model identifier** have already been
> observed to expose different mode enums in different regions. Record the
> full model code and the region. "Same model id" is not "same protocol".

## 2. Determine the protocol family

Find out whether UALC already understands how your appliance talks — that
decides whether you need Level 1, 2 or 3.

1. Check [`../STATUS_MATRIX.md`](../STATUS_MATRIX.md) for your manufacturer.
2. Observe where the appliance connects: destination ports and hostnames.
   Common shapes:
   * **TLS/MQTT on 8883 outbound to a vendor cloud** — the appliance is a
     client; local control usually needs a substitute endpoint.
   * **A plain TCP port open *on the appliance*** (e.g. Midea V3 on 6444) —
     the appliance is a server; local control may just work.
   * **HTTPS on 443 only** — probably REST plus a push channel.
3. Note whether traffic is appliance-initiated or app-initiated. This decides
   whether local control means "serve it" or "connect to it".
4. Look for existing public reverse-engineering of the family. Note it; do
   **not** copy its code (see §9).

Write what you find into the PR even if you get no further. "This model
speaks Midea V3 on 6444" is a genuinely useful contribution by itself.

## 3. Collect authorised protocol observations

**Only on your own network and your own devices.**

Options, roughly in order of preference:

* **Your router's packet capture**, filtered to the appliance's IP. Filter at
  capture time if you can, so you never hold your household's traffic.
* **A mirror/span port** or a Linux box between the appliance and the network.
* **Your existing integration's debug log** — if HA already talks to the
  appliance over the cloud, its logs may show decoded state, which is
  excellent for building a tag→meaning table.
* **The vendor app, driven deliberately**: change one setting at a time and
  note which frame changed. This is how enum values get established.

Practical method that works well: **change exactly one thing, capture, repeat.**
A capture of "I pressed fan-high" is worth more than an hour of idle traffic.

What you need for a usable fixture:

* the raw frame bytes (hex is fine);
* what the appliance was doing at the time, in words;
* what the vendor app displayed at the time.

If the session is TLS-encrypted and you cannot see inside it, that is still a
finding — record the endpoints, ports, timing and TLS version. Do **not**
attempt to break TLS, and do not ask us how to; see §9.

## 4. Sanitize before you commit anything

Non-negotiable. Remove or replace:

| Remove | Replace with |
|---|---|
| Your IP addresses | RFC 5737: `192.0.2.x`, `198.51.100.x`, `203.0.113.x` |
| Full MAC addresses | keep the OUI (first 3 bytes), zero the rest: `1c:39:29:00:00:01` |
| Device serial numbers, `duid`, appliance IDs | an obviously fake constant, e.g. `000000000000000` |
| Account email / user IDs / home IDs | `user@example.com`, `account-0001` |
| **Tokens, keys, certificates, device secrets, passwords** | **delete the whole field. Do not substitute — delete.** |
| Wi-Fi SSIDs | `EXAMPLE_SSID` |
| Precise timestamps, GPS, timezone-revealing data | round or remove |
| Your home directory paths | `/path/to/...` |

Then check your work:

```bash
grep -nEi '([0-9a-f]{2}:){5}[0-9a-f]{2}|192\.168\.|10\.[0-9]+\.|token|secret|passwd|password|localkey|bearer' your_fixture_file
```

A hit is not automatically a problem — `token` might be a field *name* you
need to document — but you must look at every one. **If you are not sure
whether a value is a secret, delete it and say so in the PR.**

## 5. Write a profile or a handler

### Prefer Level 1 — a model profile

If your appliance speaks a protocol UALC already has a codec for, and the only
difference is which tag means what:

1. Copy [`../../devices/lg/AIR_910604_WW.json`](../../devices/lg/AIR_910604_WW.json).
2. Put yours at `devices/<manufacturer>/<MODEL_ID>.json`.
3. Fill in `model`, `protocol.parameters`, and one `fields` entry per tag you
   can name. Omit tags you are unsure of — they become `unknown_tag_count`,
   which is honest and harmless.
4. Set `support_status` truthfully. With fixtures only, that is
   `DECODED` / `none` / `false`.

Full rules: [`../MODEL_PROFILE_SPEC.md`](../MODEL_PROFILE_SPEC.md).
**No UALC source file changes.**

### Level 2 — a Lua handler

When decoding needs actual logic. See
[`LUA_PLUGIN_GUIDE.md`](LUA_PLUGIN_GUIDE.md) and copy
[`../../plugins/lua/examples/lg_air_910604_ww/`](../../plugins/lua/examples/lg_air_910604_ww/).

### Level 3 — a protocol adapter

A genuinely new protocol. Implement `translator/base.py`'s `ProtocolAdapter`
in `translator/adapters/`, register it, and the existing router and HA
interface work unchanged. Expect a longer review.

## 6. Make reproducible fixtures

Add your frames to `testing_infra/contract_fixtures.py` as `ContractCase`
entries. Each one needs a `rationale` saying what it proves — a fixture
nobody can interpret is dead weight six months later.

**Label synthetic versus captured.** A frame you built with the encoder
proves your decoder is self-consistent. A frame your appliance actually sent
proves something about the appliance. Only the second upgrades your support
level to `CAPTURED`. Both are welcome; do not mix them up.

Include the awkward cases, not just the happy path: a delta frame, an
out-of-domain enum value, a truncated frame, an unknown tag. The reference
cases cover all four and are worth reading as a model.

## 7. Run the offline tests

```bash
PYTHONPATH=translator:testing_infra:. python testing_infra/profile_validation_test.py
PYTHONPATH=translator:testing_infra:. python testing_infra/adapter_contract_test.py
PYTHONPATH=translator:testing_infra:. python testing_infra/plugin_security_test.py
```

Everything in steps 1–7 is achievable **with no physical appliance at all**
once fixtures exist — which is exactly how someone else can improve your
model later, or how you can improve a model you do not own.

## 8. Optional: validate against real hardware, safely

Only you can do this, and it is optional. If you do:

**Before you start**

* Pick a **non-critical appliance**. Do not start with the freezer holding
  your food, or anything running a cycle you care about.
* Know your rollback *before* you change anything, and verify you can
  execute it.
* Expect to lose cloud connectivity for the duration. Decide whether that is
  acceptable.
* Understand that **re-provisioning an appliance to a local endpoint may be
  hard to reverse** on some devices, and may in the worst case require
  re-pairing through the vendor app. Find out which case you are in before
  you commit.

**Do**

* Start **observation-only**: decode what the appliance sends; send nothing.
* Change **one** thing at a time and record what happened.
* Time-box it. Set a deadline at which you roll back regardless of progress.
* Keep a human watching.

**Do not**

* send commands during a first test;
* factory-reset to "clean up";
* run unreviewed plugins on the machine hosting your production Home
  Assistant;
* modify appliance firmware.

Then fill in [`HARDWARE_TEST_REPORT.md`](HARDWARE_TEST_REPORT.md). That report
is what lets a maintainer who has never seen your appliance judge the claim.

## 9. Licensing and legality, explicitly

* **Reimplementing a wire format from a field list is fine.** A protocol is
  not a copyrightable expression.
* **Copying code, comments or captured fixtures is not** — and if the source
  is GPL, it is incompatible with UALC's MIT licence and we cannot merge it.
* If your knowledge came from another project, implement independently,
  record it in `source_provenance` / `notes`, and **say so in the PR**. The
  reference plugin's header shows the standard we expect.
* Reverse-engineering for interoperability is lawful in many jurisdictions
  but not all, and we cannot give you legal advice. You are responsible for
  your own jurisdiction.
* Do not contribute anything obtained by breaking a protection measure, or
  anything under NDA.
* Nothing in UALC attempts to defeat TLS, extract private keys, or modify
  firmware, and contributions that do will be declined.

## 10. Open the pull request

Include:

* [ ] what the appliance is (step 1, in full)
* [ ] protocol family and how you determined it
* [ ] your profile and/or handler
* [ ] fixtures, **labelled synthetic or captured**
* [ ] confirmation you sanitized, and what you removed
* [ ] offline test output, pasted
* [ ] hardware test report, if you did step 8
* [ ] `support_status` you are claiming, and why that level and not a higher one
* [ ] `known_limitations`, populated
* [ ] provenance of your protocol knowledge

### How we review something we cannot test

Be aware of what review can and cannot establish, so the result is not
oversold:

**We can** read the diff for anything outside the declared capability set;
confirm the sandbox and declared permissions; run every offline test; check
fixture/decoder consistency; check the claimed support level against the
evidence; check licensing and sanitization; check that no UALC core file
needed changing.

**We cannot** confirm your appliance behaves as described, that your capture
is representative, or that it works on firmware you did not test.

So a merge means: *the code is safe to ship, the tests pass, and the claim is
consistent with the evidence provided.* It does **not** mean a maintainer
reproduced your hardware result. That is precisely why
`verification_source` exists and why your contribution is recorded as
`community` until someone else with the same appliance independently confirms
it — at which point it becomes `both`.

**Offering to validate somebody else's untested model, because you happen to
own that appliance, is one of the most useful things you can do here.**
