"""
Offline, synthetic-traffic validation of the appliance router (Project 1).
Everything here runs on 127.0.0.1 loopback only - no real device, no real
UniFi, no real cloud. "Cloud" and "local endpoint" are both fake echo
servers we spin up ourselves for the duration of the test.
"""
import asyncio
import sys

from policy import DevicePolicy, PolicyTable
from proxy import ApplianceRouter, RouterConfig

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


async def make_echo_server(host="127.0.0.1", port=0):
    async def handler(reader, writer):
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except Exception:
            pass
        writer.close()

    server = await asyncio.start_server(handler, host, port)
    actual_port = server.sockets[0].getsockname()[1]
    return server, actual_port


async def run_client_through_router(router_port, payload, src_ip="192.0.2.10", src_mac="02:00:00:00:00:01"):
    reader, writer = await asyncio.open_connection("127.0.0.1", router_port)
    writer.write(payload)
    await writer.drain()
    echoed = await asyncio.wait_for(reader.readexactly(len(payload)), timeout=3)
    writer.close()
    return echoed


async def serve_one(router, device_id_label, listen_port, src_ip, src_mac, dst_ip, dst_port):
    srv = await asyncio.start_server(
        lambda r, w: router.handle_connection(
            r, w, src_ip=src_ip, src_port=55555, src_mac=src_mac, dst_ip=dst_ip, dst_port=dst_port
        ),
        "127.0.0.1", listen_port,
    )
    return srv


async def main():
    events = []

    async def sink(ev):
        events.append(ev)

    cloud_server, cloud_port = await make_echo_server()
    local_server, local_port = await make_echo_server()

    policy = DevicePolicy(
        device_id="q10_sim",
        match_src_ip="192.0.2.10",
        cloud_host="127.0.0.1", cloud_port=cloud_port,
        local_host="127.0.0.1", local_port=local_port,
        prefer_local=False,
    )
    table = PolicyTable([policy])
    router = ApplianceRouter(table, RouterConfig(health_check_timeout=1.0), event_sink=sink)

    router_listen_port = 54321

    async def one_shot_listener():
        srv = await asyncio.start_server(
            lambda r, w: router.handle_connection(
                r, w, src_ip="192.0.2.10", src_port=1234, src_mac="02:00:00:00:00:01",
                dst_ip="203.0.113.50", dst_port=8883,
            ),
            "127.0.0.1", 0,
        )
        return srv

    # --- Test 1: pass-through forwards bytes byte-for-byte unmodified, defaults to cloud ---
    srv = await one_shot_listener()
    port = srv.sockets[0].getsockname()[1]
    payload = b"synthetic-tls-shaped-bytes-not-inspected-\x00\x01\x02"
    echoed = await run_client_through_router(port, payload)
    await asyncio.sleep(0.1)
    check("pass-through: bytes returned unmodified", echoed == payload)
    check("pass-through: defaulted to cloud (prefer_local=False)", any(e.get("routed_to") == "cloud" for e in events if "routed_to" in e))
    srv.close()
    await srv.wait_closed()

    # --- Test 2: unknown device (no matching policy) is rejected, not guessed ---
    events.clear()
    srv2 = await asyncio.start_server(
        lambda r, w: router.handle_connection(
            r, w, src_ip="192.0.2.99", src_port=1, src_mac="aa:bb:cc:dd:ee:ff",
            dst_ip="1.2.3.4", dst_port=443,
        ),
        "127.0.0.1", 0,
    )
    port2 = srv2.sockets[0].getsockname()[1]
    try:
        r, w = await asyncio.open_connection("127.0.0.1", port2)
        w.write(b"hello")
        await w.drain()
        try:
            data = await asyncio.wait_for(r.read(100), timeout=1)
        except ConnectionResetError:
            data = b""  # abrupt close with no data is the expected rejection behavior on this OS
        check("unmatched traffic: connection closed with no data relayed", data == b"")
    finally:
        srv2.close()
        await srv2.wait_closed()
    check("unmatched traffic: emitted connection_failed, not silently dropped", any(e["message_type"] == "connection_failed" for e in events))

    # --- Test 3: local endpoint preferred when healthy ---
    events.clear()
    policy_local = DevicePolicy(
        device_id="q10_sim_local",
        match_src_ip="192.0.2.49",
        cloud_host="127.0.0.1", cloud_port=cloud_port,
        local_host="127.0.0.1", local_port=local_port,
        prefer_local=True,
    )
    table2 = PolicyTable([policy_local])
    router2 = ApplianceRouter(table2, RouterConfig(health_check_timeout=1.0), event_sink=sink)
    srv3 = await asyncio.start_server(
        lambda r, w: router2.handle_connection(
            r, w, src_ip="192.0.2.49", src_port=1, src_mac=None, dst_ip="203.0.113.50", dst_port=8883,
        ),
        "127.0.0.1", 0,
    )
    port3 = srv3.sockets[0].getsockname()[1]
    echoed3 = await run_client_through_router(port3, b"local-path-test")
    check("local preference: healthy local endpoint used when prefer_local=True", any(e.get("routed_to") == "local" for e in events if "routed_to" in e))
    srv3.close()
    await srv3.wait_closed()

    # --- Test 4: automatic rollback after repeated local failures, isolated per device ---
    events.clear()
    dead_port = 1  # nothing listens here -> guaranteed health-check failure
    policy_rollback = DevicePolicy(
        device_id="q10_sim_rollback",
        match_src_ip="192.0.2.50",
        cloud_host="127.0.0.1", cloud_port=cloud_port,
        local_host="127.0.0.1", local_port=dead_port,
        prefer_local=True,
    )
    policy_unaffected = DevicePolicy(
        device_id="other_device_unaffected",
        match_src_ip="192.0.2.51",
        cloud_host="127.0.0.1", cloud_port=cloud_port,
        local_host="127.0.0.1", local_port=local_port,
        prefer_local=True,
    )
    table3 = PolicyTable([policy_rollback, policy_unaffected])
    router3 = ApplianceRouter(table3, RouterConfig(health_check_timeout=0.3), event_sink=sink)

    for attempt in range(3):
        srv4 = await asyncio.start_server(
            lambda r, w: router3.handle_connection(
                r, w, src_ip="192.0.2.50", src_port=1, src_mac=None, dst_ip="x", dst_port=1,
            ),
            "127.0.0.1", 0,
        )
        p4 = srv4.sockets[0].getsockname()[1]
        try:
            await run_client_through_router(p4, b"rollback-attempt")
        except Exception:
            pass
        srv4.close()
        await srv4.wait_closed()

    check("rollback: triggered after 3 consecutive local failures", any(e["message_type"] == "rollback_triggered" for e in events))
    check("rollback: device state marks local disabled", router3._state_for("q10_sim_rollback").local_disabled_by_rollback)
    check("rollback: isolated - other device's state untouched", not router3._state_for("other_device_unaffected").local_disabled_by_rollback)

    cloud_server.close()
    local_server.close()
    await cloud_server.wait_closed()
    await local_server.wait_closed()

    print()
    passed = sum(1 for _, ok in results if ok)
    print(f"TOTAL: {passed}/{len(results)} checks passed")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
