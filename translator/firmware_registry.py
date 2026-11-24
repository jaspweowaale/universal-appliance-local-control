"""Firmware governance registry -- owner-controlled firmware update tracking.

This module is deliberately NOT a ProtocolAdapter and does not sit on the
inbound/outbound message path (see base.py). It is pure bookkeeping: given
facts an investigation has already gathered about a device (by reading
protocol source, APK statics, or passive network capture elsewhere), it
records a firmware baseline, flags version changes, classifies observed
network endpoints against a per-device OTA-endpoint registry, and reports a
protection status.

It never opens a socket, never talks to a device or a manufacturer cloud,
and never blocks anything itself -- blocking firmware traffic is a
firewall/DNS/router action outside this repository's scope. Matches the
project's standing invariant: zero changes to any real device, ever.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EndpointClassification(Enum):
    """How confident we are that a given host is involved in firmware delivery."""

    CONFIRMED_OTA = "confirmed_ota"  # evidence ties this host specifically to firmware delivery
    SUSPECTED_OTA = "suspected_ota"  # plausible but not isolated from general cloud traffic
    GENERAL_CLOUD = "general_cloud"  # confirmed NOT OTA-specific (e.g. telemetry/crash reporting)
    UNKNOWN = "unknown"


class ProtectionLevel(Enum):
    NATIVE_SWITCH_DISABLED = "native_switch_disabled"
    NATIVE_SWITCH_AVAILABLE_NOT_SET = "native_switch_available_not_set"
    NETWORK_MITIGATION_ACTIVE = "network_mitigation_active"
    NO_MITIGATION = "no_mitigation"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FirmwareBaseline:
    manufacturer: str
    model_id: str
    device_id: str
    firmware_version: str | None  # None means "queried, not exposed by this channel"
    protocol_version: str | None = None
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "unknown"  # e.g. "lan_discovery_v3", "cloud_list_appliances", "apk_static"


@dataclass(frozen=True)
class OtaEndpoint:
    host: str  # DNS name or literal IP
    classification: EndpointClassification
    evidence: str  # one-line citation of how this was established
    shares_host_with_general_traffic: bool = False


class FirmwareRegistry:
    """Per-device firmware-governance bookkeeping. One instance per device_id."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self._baselines: list[FirmwareBaseline] = []
        self._endpoints: dict[str, OtaEndpoint] = {}
        self._owner_approved_update: str | None = None

    def record_baseline(self, baseline: FirmwareBaseline) -> None:
        if baseline.device_id != self.device_id:
            raise ValueError(
                f"baseline device_id {baseline.device_id!r} != registry device_id {self.device_id!r}"
            )
        self._baselines.append(baseline)

    @property
    def latest_baseline(self) -> FirmwareBaseline | None:
        return self._baselines[-1] if self._baselines else None

    def check_version_change(self, observed_version: str | None) -> bool:
        """True if observed_version differs from the latest recorded baseline.

        A None observed_version (channel doesn't expose version) never counts
        as a change -- absence of data is not evidence of a change.
        """
        latest = self.latest_baseline
        if latest is None or observed_version is None:
            return False
        return latest.firmware_version != observed_version

    def register_ota_endpoint(self, endpoint: OtaEndpoint) -> None:
        self._endpoints[endpoint.host] = endpoint

    def classify_traffic(self, host: str) -> EndpointClassification:
        endpoint = self._endpoints.get(host)
        return endpoint.classification if endpoint else EndpointClassification.UNKNOWN

    def approve_update(self, firmware_version: str) -> None:
        """Record that the owner explicitly approved updating TO this version.

        This registry never installs anything -- it only tracks the decision
        so protection_status() can distinguish an approved pending update from
        an unapproved one.
        """
        self._owner_approved_update = firmware_version

    def protection_status(
        self,
        native_switch_found: bool | None,
        native_switch_value: str | None,
        network_mitigation_active: bool,
    ) -> dict:
        """Return a status dict, not a verdict string.

        Callers must read the booleans themselves rather than trust a single
        "protected: true" flag -- this is deliberate, per the standing policy
        that protection must never be reported as effective without
        verification (see feedback_firmware_update_control_policy memory).
        """
        if native_switch_found is True and native_switch_value == "disabled":
            level = ProtectionLevel.NATIVE_SWITCH_DISABLED
        elif native_switch_found is True:
            level = ProtectionLevel.NATIVE_SWITCH_AVAILABLE_NOT_SET
        elif native_switch_found is False and network_mitigation_active:
            level = ProtectionLevel.NETWORK_MITIGATION_ACTIVE
        elif native_switch_found is False:
            level = ProtectionLevel.NO_MITIGATION
        else:
            level = ProtectionLevel.UNKNOWN
        return {
            "device_id": self.device_id,
            "protection_level": level.value,
            "latest_baseline": self.latest_baseline,
            "owner_approved_update": self._owner_approved_update,
            "known_endpoints": dict(self._endpoints),
        }
