"""Connection metadata model for the traffic router. No payload inspection -
these fields are everything the router is allowed to know about a connection."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ConnectionMetadata:
    connection_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    device_id: str | None = None
    src_ip: str = ""
    src_port: int = 0
    src_mac: str | None = None
    dst_ip: str = ""
    dst_port: int = 0
    protocol: str = "tcp"
    opened_at: float = field(default_factory=time.time)
    closed_at: float | None = None
    bytes_c2s: int = 0  # client (device) -> server (upstream)
    bytes_s2c: int = 0  # server (upstream) -> client (device)
    state: str = "open"  # open | closed | failed | rejected
    failure_reason: str | None = None
    routed_to: str = ""  # "cloud" | "local" - which upstream actually got used
