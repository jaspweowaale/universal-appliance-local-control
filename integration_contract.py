"""
Shared, transport-independent contract between the traffic router (Project 1)
and the protocol translator (Project 2). Neither project depends on the
other's internals - both depend only on this module.

Design rule: this module must never import anything Roborock-specific, and
must never import anything UniFi/router-specific. If a field here starts
looking manufacturer- or transport-specific, it belongs in an adapter/policy
object instead, not here.
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class Direction(str, enum.Enum):
    INBOUND = "inbound"    # device/appliance -> us
    OUTBOUND = "outbound"  # us -> device/appliance


class MessageType(str, enum.Enum):
    # Router-level (Project 1) connection lifecycle - router emits these,
    # it never emits DEVICE_EVENT or DEVICE_COMMAND; it does not understand
    # manufacturer payloads.
    CONNECTION_OPENED = "connection_opened"
    CONNECTION_CLOSED = "connection_closed"
    CONNECTION_FAILED = "connection_failed"
    HEALTH_CHECK_RESULT = "health_check_result"
    ROLLBACK_TRIGGERED = "rollback_triggered"

    # Translator-level (Project 2) - only the translator ever emits/consumes these.
    DEVICE_EVENT = "device_event"       # standardized state coming from a device
    DEVICE_COMMAND = "device_command"   # standardized command going to a device
    ADAPTER_ERROR = "adapter_error"


class AuthStatus(str, enum.Enum):
    NOT_APPLICABLE = "not_applicable"   # e.g. a router-level connection-metadata message
    UNVERIFIED = "unverified"           # payload present but not cryptographically checked
    VERIFIED = "verified"               # signature/credential check passed
    REJECTED = "rejected"               # signature/credential check failed


@dataclass
class StandardMessage:
    """The one envelope shape both projects speak. Payload contents are
    opaque to anything except the adapter that produced/consumes them."""

    device_id: str
    protocol_adapter: str          # e.g. "roborock_b01", or "router" for Project-1-originated messages
    direction: Direction
    message_type: MessageType
    payload: dict[str, Any]
    auth_status: AuthStatus = AuthStatus.NOT_APPLICABLE
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)

    def redacted(self) -> dict[str, Any]:
        """Safe-to-log representation. Never include this object's raw
        payload in a log line directly - always go through this method.
        Strips any key that looks credential-shaped, recursively."""
        SENSITIVE_KEYS = {
            "password", "secret", "token", "localkey", "local_key", "key",
            "credential", "sign", "signature", "private_key", "apikey",
            "api_key", "duid",  # duid is an identifier, not a secret, but
            # treat conservatively since it is device-identifying.
        }

        def scrub(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {
                    k: ("<redacted>" if k.lower() in SENSITIVE_KEYS else scrub(v))
                    for k, v in obj.items()
                }
            if isinstance(obj, list):
                return [scrub(v) for v in obj]
            return obj

        return {
            "device_id": self.device_id,
            "protocol_adapter": self.protocol_adapter,
            "direction": self.direction.value,
            "message_type": self.message_type.value,
            "auth_status": self.auth_status.value,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "payload": scrub(self.payload),
        }


class StandardCommand(str, enum.Enum):
    """Manufacturer-independent commands the translator layer accepts from
    a consumer (Home Assistant or anything else). Not every adapter will
    support every command - unsupported ones raise NotImplementedError."""
    GET_STATUS = "get_status"
    START = "start"
    PAUSE = "pause"
    DOCK = "dock"
    GET_MAP = "get_map"  # reserved for future map-data work, not implemented by any adapter yet


class StandardEventKind(str, enum.Enum):
    """Manufacturer-independent event kinds a translator produces."""
    STATUS = "status"
    BATTERY = "battery"
    ERROR = "error"
    MAP_UPDATE = "map_update"  # reserved, not implemented
