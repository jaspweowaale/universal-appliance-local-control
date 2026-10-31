"""Per-device routing policy. The router matches an incoming connection to
exactly one policy (or none, in which case the connection is rejected) and
never lets one device's traffic match another device's policy."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DevicePolicy:
    device_id: str
    # Matching: all specified fields must match; unspecified (None) fields are wildcards.
    match_src_ip: str | None = None
    match_src_mac: str | None = None
    match_dst_ip: str | None = None
    match_dst_port: int | None = None

    # Upstream destinations.
    cloud_host: str = ""
    cloud_port: int = 0
    local_host: str | None = None
    local_port: int | None = None

    # Whether to prefer the local endpoint over cloud when both are healthy.
    # Defaults to False: cloud pass-through is always the safe default, a
    # device is only ever routed locally if this is explicitly set true AND
    # a local endpoint is actually configured.
    prefer_local: bool = False


class PolicyTable:
    """Holds all device policies. Isolation guarantee: match() returns at
    most one policy, and policies are never merged/combined."""

    def __init__(self, policies: list[DevicePolicy]):
        ids = [p.device_id for p in policies]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate device_id in policy table")
        self._policies = list(policies)

    def match(
        self,
        *,
        src_ip: str,
        src_mac: str | None,
        dst_ip: str,
        dst_port: int,
    ) -> DevicePolicy | None:
        candidates = []
        for p in self._policies:
            if p.match_src_ip is not None and p.match_src_ip != src_ip:
                continue
            if p.match_src_mac is not None and p.match_src_mac != src_mac:
                continue
            if p.match_dst_ip is not None and p.match_dst_ip != dst_ip:
                continue
            if p.match_dst_port is not None and p.match_dst_port != dst_port:
                continue
            candidates.append(p)
        if len(candidates) > 1:
            # Ambiguous policies are a configuration error, not something to
            # silently resolve - fail closed rather than guess which device
            # a connection belongs to.
            raise ValueError(
                f"ambiguous policy match for src_ip={src_ip} dst={dst_ip}:{dst_port}: "
                f"{[c.device_id for c in candidates]}"
            )
        return candidates[0] if candidates else None

    def get(self, device_id: str) -> DevicePolicy | None:
        for p in self._policies:
            if p.device_id == device_id:
                return p
        return None
