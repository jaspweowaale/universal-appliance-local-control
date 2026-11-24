"""Offline validation of firmware_registry.py using synthetic + real,
already-gathered facts only (the Toshiba case study below cites this
project's own docs/status matrix, a prior PCAPdroid capture's hostnames, and
one single passive LAN discovery broadcast replay against the real fridge --
no credential, token, or private-network IP is included). This TEST FILE
itself makes zero network calls and contacts zero device -- it only asserts
against values recorded as constants above, matching every other
*_offline.py suite in this repo. The one live observation that produced the
"5.37.4" candidate value happened separately, during the 2026-11-24
investigation, documented in the comment below and in that session's report.
"""
import sys

from firmware_registry import (
    EndpointClassification,
    FirmwareBaseline,
    FirmwareRegistry,
    OtaEndpoint,
    ProtectionLevel,
)

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # --- Basic baseline + version-change detection ---
    reg = FirmwareRegistry(device_id="synthetic-001")
    check("fresh registry: no baseline yet", reg.latest_baseline is None)

    b1 = FirmwareBaseline(
        manufacturer="acme",
        model_id="WIDGET-1",
        device_id="synthetic-001",
        firmware_version="1.2.3",
        source="lan_discovery_v3",
    )
    reg.record_baseline(b1)
    check("baseline recorded", reg.latest_baseline is b1)
    check("no version change: same version observed", not reg.check_version_change("1.2.3"))
    check("version change detected", reg.check_version_change("1.2.4"))
    check("unknown observed version is never a 'change'", not reg.check_version_change(None))

    # --- device_id mismatch must fail closed, not silently accept ---
    mismatched = FirmwareBaseline(
        manufacturer="acme", model_id="WIDGET-1", device_id="other-device", firmware_version="9.9.9"
    )
    try:
        reg.record_baseline(mismatched)
        check("mismatched device_id baseline rejected", False)
    except ValueError:
        check("mismatched device_id baseline rejected", True)

    # --- endpoint classification ---
    reg.register_ota_endpoint(
        OtaEndpoint(
            host="ota.example.com",
            classification=EndpointClassification.CONFIRMED_OTA,
            evidence="synthetic fixture",
        )
    )
    check("known OTA host classified", reg.classify_traffic("ota.example.com") == EndpointClassification.CONFIRMED_OTA)
    check("unknown host classified UNKNOWN, not guessed", reg.classify_traffic("random.example.com") == EndpointClassification.UNKNOWN)

    # --- owner-approval bookkeeping never installs anything, just records intent ---
    check("no approval recorded yet", reg.protection_status(None, None, False)["owner_approved_update"] is None)
    reg.approve_update("1.2.4")
    check("approval recorded verbatim", reg.protection_status(None, None, False)["owner_approved_update"] == "1.2.4")

    # --- protection_status: all 4 real combinations, never guesses ---
    check(
        "native switch found + disabled -> NATIVE_SWITCH_DISABLED",
        reg.protection_status(True, "disabled", False)["protection_level"] == ProtectionLevel.NATIVE_SWITCH_DISABLED.value,
    )
    check(
        "native switch found + not set -> NATIVE_SWITCH_AVAILABLE_NOT_SET",
        reg.protection_status(True, "enabled", False)["protection_level"]
        == ProtectionLevel.NATIVE_SWITCH_AVAILABLE_NOT_SET.value,
    )
    check(
        "no native switch + network mitigation -> NETWORK_MITIGATION_ACTIVE",
        reg.protection_status(False, None, True)["protection_level"] == ProtectionLevel.NETWORK_MITIGATION_ACTIVE.value,
    )
    check(
        "no native switch + no mitigation -> NO_MITIGATION (honest exposed state)",
        reg.protection_status(False, None, False)["protection_level"] == ProtectionLevel.NO_MITIGATION.value,
    )
    check(
        "switch presence unknown -> UNKNOWN, never defaults to a false sense of safety",
        reg.protection_status(None, None, False)["protection_level"] == ProtectionLevel.UNKNOWN.value,
    )

    # --- Toshiba GR-RF900WI-PMV(06)-MG reference case study ---
    # Facts cited here are from this project's own public history
    # (STATUS_MATRIX.md's LOCAL_OPERATIONAL entry) plus the 2026-11-24
    # firmware-control investigation's own two rounds of evidence:
    #
    # Round 1 (static source reading): the CA (0xCA refrigerator) application
    # message set in midealan/devices/ca/message.py and ca/__init__.py has NO
    # firmware/software-version field and NO OTA-related command anywhere --
    # confirmed by reading the real source, not assumed.
    #
    # Round 2 (a single passive re-send of the SAME discovery broadcast this
    # integration already performs routinely -- zero new network behaviour,
    # zero login, zero write): midealan's own discover.py reads bytes
    # 69+ssid_len..75+ssid_len of the decrypted reply into one 6-byte hex
    # field it calls "protocol_version", but never separates the last 3 of
    # those 6 bytes out. An independent sibling reverse-engineering project,
    # nbogojevic/midea-beautiful-air (cited by midealan's OWN _extract_mac
    # docstring as a direct source), decodes exactly those last 3 bytes
    # (reply[72+ssid_len], [73+ssid_len], [74+ssid_len]) as a
    # major.minor.patch firmware_version. Replaying the broadcast against the
    # real fridge (device_id 242992069879584, ssid "toshiba_ca_0072") and
    # decoding with that byte offset produced "5.37.4" -- a real, directly
    # observed value, not fabricated, but recorded here as a cross-validated
    # CANDIDATE rather than an officially documented Midea field, since no
    # vendor spec confirms the semantic label.
    #
    # Two cloud hostnames were separately observed via a prior passive
    # PCAPdroid capture of the TSmartLife PHONE app (not the fridge itself):
    # mp-jp-prod.appsmb.com (general API traffic, login/appliance list -- no
    # OTA-specific subdomain was ever found distinct from this) and
    # sentry.msmartlife.net (confirmed, via embedded Sentry DSN strings, to be
    # ordinary crash/diagnostics reporting, not OTA).
    toshiba = FirmwareRegistry(device_id="242992069879584")
    toshiba.record_baseline(
        FirmwareBaseline(
            manufacturer="toshiba",
            model_id="GR-RF900WI-PMV06-MG",
            device_id="242992069879584",
            firmware_version="5.37.4",  # candidate -- see note above, cross-validated not vendor-confirmed
            protocol_version="059034",  # raw hex of the 3 bytes immediately preceding the firmware bytes
            source="lan_discovery_v3_extended_bytes_cross_referenced_20261124",
        )
    )
    toshiba.register_ota_endpoint(
        OtaEndpoint(
            host="mp-jp-prod.appsmb.com",
            classification=EndpointClassification.SUSPECTED_OTA,
            evidence="TSmartLife cloud API host; no OTA-specific subdomain isolated from general traffic",
            shares_host_with_general_traffic=True,
        )
    )
    toshiba.register_ota_endpoint(
        OtaEndpoint(
            host="sentry.msmartlife.net",
            classification=EndpointClassification.GENERAL_CLOUD,
            evidence="Confirmed Sentry crash/diagnostics DSN, not OTA",
        )
    )
    check(
        "Toshiba: baseline records the real observed candidate firmware version verbatim",
        toshiba.latest_baseline.firmware_version == "5.37.4",
    )
    check(
        "Toshiba: baseline source string flags this as cross-referenced, not vendor-confirmed",
        "cross_referenced" in toshiba.latest_baseline.source,
    )
    check(
        "Toshiba: cloud API host correctly NOT marked CONFIRMED (evidence doesn't support that)",
        toshiba.classify_traffic("mp-jp-prod.appsmb.com") == EndpointClassification.SUSPECTED_OTA,
    )
    check(
        "Toshiba: sentry host correctly cleared as non-OTA",
        toshiba.classify_traffic("sentry.msmartlife.net") == EndpointClassification.GENERAL_CLOUD,
    )
    status = toshiba.protection_status(native_switch_found=False, native_switch_value=None, network_mitigation_active=False)
    check(
        "Toshiba: no native switch + no mitigation configured -> reports NO_MITIGATION, i.e. exposed",
        status["protection_level"] == ProtectionLevel.NO_MITIGATION.value,
    )

    print()
    passed = sum(1 for _, ok in results if ok)
    print(f"{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
