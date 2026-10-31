"""
Documented interface Home Assistant (or any other consumer) talks to. This
is the only file a HA integration would need to know about; it never needs
to know which manufacturer/protocol a given device uses.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from integration_contract import StandardCommand, StandardMessage
from registry import AdapterRegistry
from command_tracker import CommandAckTracker

EventCallback = Callable[[StandardMessage], Awaitable[None]] | Callable[[StandardMessage], None]


class DeviceNotRegistered(Exception):
    pass


class HomeAssistantInterface:
    """
    Usage from a consumer's point of view:

        iface = HomeAssistantInterface(registry)
        iface.register_device("q10_ss09_pf", manufacturer="roborock", protocol_family="B01")
        iface.subscribe(my_callback)

        # Whatever feeds decrypted bytes in (a legitimate local TLS endpoint
        # today would be the "local" side of Project 1's proxy; right now,
        # for Q10, this is only ever a test fixture - see adapter docstring):
        iface.ingest_inbound("q10_ss09_pf", topic, payload_bytes)

        # Sending a standardized command:
        topic, payload = iface.send_command("q10_ss09_pf", StandardCommand.PAUSE)
        # caller is responsible for actually getting (topic, payload) to the
        # device over a real session - this interface deliberately does not
        # open any network connection itself.
    """

    def __init__(self, registry: AdapterRegistry):
        self._registry = registry
        self._devices: dict[str, tuple[str, str]] = {}
        self._subscribers: list[EventCallback] = []
        self._ack_tracker = CommandAckTracker()

    def register_device(self, device_id: str, *, manufacturer: str, protocol_family: str) -> None:
        self._registry.get(manufacturer, protocol_family)  # raises if unknown - fail fast
        existing = self._devices.get(device_id)
        if existing is not None and existing != (manufacturer, protocol_family):
            raise ValueError(
                f"device_id {device_id!r} is already registered as {existing}, "
                f"refusing to silently switch it to {(manufacturer, protocol_family)} "
                f"(e.g. on a reconnect) - register a new device_id instead"
            )
        self._devices[device_id] = (manufacturer, protocol_family)

    def subscribe(self, callback: EventCallback) -> None:
        self._subscribers.append(callback)

    def _adapter_for(self, device_id: str):
        if device_id not in self._devices:
            raise DeviceNotRegistered(device_id)
        manufacturer, protocol_family = self._devices[device_id]
        return self._registry.get(manufacturer, protocol_family)

    async def ingest_inbound(self, device_id: str, topic: str, payload: bytes) -> StandardMessage:
        adapter = self._adapter_for(device_id)
        message = adapter.parse_inbound(device_id, topic, payload)
        self._ack_tracker.notify_inbound(
            device_id, lambda command: adapter.is_ack_for(command, message.payload)
        )
        for cb in self._subscribers:
            result = cb(message)
            if hasattr(result, "__await__"):
                await result
        return message

    def send_command(self, device_id: str, command: StandardCommand) -> tuple[str, bytes]:
        adapter = self._adapter_for(device_id)
        return adapter.build_outbound(device_id, command)

    def send_command_tracked(self, device_id: str, command: StandardCommand) -> tuple[str, bytes, str]:
        """Like send_command, but also returns a correlation_id you can pass
        to wait_for_ack() to find out whether the device actually acted on
        it within a timeout, instead of assuming success once bytes are sent."""
        topic, payload = self.send_command(device_id, command)
        correlation_id = self._ack_tracker.track(device_id, command)
        return topic, payload, correlation_id

    async def wait_for_ack(self, correlation_id: str, timeout: float = 5.0) -> bool:
        return await self._ack_tracker.wait(correlation_id, timeout)

    def supported_commands(self, device_id: str) -> set[StandardCommand]:
        return self._adapter_for(device_id).supported_commands()
