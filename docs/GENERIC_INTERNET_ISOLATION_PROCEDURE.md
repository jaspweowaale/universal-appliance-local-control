# Router-independent procedure: preventing internet-delivered firmware updates while preserving local control

**Status: project documentation, no code/architecture change.** Router-agnostic write-up of the method actually
proven on a real device (below). Placeholders used throughout instead of real IPs/MACs/credentials,
following the same sanitization convention already used in the UALC public repo (RFC 5737-style
documentation values).

## The 7 steps

1. **Establish local communication with the device**, independent of any cloud account —
   confirm you can read status and send commands to the device over the LAN alone (its own
   local protocol/port), with the manufacturer's cloud entirely out of the loop for that
   exchange.
2. **Confirm the device has no *required* cloud dependency for ongoing operation** — specifically,
   that re-establishing a local session after a restart/reload does not itself require a fresh
   cloud call. This is the step that determines whether isolation is even viable: a device whose
   local client re-authenticates against the cloud on every reconnect cannot be isolated without
   breaking it.
3. **Give the device a persistent, unambiguous identity** on your network — a DHCP reservation
   (or equivalent static binding) tied to its MAC address, not just its current IP. Any rule that
   targets the device by IP address alone will silently stop working if the IP ever changes.
4. **Block the device's traffic to the internet while explicitly preserving LAN traffic** — a
   rule scoped to "this device → Internet/WAN" only, never a rule that also touches
   device-to-LAN communication (e.g., to your home automation system). Prefer a single rule type
   that cleanly separates "Internet" as a distinct target from ordinary intra-network traffic, if
   your router/firewall offers one.
5. **Verify there is no alternate path around the block**: check for a second, overlapping global
   IPv6 address the rule doesn't cover (a device with only a link-local v6 address has no v6
   internet path to begin with, so nothing extra is needed there); check for VPN clients, static
   routes, or port-forwards that might create a bypass; and don't assume an inbound-only concern —
   also check that nothing allows unsolicited traffic *to* the device from the internet (most
   routers already default-deny this for every device, so this is usually "confirm existing
   default," not a new rule).
6. **Verify normal device functionality continues** — confirm live telemetry/status keeps
   updating (not frozen/cached), confirm you can still send local commands, and specifically
   confirm that restarting or reloading your local integration re-establishes the session purely
   locally (reusing a previously-stored credential/token), without silently falling back to a
   cloud call you didn't notice. **Also check for a watchdog signature**: some devices contain a
   cloud-connectivity watchdog whose communication module repeatedly disconnects and reconnects if
   it cannot reach the manufacturer's cloud within a few minutes — reported for some Midea-based
   appliances
   ([report](https://github.com/wuwentao/midea-lan/pull/198#issuecomment-7122333488), citing a
   [specific case](https://github.com/wuwentao/midea_ac_lan/issues/1146#issuecomment-6588470606)),
   not confirmed on the device this procedure was verified against (see below). A recurring
   disconnect/reconnect pattern at a short, roughly fixed interval, with no external cause, is a
   *suspected* watchdog-triggered reboot, not a confirmed one, unless you have independent
   evidence the appliance or its module actually restarted (a local protocol restart/boot message,
   a reset uptime counter) — see `UALC_TWO_MODE_FIRMWARE_GOVERNANCE.md`'s terminology for the full
   distinction. Don't confuse this with an ordinary, irregular Wi-Fi reconnect, which is not
   evidence of a watchdog. If you observe a recurring pattern: do not automatically restore
   internet access as the default fix — that re-exposes the device to firmware updates. Instead,
   note what you observed, assess whether the device's actual function (and any safety-relevant
   function) is being disrupted, and make a deliberate decision about whether continued isolation
   is appropriate for that device, restoring access only if you decide it's needed and accepting
   the update-exposure risk that comes with doing so.
7. **Retain the isolation indefinitely, unless the owner explicitly authorizes a change** — don't
   build in a timer, schedule, or automatic re-opening. Any temporary lifting of the block should
   be a deliberate, logged, owner-initiated action (see the explicit warning below), not a
   background process.

## What this does and does not prevent

- **Prevents:** any firmware update delivered to the device over its own internet connection —
  the device simply cannot reach the manufacturer's servers to check for, request, or download
  one.
- **Does not necessarily prevent:**
  - **Locally-delivered firmware** — a technician's service tool connected directly to the
    device, a USB/local-maintenance interface, or any other non-internet delivery mechanism, if
    the device has one. This procedure has no visibility into that path at all.
  - **Firmware already downloaded before isolation was applied** — if an update was already
    staged on the device before you blocked it, isolation does not undo that; it only stops
    *future* downloads.
  - **Any period where internet access is temporarily restored** — see below.

## Explicit warning: temporarily reopening access

If you ever temporarily lift this isolation for any reason (to use a cloud-dependent feature, to
intentionally allow an update you've reviewed and approved, to test something), be aware that
**the moment the device can reach the internet again, it may also be able to receive an automatic
firmware update you did not separately request** — most consumer IoT devices do not expose a way
to allow "ordinary app connectivity" while still blocking "the update channel" specifically,
because the two commonly travel over the same connection. Treat any reopening as a maintenance
window with that risk accepted, not as a safe partial exception.

## Verified real-world example — Toshiba refrigerator (LAN V3 / Midea-based control)

This exact procedure was implemented and verified on a real Toshiba refrigerator using LAN V3
local control (Home Assistant's `midea_ac_lan` integration) and a UniFi gateway as the
enforcement point, as one concrete implementation of step 4 (a zone-based firewall policy
blocking Internal→External traffic from the device's reserved IP, all protocols, always-on
schedule):

- Step 2 confirmed structurally: the device's local protocol re-authenticates on a cached
  token/key with no cloud call on reconnect.
- Step 3 implemented: DHCP reservation added for the device's MAC, pinning its existing IP.
- Step 4 implemented and has been continuously active for over three weeks at time of writing.
- Step 5 confirmed: the device has no global IPv6 address (link-local only), no VPN/routing
  bypass exists, and the gateway's default posture already blocks unsolicited inbound traffic to
  every device including this one.
- Step 6 confirmed with live evidence: the device's temperature and door sensors have continued
  updating normally throughout (thousands of recorded state changes, a small number of brief
  connectivity blips consistent with ordinary WiFi behavior, no sustained outage), and a local
  integration reload re-authenticated purely locally with zero cloud contact.
- Step 7: the isolation rule remains active, renamed from its original "TEMP" test name to reflect
  its permanent, intentional status, with no scheduled expiry.

**Not yet available for this device:** selective firmware-update blocking that would allow
ordinary cloud/app connectivity to keep working while specifically preventing updates — see
`UALC_TWO_MODE_FIRMWARE_GOVERNANCE.md` for why, and why that's recorded as an open research
question rather than a closed "impossible."

**Step 6's watchdog-signature check, for this device specifically**: no recurring
disconnect/reconnect pattern observed. Across 3+ weeks of continuous isolation, the device's
session and Wi-Fi association showed only occasional, irregular reconnects consistent with
ordinary network behaviour — not a watchdog signature — and no independent evidence of any
restart event, appliance- or module-level. This result does not transfer to other devices — see
`UALC_TWO_MODE_FIRMWARE_GOVERNANCE.md`'s "Watchdog and reboot detection" section for the
reusable, per-device check this procedure now requires at step 6.
