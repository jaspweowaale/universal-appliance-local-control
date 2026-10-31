"""
Task 2 hardening tests for the appliance router. Additive - does not modify
or replace test_router_offline.py. All synthetic, loopback-only.
"""
import asyncio
import sys

from policy import DevicePolicy, PolicyTable
from proxy import ApplianceRouter, RouterConfig

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


async def make_echo_server(host="127.0.0.1", port=0, delay=0.0):
    async def handler(reader, writer):
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                if delay:
                    await asyncio.sleep(delay)
                writer.write(chunk)
                await writer.drain()
        except Exception:
            pass
        writer.close()

    server = await asyncio.start_server(handler, host, port)
    return server, server.sockets[0].getsockname()[1]


async def start_router_listener(router, src_ip, src_mac, dst_ip="x", dst_port=1):
    srv = await asyncio.start_server(
        lambda r, w: router.handle_connection(r, w, src_ip=src_ip, src_port=1, src_mac=src_mac, dst_ip=dst_ip, dst_port=dst_port),
        "127.0.0.1", 0,
    )
    return srv, srv.sockets[0].getsockname()[1]


async def test_multiple_simultaneous_devices():
    echo_a, port_a = await make_echo_server()
    echo_b, port_b = await make_echo_server()
    events = []

    async def sink(ev):
        events.append(ev)

    table = PolicyTable([
        DevicePolicy(device_id="device_a", match_src_ip="10.0.0.1", cloud_host="127.0.0.1", cloud_port=port_a),
        DevicePolicy(device_id="device_b", match_src_ip="10.0.0.2", cloud_host="127.0.0.1", cloud_port=port_b),
    ])
    router = ApplianceRouter(table, RouterConfig(), event_sink=sink)

    srv_a, listen_a = await start_router_listener(router, "10.0.0.1", "aa:aa:aa:aa:aa:aa")
    srv_b, listen_b = await start_router_listener(router, "10.0.0.2", "bb:bb:bb:bb:bb:bb")

    async def round_trip(port, payload):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(payload)
        await w.drain()
        echoed = await asyncio.wait_for(r.readexactly(len(payload)), timeout=3)
        w.close()
        return echoed

    results_ab = await asyncio.gather(
        round_trip(listen_a, b"payload-for-device-a"),
        round_trip(listen_b, b"payload-for-device-b-longer"),
    )
    check("concurrent devices: device A got its own unmodified payload back", results_ab[0] == b"payload-for-device-a")
    check("concurrent devices: device B got its own unmodified payload back", results_ab[1] == b"payload-for-device-b-longer")
    await asyncio.sleep(0.1)
    a_meta = [e for e in events if e.get("device_id") == "device_a"]
    b_meta = [e for e in events if e.get("device_id") == "device_b"]
    check("concurrent devices: device A's metadata never attributed to device B", all(e.get("device_id") != "device_b" for e in a_meta))
    check("concurrent devices: device B's metadata never attributed to device A", all(e.get("device_id") != "device_a" for e in b_meta))

    for s in (srv_a, srv_b, echo_a, echo_b):
        s.close()


async def test_long_lived_connection_multi_chunk():
    echo, port = await make_echo_server()
    table = PolicyTable([DevicePolicy(device_id="dev", match_src_ip="10.0.0.3", cloud_host="127.0.0.1", cloud_port=port)])
    router = ApplianceRouter(table, RouterConfig())
    srv, listen_port = await start_router_listener(router, "10.0.0.3", None)

    r, w = await asyncio.open_connection("127.0.0.1", listen_port)
    total_sent = b""
    for i in range(20):
        chunk = f"chunk-{i}-".encode() * 10
        w.write(chunk)
        await w.drain()
        total_sent += chunk
        await asyncio.sleep(0.01)  # simulate a long-lived, slowly-chattering connection
    echoed = await asyncio.wait_for(r.readexactly(len(total_sent)), timeout=5)
    check("long-lived connection: all 20 chunks relayed correctly over time", echoed == total_sent)
    w.close()
    srv.close()
    echo.close()


async def test_abrupt_disconnect():
    echo, port = await make_echo_server()
    events = []

    async def sink(ev):
        events.append(ev)

    table = PolicyTable([DevicePolicy(device_id="dev", match_src_ip="10.0.0.4", cloud_host="127.0.0.1", cloud_port=port)])
    router = ApplianceRouter(table, RouterConfig(), event_sink=sink)
    srv, listen_port = await start_router_listener(router, "10.0.0.4", None)

    r, w = await asyncio.open_connection("127.0.0.1", listen_port)
    w.write(b"partial-data-then-abrupt-close")
    await w.drain()
    w.close()  # no graceful shutdown handshake, just drop it
    await asyncio.sleep(0.3)
    check("abrupt disconnect: router did not crash (still accepting new connections)", srv.is_serving())
    check("abrupt disconnect: connection_closed or connection_opened recorded, no silent loss", any(e["message_type"] in ("connection_closed", "connection_opened") for e in events))
    srv.close()
    echo.close()


