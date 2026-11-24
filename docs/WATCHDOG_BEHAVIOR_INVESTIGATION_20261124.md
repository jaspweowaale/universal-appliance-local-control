# Cloud-connectivity watchdog behaviour — investigation (2026-11-24, documentation only)

**Status: research complete, documentation only. No code, test, or device change.** This
satisfies the "investigate cloud-connectivity watchdog behaviour" outstanding item. All sources
below are public GitHub threads, fetched and read directly (not inferred), on the same
open-source Midea LAN ecosystem our own Toshiba integration builds on.

## What was actually confirmed, by source

1. **Maintainer's own explanation (GitHub, `wuwentao/midea_ac_lan` issue #463, maintainer
   @wuwentao)**: "Midea Device/hardware module still required internet access, as it will
   notice all the local LAN message to cloud server... it's mandatory from midea side." And:
   "it's midea software and hardware design, we can do nothing for it." This is the clearest
   first-party statement available: the Wi-Fi module is designed to report local LAN activity to
   Midea's cloud regardless of whether a local controller (like Home Assistant) is also talking
   to it — cloud connectivity is not merely a convenience feature, it is built into the module's
   normal operating loop.
2. **Project's own README (`wuwentao/midea_ac_lan`)**, quoted verbatim: "the appliance's built-in
   Wi-Fi module is designed to maintain a connection to Midea Cloud after joining a Wi-Fi
   network. If Internet access is blocked, the module will repeatedly restart and probe for
   connectivity until it can reach Midea Cloud." This documents the restart-and-probe behaviour
   as an acknowledged, expected characteristic of the hardware/firmware — not a bug report, a
   design statement.
3. **Detailed technical report (issue #1146, comment 6588470606)**: one specific AC (model
   `00000Q1B`, subtype 44204, protocol v3) on an isolated IoT VLAN showed periodic TCP resets
   roughly every 3 minutes 10 seconds, each followed by ~25 seconds of unavailability during
   reconnection/re-probing, with "Connection reset by peer" visible in local LAN traffic even
   though the device stayed Wi-Fi associated throughout. Restoring cloud reachability eliminated
   the pattern entirely. This is the closest thing to a measured timing profile found — useful as
   a reference interval (not a guaranteed constant across models).
4. **Independent corroborating reports (issue #463, multiple users)**: blocking internet access
   reliably causes Midea AC units to go unavailable in Home Assistant after a variable delay
   (one report: ~24 hours before onset; others sooner), with repeated Wi-Fi disconnect/reconnect
   cycles while remaining pingable — consistent with a reboot/retry loop rather than a clean,
   stable "offline" state.
5. **Reported partial workaround, not verified by us, not universal**: one user (@losuler) in the
   same thread reported that blocking only DNS resolution to the device (rather than blocking all
   outbound internet traffic) avoided the "zombie state," on the theory that the module's cloud
   check depends on successfully resolving a hostname, and failing DNS resolution is handled
   differently by the firmware than a reachable-but-blocked connection. **This is a single
   third-party report, not something we have tested, and it directly concerns a different
   device family (Midea AC) than our own Toshiba fridge.** Worth tracking as a possible future
   research avenue for Mode B (selective blocking), not something to recommend as-is.
6. **A separate, structurally different symptom exists in the same ecosystem (issue #307)**: some
   devices keep the TCP/auth session alive while offline-from-the-controller's-perspective
   because the control board itself is asleep, not because of a cloud watchdog. Noted here only
   to avoid conflating two different "looks offline" failure modes in any future UALC
   diagnostic — they need different handling.

## Classification, applying the terminology in `UALC_TWO_MODE_FIRMWARE_GOVERNANCE.md`

None of the sources above include on-device confirmation of an actual restart (no boot log, no
reset uptime counter, no physical observation). Applying that document's terminology:

- **Items 1-2** (maintainer's and README's own statements that "the module" restarts/probes) are
  first-party source statements about the component involved, not instrumented evidence we
  gathered ourselves — we report them as the source's own characterization, not as something we
  independently confirmed as a "confirmed communication module reboot."
- **Item 3** (issue #1146's ~3m10s TCP-reset pattern) is, by the terminology, a **suspected
  watchdog-triggered reboot**: a recurring, short-interval pattern, with no independent
  confirmation of which component (appliance board vs. communication module) actually restarted.
- **Item 4** (issue #463's multi-user reports of disconnect/reconnect cycling) is likewise
  **suspected watchdog-triggered reboot**, not confirmed, for the same reason.
- **Item 6** (issue #307's sleeping-control-board symptom) is explicitly **not** a watchdog
  signature at all — it's a different failure mode (reachable at the transport layer, silent at
  the application layer) and is recorded here only so it isn't mistaken for one.

## What remains genuinely unknown

- **Whether our own Toshiba fridge's specific firmware/module shares this exact watchdog
  behaviour.** It has not shown it in 3+ weeks of continuous isolation, but the AC reports above
  show the onset delay varies by device/model (minutes to ~24 hours) — our test duration makes a
  reboot loop unlikely for this unit, but does not mechanically rule out every possible timing.
- **Whether the DNS-only-block workaround generalizes** beyond the one AC report that mentioned
  it, or applies to Toshiba-branded/refrigerator-family devices at all.
- **The exact mechanism** ("notice all the local LAN message to cloud server") is stated by the
  maintainer in general terms, not documented at the protocol level — we have not found (and did
  not look for, this being a documentation task) a packet-level confirmation of what specifically
  gets sent to the cloud from a LAN-only session.

## Relationship to existing UALC documents

This investigation is the evidentiary basis for the new "Watchdog and reboot detection" section
added to `UALC_TWO_MODE_FIRMWARE_GOVERNANCE.md` and the step-6 update to
`GENERIC_INTERNET_ISOLATION_PROCEDURE.md` (both edited 2026-11-24, same session). Read those for
the resulting reusable requirement; this file is the research record it was built from.

Related: `UALC_TWO_MODE_FIRMWARE_GOVERNANCE.md`, `GENERIC_INTERNET_ISOLATION_PROCEDURE.md`.
