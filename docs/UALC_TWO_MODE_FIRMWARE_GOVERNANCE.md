# UALC firmware governance — two operating modes (design note, not implemented)

## Closeout record, 2026-11-24

The isolation rule for the Toshiba fridge was renamed from its original temporary test name to
**"Toshiba Refrigerator — Owner-Controlled Internet Isolation"** (name field only — action,
enabled state, protocol, source/destination zones, schedule, and index all verified
byte-identical before/after). A DHCP reservation was added pinning the fridge's existing IP to
its MAC address, closing the one real gap found during investigation (the rule previously
depended on a floating, non-reserved lease). Both changes verified live; the device's LAN
telemetry (HA sensors) remained fresh and undisturbed throughout, confirmed immediately after
each change.

**Historical note, closed, not investigated further:** the rule's internal gateway-assigned
identifier recorded when it was originally created (2026-11-02) did not match the identifier
found live during this 2026-11-24 investigation — same rule name at both times, different
internal identifier. No record was found explaining a deletion/recreation in between, and
no accessible audit/activity log on this controller could resolve it (two plausible endpoints
tried, both 404). Recorded here as an unresolved historical fact only; not pursued further per
explicit instruction.

**Status: documentation only.** No code, test, or architecture change accompanies this note.
UALC's dev freeze (set during the 2026-11-24 firmware investigation) stays in effect. This
captures findings from the real Toshiba fridge investigation so a future, separately-approved
session can design against real evidence instead of re-deriving it.

## Mode A — Full internet isolation (verified achievable today, for this device)

What the 2026-11-24 investigation actually confirmed, on real hardware, for the Toshiba
GR-RF900WI-PMV(06)-MG:
- A single gateway-level rule (block all Internal→External traffic from the appliance's IP,
  all protocols) fully isolates the device from the internet while leaving LAN control
  (HA, port 6444) completely unaffected — because the LAN V3 protocol never needs the cloud
  for ongoing operation once paired (confirmed: integration reload re-authenticates locally
  on the cached token/key, zero cloud call).
- This has been running continuously on the real device since 2026-11-02 (22 days as of this
  note), confirmed healthy: sensors remain live and updating, no related errors in HA's log.
- **This is a blunt instrument** — it also stops any legitimate cloud feature (the phone app's
  "online" status, any cloud notification), not just OTA. It is not selective.
- **Gap found in the existing real-world rule**: it matches by IP, and the device's IP is a
  floating DHCP lease (not a reservation) — if the lease ever changes, the rule silently stops
  covering the device. A future implementation of "Mode A" should pair the isolation rule with
  a DHCP reservation (or a MAC-based match, which this gateway's firewall schema supports via a
  `match_mac` field) so the block can't be silently defeated by a lease renewal.