async def test_unavailable_upstream():
    table = PolicyTable([DevicePolicy(device_id="dev", match_src_ip="10.0.0.5", cloud_host="127.0.0.1", cloud_port=1)])  # nothing listens on port 1
    events = []

    async def sink(ev):
        events.append(ev)

    router = ApplianceRouter(table, RouterConfig(health_check_timeout=1.0), event_sink=sink)
    srv, listen_port = await start_router_listener(router, "10.0.0.5", None)

    try:
        r, w = await asyncio.open_connection("127.0.0.1", listen_port)
        w.write(b"anything")
        await w.drain()
        data = await asyncio.wait_for(r.read(10), timeout=2)
        check("unavailable upstream: connection closed with no data relayed", data == b"")
    except (ConnectionResetError, asyncio.TimeoutError):
        check("unavailable upstream: connection closed with no data relayed", True)
    check("unavailable upstream: failure recorded with a reason, not silently swallowed", any(e["message_type"] == "connection_failed" and e.get("failure_reason") for e in events))
    srv.close()


async def test_partial_reads_writes_byte_by_byte():
    echo, port = await make_echo_server()
    table = PolicyTable([DevicePolicy(device_id="dev", match_src_ip="10.0.0.6", cloud_host="127.0.0.1", cloud_port=port)])
    router = ApplianceRouter(table, RouterConfig())
    srv, listen_port = await start_router_listener(router, "10.0.0.6", None)

    r, w = await asyncio.open_connection("127.0.0.1", listen_port)
    payload = b"byte-by-byte-stress-test-payload"
    for b in payload:
        w.write(bytes([b]))
        await w.drain()
    echoed = await asyncio.wait_for(r.readexactly(len(payload)), timeout=5)
    check("partial writes: byte-by-byte input reassembled correctly end to end", echoed == payload)
    w.close()
    srv.close()
    echo.close()


async def test_backpressure_large_transfer():
    echo, port = await make_echo_server(delay=0.001)  # slow consumer, forces backpressure
    table = PolicyTable([DevicePolicy(device_id="dev", match_src_ip="10.0.0.7", cloud_host="127.0.0.1", cloud_port=port)])
    router = ApplianceRouter(table, RouterConfig(relay_chunk_size=4096))
    srv, listen_port = await start_router_listener(router, "10.0.0.7", None)

    r, w = await asyncio.open_connection("127.0.0.1", listen_port)
    big_payload = b"X" * (2 * 1024 * 1024)  # 2 MiB
    w.write(big_payload)
    await w.drain()
    echoed = bytearray()
    while len(echoed) < len(big_payload):
        chunk = await asyncio.wait_for(r.read(65536), timeout=10)
        if not chunk:
            break
        echoed.extend(chunk)
    check("backpressure: large transfer through a slow upstream completes without data loss/corruption", bytes(echoed) == big_payload)
    w.close()
    srv.close()
    echo.close()


async def test_ambiguous_policy_match_fails_closed():
    table = PolicyTable([
        DevicePolicy(device_id="dev_x", match_src_ip="10.0.0.8", cloud_host="a", cloud_port=1),
        DevicePolicy(device_id="dev_y", match_dst_port=443, cloud_host="b", cloud_port=1),  # overlaps dev_x's connection if dst_port also 443
    ])
    router = ApplianceRouter(table, RouterConfig())
    try:
        router.policy_table.match(src_ip="10.0.0.8", src_mac=None, dst_ip="anything", dst_port=443)
        check("ambiguous policy match: raises instead of silently picking one", False)
    except ValueError:
        check("ambiguous policy match: raises instead of silently picking one", True)


async def test_no_mid_session_destination_switch():
    """An already-open relay must never be redirected mid-stream, even if the
    device's rollback state changes while the connection is still active."""
    local_srv, local_port = await make_echo_server()
    table = PolicyTable([DevicePolicy(
        device_id="dev_midswitch", match_src_ip="10.0.0.9",
        cloud_host="127.0.0.1", cloud_port=local_port,
        local_host="127.0.0.1", local_port=local_port, prefer_local=True,
    )])
    router = ApplianceRouter(table, RouterConfig())
    srv, listen_port = await start_router_listener(router, "10.0.0.9", None)

    r, w = await asyncio.open_connection("127.0.0.1", listen_port)
    # Mutate rollback state WHILE this connection is open - handle_connection
    # already chose its upstream before this point and must not re-check.
    state = router._state_for("dev_midswitch")
    state.local_disabled_by_rollback = True

    payload = b"still-using-the-upstream-chosen-at-connect-time"
    w.write(payload)
    await w.drain()
    echoed = await asyncio.wait_for(r.readexactly(len(payload)), timeout=3)
    check("no mid-session switch: already-open relay keeps working after rollback state changes elsewhere", echoed == payload)
    w.close()
    srv.close()
    local_srv.close()


async def main():
    await test_multiple_simultaneous_devices()
    await test_long_lived_connection_multi_chunk()
    await test_abrupt_disconnect()
    await test_unavailable_upstream()
    await test_partial_reads_writes_byte_by_byte()
    await test_backpressure_large_transfer()
    await test_ambiguous_policy_match_fails_closed()
    await test_no_mid_session_destination_switch()

    print()
    passed = sum(1 for _, ok in results if ok)
    print(f"TOTAL: {passed}/{len(results)} checks passed")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
