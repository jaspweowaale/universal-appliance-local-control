"""Abstract protocol adapter interface. A new manufacturer/protocol is added
by implementing this class - nothing else in Project 2, and nothing in
Project 1, needs to change."""
from __future__ import annotations

from abc import ABC, abstractmethod

from integration_contract import StandardCommand, StandardMessage


class ProtocolAdapter(ABC):
    manufacturer: str
    protocol_family: str

    @abstractmethod
    def parse_inbound(self, device_id: str, topic: str, payload: bytes) -> StandardMessage:
        """Turn a raw (already-decrypted) topic+payload pair into a
        StandardMessage. Must never raise on malformed input silently -
        either return a message with message_type=ADAPTER_ERROR or raise."""

    @abstractmethod
    def build_outbound(self, device_id: str, command: StandardCommand) -> tuple[str, bytes]:
        """Turn a standardized command into (topic, payload) bytes ready to
        hand to a legitimate local TLS endpoint. Raises NotImplementedError
        for commands this adapter/model doesn't support."""

    @abstractmethod
    def supported_commands(self) -> set[StandardCommand]: ...

    @abstractmethod
    def is_ack_for(self, command: StandardCommand, inbound_payload: dict) -> bool:
        """Protocol-specific: does this already-parsed inbound payload count
        as the device's acknowledgement of the given outbound command?"""
