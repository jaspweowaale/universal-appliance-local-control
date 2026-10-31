"""Adapter registry. Adding a new manufacturer/protocol means adding one
entry here and one new file under adapters/ - nothing else changes."""
from __future__ import annotations

from base import ProtocolAdapter


class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[tuple[str, str], ProtocolAdapter] = {}

    def register(self, adapter: ProtocolAdapter) -> None:
        key = (adapter.manufacturer, adapter.protocol_family)
        if key in self._adapters:
            raise ValueError(f"adapter already registered for {key}")
        self._adapters[key] = adapter

    def get(self, manufacturer: str, protocol_family: str) -> ProtocolAdapter:
        key = (manufacturer, protocol_family)
        if key not in self._adapters:
            raise KeyError(f"no adapter registered for {key}")
        return self._adapters[key]

    def all_manufacturers(self) -> set[str]:
        return {m for m, _ in self._adapters}
