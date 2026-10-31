"""Per-device, per-manufacturer credential isolation. Mirrors the Phase A3
pattern: callers can ask whether a field is present, never retrieve-and-log
it accidentally through a generic path. Values never appear in __repr__."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _DeviceCredentials:
    device_id: str
    manufacturer: str
    _values: dict[str, str] = field(default_factory=dict, repr=False)

    def __repr__(self):
        # Deliberately do not include _values, even in a debug repr.
        return f"_DeviceCredentials(device_id={self.device_id!r}, manufacturer={self.manufacturer!r}, fields={sorted(self._values)})"


class CredentialStore:
    def __init__(self):
        self._by_device: dict[str, _DeviceCredentials] = {}

    def put(self, device_id: str, manufacturer: str, field_name: str, value: str) -> None:
        existing = self._by_device.get(device_id)
        if existing is not None and existing.manufacturer != manufacturer:
            raise ValueError(
                f"device_id {device_id!r} already registered under manufacturer "
                f"{existing.manufacturer!r}, refusing to mix in {manufacturer!r} credentials"
            )
        if existing is None:
            existing = _DeviceCredentials(device_id=device_id, manufacturer=manufacturer)
            self._by_device[device_id] = existing
        existing._values[field_name] = value

    def get(self, device_id: str, field_name: str) -> str | None:
        dev = self._by_device.get(device_id)
        if dev is None:
            return None
        return dev._values.get(field_name)

    def has(self, device_id: str, field_name: str) -> bool:
        dev = self._by_device.get(device_id)
        return dev is not None and field_name in dev._values

    def field_inventory(self, device_id: str) -> dict[str, bool]:
        """Safe-to-log/report view: which fields exist, never their values."""
        dev = self._by_device.get(device_id)
        if dev is None:
            return {}
        return {k: True for k in dev._values}
