# Ariston VELIS Lydos — local-control research (BLE provisioning)

Honest status of this project's Ariston work. **`RESEARCH` level — architecture mapped from
the vendor app, nothing captured from real traffic, nothing simulated, nothing hardware-tested.**
Read [`SUPPORT_LEVELS.md`](SUPPORT_LEVELS.md) before assuming any of this is usable.

## Device
- Family: Ariston VELIS Lydos electric water heater, Wi-Fi gateway module (ESP32-class MCU).
- Paired via the official Android app, `com.remotethermo.aristonnet` ("Ariston Net").
- Cloud transport (separately confirmed by live packet capture, not part of this doc's scope):
  the gateway is an **outbound-only MQTTS client** to Ariston's cloud broker, with **TLS
  certificate pinning in the device firmware** — it runs no accepted local listener on any of
  the commonly-checked ports. The firmware itself could not be obtained in cleartext (a sibling
  model's dump was flash-encrypted at the hardware fuse level); that path is a dead end
  independent of anything below.

## What app static analysis found — a separate, previously-unknown local channel
The vendor app embeds a real Bluetooth LE GATT protocol used during device setup, independent
of the cloud MQTT path above. Found by decompiling the official app (JADX, no vendor source
copied into this repo — only the protocol *shape* is documented here, in our own words).

**Command set** (Protobuf-encoded over BLE characteristics): sending Wi-Fi credentials to the
device (`PutCredentials`: SSID/password/DHCP-or-static-IP, plaintext fields at this layer),
asking the device to scan nearby networks (`GetNetworks`), reading device/menu topology
(`GetTopology`, `GetDataFunctions`, `GetMenuVisibility`), reading/clearing error state
(`GetErrorState`, `ExecuteDeviceErrorReset`), and a couple of narrower commands
(`PutCredentialsEth`, `BleOff`).

**Access gate — a real challenge-response, not just BLE bonding:** the device issues a random
challenge over a GATT characteristic; the app must answer with
`HMAC(key = deviceSecret, msg = appSecret + challenge)` (truncated 20 bytes) before any command
is accepted, then derives a session key the same way (truncated 16 bytes) for the rest of the
session.

**Open question, not resolved by static analysis alone:** where `deviceSecret`/`appSecret`
actually originate. Ruled out: no bespoke native crypto library ships in the app (only generic
libs — a DB engine, graphics, a root-check stub); the secret container is never constructed
anywhere in the ~36,700 decompiled classes with a traceable literal value; there is no QR/barcode
scan step in the pairing wizard. The wizard **does** collect the gateway's serial number and
**does** make an authenticated cloud call (`GwRegistrationProxyAdapter.register()`, requiring
Ariston account sign-in) before BLE pairing proceeds — but that call's return value is a bare
integer status, not an obviously-returned secret blob. Whether the secret is cloud-issued
per-device (closing this off the same way Roborock's Q10 bootstrap secret did) or derivable
locally from the serial number was not determined this pass.

## Four maturity levels (do not conflate — see `SUPPORT_LEVELS.md`)
| Level | Status |
|---|---|
| Protocol identified | **Partial** — command set and auth handshake architecture mapped from app decompile; no byte-level frame layout confirmed (no real capture exists) |
| Offline / simulator tested | No |
| Actual hardware verified | No |
| Cloud-independent operation | Unknown — gated entirely on the open secret-origin question above |

## Why this is worth keeping even though nothing works yet
This is a genuinely different channel from the cloud-MQTT path (which is firmware-TLS-pinned
and a hard dead end) and the physical UART path (which needs opening the casing and has an
unresolved electrical-isolation question). If the per-device secret turns out to be capturable
once — the same shape as the Toshiba fridge fix in this repo's history — the read-only commands
above (`GetTopology`, `GetDataFunctions`, `GetErrorState`) would then work entirely over BLE,
no network involved, for as long as that captured secret stays valid.

## Explicitly not done
- No BLE connection has ever been attempted against a real device.
- No secret has been captured or guessed.
- No vendor app source was copied into this or any repo — this document describes protocol
  *shape* (command names, auth architecture) in original wording, which is standard
  interoperability documentation, not a license-encumbered copy.

## Next step if continued
Trace the Koin dependency-injection bindings for `Secret`/`RemSecret` (not found via plain
text search) to find the literal construction site, or instrument the real app with Frida to
observe the value live during a real pairing session — the latter requires a live device/account
test and separate approval.
