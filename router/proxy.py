"""TCP pass-through proxy. This module must never read application-layer
semantics out of the bytes it relays - TLS or not, it only counts bytes and
forwards them. If you find yourself wanting to parse a payload here, that
work belongs in Project 2 (the translator), not here.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from models import ConnectionMetadata
from policy import DevicePolicy, PolicyTable

logger = logging.getLogger("appliance_router")

EventSink = Callable[[dict], Awaitable[None]]


@dataclass
class RouterConfig:
    health_check_timeout: float = 2.0
    relay_chunk_size: int = 65536
    # After this many consecutive local-endpoint failures for a device, stop
    # trying local and fall back to cloud until manually re-enabled. This is
    # the "automatic rollback planning" requirement - rollback is automatic,
    # re-enabling local routing is not.
    max_local_failures_before_rollback: int = 3


class DeviceRoutingState:
    """Per-device health/rollback state. Isolated per device_id - one
    device's failures never affect another device's routing decisions."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.local_consecutive_failures = 0
        self.local_disabled_by_rollback = False

    def record_local_failure(self) -> bool:
        """Returns True if this failure just triggered a rollback."""
        self.local_consecutive_failures += 1
        if self.local_consecutive_failures >= 3 and not self.local_disabled_by_rollback:
            self.local_disabled_by_rollback = True
            return True
        return False

    def record_local_success(self):
        self.local_consecutive_failures = 0


class ApplianceRouter:
    def __init__(self, policy_table: PolicyTable, config: RouterConfig | None = None, event_sink: EventSink | None = None):
        self.policy_table = policy_table
        self.config = config or RouterConfig()
        self.event_sink = event_sink
        self._device_state: dict[str, DeviceRoutingState] = {}
        self.connections: dict[str, ConnectionMetadata] = {}

    def _state_for(self, device_id: str) -> DeviceRoutingState:
        if device_id not in self._device_state:
            self._device_state[device_id] = DeviceRoutingState(device_id)
        return self._device_state[device_id]

    async def _emit(self, message_type: str, **payload):
        if self.event_sink is not None:
            await self.event_sink({"message_type": message_type, **payload})

    async def health_check(self, host: str, port: int) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=self.config.health_check_timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            return False

    async def _choose_upstream(self, policy: DevicePolicy) -> tuple[str, int, str]:
        """Decide which upstream to use for this connection. Returns
        (host, port, label) where label is 'cloud' or 'local'."""
        state = self._state_for(policy.device_id)
        want_local = (
            policy.prefer_local
            and policy.local_host is not None
            and policy.local_port is not None
            and not state.local_disabled_by_rollback
        )
        if want_local:
            healthy = await self.health_check(policy.local_host, policy.local_port)
            if healthy:
                state.record_local_success()
                return policy.local_host, policy.local_port, "local"
            rolled_back = state.record_local_failure()
            if rolled_back:
                await self._emit(
                    "rollback_triggered",
                    device_id=policy.device_id,
                    reason="local endpoint failed health check 3 times in a row",
                )
            # fall through to cloud below
        return policy.cloud_host, policy.cloud_port, "cloud"

    async def handle_connection(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        *,
        src_ip: str,
        src_port: int,
        src_mac: str | None,
        dst_ip: str,
        dst_port: int,
    ):
        policy = self.policy_table.match(src_ip=src_ip, src_mac=src_mac, dst_ip=dst_ip, dst_port=dst_port)
        meta = ConnectionMetadata(
            device_id=policy.device_id if policy else None,
            src_ip=src_ip, src_port=src_port, src_mac=src_mac,
            dst_ip=dst_ip, dst_port=dst_port,
        )
        self.connections[meta.connection_id] = meta

        if policy is None:
            meta.state = "rejected"
            meta.failure_reason = "no matching device policy - isolation guarantee: unknown traffic is dropped, never guessed"
            await self._emit("connection_failed", **vars(meta))
            client_writer.close()
            return

        upstream_host, upstream_port, label = await self._choose_upstream(policy)
        meta.routed_to = label

        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(upstream_host, upstream_port), timeout=self.config.health_check_timeout
            )
        except Exception as exc:
            meta.state = "failed"
            meta.failure_reason = f"upstream connect failed: {exc}"
            await self._emit("connection_failed", **vars(meta))
            client_writer.close()
            return

        await self._emit("connection_opened", **vars(meta))

        async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, counter_attr: str):
            try:
                while True:
                    chunk = await reader.read(self.config.relay_chunk_size)
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
                    setattr(meta, counter_attr, getattr(meta, counter_attr) + len(chunk))
            except Exception:
                pass

        await asyncio.gather(
            relay(client_reader, upstream_writer, "bytes_c2s"),
            relay(upstream_reader, client_writer, "bytes_s2c"),
        )

        meta.state = "closed"
        meta.closed_at = asyncio.get_event_loop().time()
        for w in (client_writer, upstream_writer):
            try:
                w.close()
            except Exception:
                pass
        await self._emit("connection_closed", **vars(meta))