- **Not risk-free for every device, reported 2026-11-24, not independently reproduced by us**:
  the `midea-lan` maintainer reports that some Midea-based smart-home appliances contain a
  cloud-connectivity watchdog — if the device can't reach the manufacturer's cloud within a few
  minutes, its communication module repeatedly disconnects and reconnects while retrying
  ([report](https://github.com/wuwentao/midea-lan/pull/198#issuecomment-7122333488), citing a
  [specific case](https://github.com/wuwentao/midea_ac_lan/issues/1146#issuecomment-6588470606)).
  This is a reported disconnect/reconnect pattern, not independently confirmed by us as a full
  appliance or module reboot in every case — but on an affected device, Mode A could produce this
  unstable, cycling pattern instead of calm local-only operation. This varies by device
  branch/app/region — our own Toshiba fridge shows no such pattern across 3+ weeks of continuous
  isolation — but any future UALC implementation of Mode A must treat "does this device show a
  watchdog signature when isolated" as a per-device check, not an assumption, and must document
  the result either way. See the new "Watchdog and reboot detection" section below, including the
  terminology it uses to avoid overclaiming what a reconnect pattern actually proves.

## Mode B — Selective firmware-update protection (NOT achievable today, for this device)

Confirmed, not assumed, across three separate investigation phases:
- The appliance's own LAN V3 protocol (used for all local control) has no firmware-version
  field and no OTA-related command in its message set — confirmed by reading the actual open
  source library (`midealan`) that implements it.
- The shared, open-source Midea LAN library this device family depends on has **zero**
  OTA/update-management code anywhere in its file tree — if selective update control exists at
  all, it is proprietary code inside the manufacturer's closed app+cloud stack.
- That closed app's real code is provably inaccessible to static analysis (two independent
  methods agree: the pre-install APK contains only 3 trivial loader classes; real logic exists
  only as a runtime-reconstructed artifact inside the app's own private storage while running on
  a real device, never extracted as a file).
- The one candidate cloud endpoint that might expose more (`get_device_info()`,
  `wifiVersion` field) requires a fresh authenticated cloud login — blocked on a missing
  credential (the account password was never stored, by this project's own design) — not
  merely risky, genuinely impossible from this environment today.
- If/when the fridge's own outbound traffic is ever actually captured (blocked this session by
  a missing gateway-shell credential, not attempted again without a new lead per the user's
  instruction), and it turns out OTA shares the exact same TLS session/host as ordinary cloud
  traffic (the working hypothesis, unconfirmed), Mode B would be structurally impossible for
  this device without blocking its entire cloud relationship — collapsing back to Mode A.

**Conclusion for this device, as of this investigation: Mode A is the only mode with a working
method identified so far.** This is a statement about current evidence for one specific device,
not a general claim that selective OTA blocking is impossible — a different device, a future
capture of this device's own traffic, or a documented OTA endpoint distinct from ordinary cloud
traffic could change this. A future UALC implementation of "firmware governance" should default
to offering Mode A (full isolation) as the practical floor for any device where Mode B hasn't
been demonstrated, while keeping Mode B open as a per-device research question rather than
writing it off.

## UALC direction — three priorities (recorded 2026-11-24 closeout, documentation only)

1. **Mode A (full isolation) — proven working baseline.** Demonstrated end-to-end on the real
   Toshiba refrigerator: internet isolation via a gateway rule, LAN control and HA monitoring
   unaffected, verified over multiple weeks of real operation. This is the capability UALC should
   be able to offer for any device where it applies, as the default floor.
2. **Mode B (selective OTA-only blocking) — open research objective, not closed.** No working
   method exists yet for the Toshiba fridge specifically, for the reasons recorded above (no
   OTA-distinct field in the LAN protocol, no OTA code in the shared open-source library, the
   proprietary app's logic not statically extractable, the one promising cloud endpoint blocked
   on a missing credential). This is a per-device open question, to be revisited if any of those
   specific blockers lift (e.g., a future traffic capture, a different device with documented
   OTA endpoints) — not a general architectural dead end for UALC.
3. **Native update-control settings — preferred when available, as a convenience layer on top of
   1 and 2.** Where a device does expose a genuine update-disable switch (unlike this one), UALC
   should prefer using it over network-level isolation, since it's less blunt and doesn't require
   blocking the device's entire cloud relationship. Mode A remains the fallback whenever no such
   switch exists or can't be confirmed reliable.

No new registry code, schema, or tests accompany this note — the UALC development freeze stays in
effect through this closeout. This is a recorded direction for a future, separately-approved
session.

## Watchdog and reboot detection — reusable requirement for UALC (added 2026-11-24, design only)

Full investigation backing this section: `WATCHDOG_BEHAVIOR_INVESTIGATION_20261124.md` (same
folder) — includes the Midea maintainer's own first-party explanation, a measured timing profile
from one specific device, and a reported (unverified by us) DNS-only-block workaround worth
tracking as a possible future Mode B research lead, distinct from full WAN isolation.

Recorded as a direct response to the `midea-lan` maintainer's reported finding above. This is a
requirement UALC's eventual firmware-governance module should satisfy for *any* device under
Mode A isolation, not something specific to the Toshiba fridge — the fridge happens to be the
one device where we've actually verified its absence.

### Terminology — what observation alone can and cannot establish

A recurring disconnect/reconnect pattern is evidence of *something*, but "the device rebooted" is
a stronger claim than most isolation-level observation can actually support. Distinguish:

- **Confirmed appliance reboot** — the main control board itself restarted. Requires evidence
  beyond network behaviour: e.g. a local protocol boot/restart event, an on-device indicator
  (display/relay click), or a telemetry field that visibly resets, not just drops.
- **Confirmed communication module reboot** — the Wi-Fi/network module restarted specifically,
  even if the appliance's main board shows no sign of it. Requires evidence such as the module's
  association/session resetting as if from power-on (fresh handshake, reset internal counters),
  not just a dropped TCP connection.
- **Suspected watchdog-triggered reboot** — a recurring disconnect/reconnect pattern at a short,
  roughly fixed interval, consistent with a cloud-connectivity watchdog, *without* independent
  confirmation of either kind of restart above. This is the default classification for the kind
  of evidence isolation testing actually produces (e.g. the issue #1146 TCP-reset pattern in the
  investigation file) — report it as "suspected," not "confirmed."
- **Ordinary network reconnection** — an infrequent, irregular Wi-Fi/LAN reconnect consistent with
  normal conditions (signal, AP roaming, DHCP renewal). Not evidence of a watchdog.
- **Unknown cause** — a pattern that doesn't clearly fit any category above from the evidence
  available.

**Default rule: classify a recurring reconnect pattern as a *suspected* watchdog signature,
never as a confirmed reboot of any kind, unless you have the specific independent evidence
described above.** This applies to every finding in this document and in
`WATCHDOG_BEHAVIOR_INVESTIGATION_20261124.md` — none of the third-party reports gathered there
include on-device confirmation of an actual restart; all are, at best, "suspected."

1. **Before recommending/applying Mode A for a device, state explicitly that a watchdog signature
   is a known possibility for some devices, and that this has not been checked for the device in
   question** unless it actually has been. Never silently assume a device behaves like the one
   already-verified case.
2. **Verification procedure for "does this device show a watchdog signature when isolated"** (not
   yet run against any device other than the Toshiba fridge, where no signature was observed):
   - Apply the isolation rule, then observe the device continuously for a bounded window (the
     fridge check used ongoing production monitoring over 3+ weeks; a new device should get at
     least enough time to cover one plausible watchdog timeout — "a few minutes" per the report,
     so a 30-60 minute observation window is a reasonable starting floor, not a validated
     constant).
   - Classify what you observe using the terminology above. Most isolation-level observation can
     only support "suspected watchdog-triggered reboot," "ordinary network reconnection," or
     "unknown cause" — don't report "confirmed reboot" without the stronger evidence that
     category requires.
3. **If a suspected or confirmed watchdog signature is detected, do not treat automatic internet
   restoration as the default response.** Restoring internet access re-exposes the device to
   unwanted firmware updates, which is exactly what Mode A exists to prevent. Instead:
   - **Alert the owner** to what was observed, using the terminology above — don't overstate a
     suspected signature as a confirmed reboot.
   - **Explain** the observed pattern and what it does and doesn't establish.
   - **Treat Mode A as potentially unsuitable for that specific device** — not as a general
     failure of the approach.
   - **Recommend a recovery action based on the device's actual operational and safety
     requirements** — a safety- or essential-function-relevant device (e.g. a refrigerator) may
     warrant a faster recommendation to restore access than a non-essential device, but the
     *decision* is still the owner's.
   - **Require explicit owner approval before lifting the isolation.** UALC must never
     auto-restore internet access to "fix" a suspected watchdog signature — it can recommend, and
     can make restoration fast and easy once approved, but the action itself is gated on the
     owner's decision, consistent with this project's standing firmware-control principle: owned
     devices stay under owner control by default, and manual updates require explicit approval.
   - Do not leave essential or safety-relevant equipment in a state believed to be unstable or
     unsafe merely to preserve the isolation — the owner-approval gate is about *who* decides,
     not a reason to withhold a recommendation when one is genuinely needed.
4. **Record a per-device outcome either way** (healthy / suspected-watchdog-signature /
   confirmed-reboot / untested), not just for devices that worked — an untested device should say
   so, not be silently omitted. This is the same "honest-status machinery" principle already
   enforced elsewhere in UALC's support-level/verification-source model for device profiles.

No code/schema/test changes accompany this note — same documentation-only status as the rest of
this file. This is the design basis for a future, separately-approved implementation.

## Owner-approved maintenance mode (concept, not implemented)

For a device under Mode A isolation, a maintenance window would:
1. Record the exact current isolation rule config (already demonstrated this session — read the
   full rule object before touching anything).
2. Temporarily disable (not delete) the isolation rule, with an explicit owner action, not an
   automatic timer.
3. **Explicit warning, stated to the owner at this exact point**: re-enabling internet access may
   permit the manufacturer to push a firmware update during this window — there is no way to
   allow "the app" through while still blocking "an update," because, per Mode B's conclusion
   above, they are not separable on this device's observed architecture.
4. After the maintenance window, restore the original rule config exactly (verified by re-GET,
   not just trusting the toggle) — matching the restoration discipline already demonstrated this
   session for a different setting (the gateway's own SSH toggle).
5. Record what, if anything, actually changed on the device during the window (firmware version,
   if obtainable) as a baseline for the next cycle.

This is a design sketch based on real findings, not a committed feature.
