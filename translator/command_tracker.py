"""
Generic command-acknowledgement/timeout tracking. The bookkeeping here is
manufacturer-independent; the actual "is this inbound message the ack for
that command" question is answered by the adapter (ProtocolAdapter.is_ack_for),
per the "keep protocol-specific code inside adapters" requirement.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass


@dataclass
class _Pending:
    device_id: str
    command: object
    future: asyncio.Future


class CommandAckTracker:
    def __init__(self):
        self._pending: dict[str, _Pending] = {}

    def track(self, device_id: str, command) -> str:
        correlation_id = uuid.uuid4().hex
        self._pending[correlation_id] = _Pending(device_id, command, asyncio.get_event_loop().create_future())
        return correlation_id

    def notify_inbound(self, device_id: str, is_ack_for) -> None:
        """is_ack_for(command) -> bool, supplied by the caller (which already
        has the adapter + decoded payload available)."""
        for cid, pending in list(self._pending.items()):
            if pending.device_id != device_id or pending.future.done():
                continue
            if is_ack_for(pending.command):
                pending.future.set_result(True)

    async def wait(self, correlation_id: str, timeout: float) -> bool:
        pending = self._pending.get(correlation_id)
        if pending is None:
            return False
        try:
            await asyncio.wait_for(pending.future, timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(correlation_id, None)
