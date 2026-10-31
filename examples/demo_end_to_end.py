"""
End-to-end demo: a simulated appliance <-> Project 1 (router, real loopback
TCP, byte-for-byte pass-through) <-> a simulated "legitimate local endpoint"
(stand-in for where real TLS would terminate) <-> Project 2 (translator) <->
a simulated Home Assistant consumer.

Everything in this file runs on 127.0.0.1. No real device, no real Roborock
cloud, no real UniFi, no DNS/firewall changes. The "local endpoint" is
plaintext here deliberately - this demo is about proving the architecture's
data flow and separation of concerns, not about pretending we have solved
TLS trust for ss09 (we haven't - see ARCHITECTURE.md).
"""
import asyncio
import json
import sys

sys.path.insert(0, "router")
sys.path.insert(0, "translator")
sys.path.insert(0, "translator/adapters")
sys.path.insert(0, ".")

from policy import DevicePolicy, PolicyTable  # noqa: E402
from proxy import ApplianceRouter, RouterConfig  # noqa: E402
from registry import AdapterRegistry  # noqa: E402
from ha_interface import HomeAssistantInterface  # noqa: E402
from integration_contract import StandardCommand, MessageType  # noqa: E402

sys.path.insert(0, "translator")
from adapters.roborock_b01 import RoborockB01Adapter  # noqa: E402

DEVICE_ID = "q10_ss09_pf"


async def main():
    # ---- Project 2 setup: translator + HA-facing interface ----
    registry = AdapterRegistry()
    registry.register(RoborockB01Adapter())
    iface = HomeAssistantInterface(registry)
    iface.register_device(DEVICE_ID, manufacturer="roborock", protocol_family="B01")

    print("[HA] subscribing to standardized device events")

    def ha_consumer(msg):
        if msg.message_type == MessageType.DEVICE_EVENT:
            print(f"[HA] received standardized event for {msg.device_id}: {msg.payload.get('kind')} "
                  f"state={msg.payload.get('state')} battery={msg.payload.get('battery')}")
        elif msg.message_type == MessageType.ADAPTER_ERROR:
            print(f"[HA] adapter error for {msg.device_id}: {msg.payload.get('error')}")

    iface.subscribe(ha_consumer)

    # ---- "legitimate local endpoint" stand-in: receives raw bytes off the
    # router, feeds them to the translator, and (if the translator's HA
    # layer wants to respond) writes the response back down the same
    # connection. In a real deployment this is where trusted TLS would
    # terminate - see ARCHITECTURE.md section on where that boundary is. ----
    async def local_endpoint_handler(reader, writer):
        data = await reader.read(65536)
        if not data:
            writer.close()
            return
        print(f"[local-endpoint] received {len(data)} bytes, handing to translator")
        await iface.ingest_inbound(DEVICE_ID, "rr/m/o/demo-client-id", data)

        # Demo-only: after reporting status, HA decides to pause the vacuum.
        print("[HA] issuing standardized PAUSE command")
        topic, payload = iface.send_command(DEVICE_ID, StandardCommand.PAUSE)
        print(f"[local-endpoint] writing translated command back to device, topic={topic}")
        writer.write(payload)
        await writer.drain()
        writer.close()

    local_server = await asyncio.start_server(local_endpoint_handler, "127.0.0.1", 0)
    local_port = local_server.sockets[0].getsockname()[1]

    # Fake "cloud" - present only so the router has a configured fallback;
    # never actually used in this demo since the local endpoint is healthy.
    async def fake_cloud_handler(reader, writer):
        await reader.read(65536)
        writer.close()

    cloud_server = await asyncio.start_server(fake_cloud_handler, "127.0.0.1", 0)
    cloud_port = cloud_server.sockets[0].getsockname()[1]

    # ---- Project 1 setup: router, policy prefers the local endpoint ----
    async def router_event_sink(ev):
        print(f"[router] {ev['message_type']}: routed_to={ev.get('routed_to')} device_id={ev.get('device_id')}")

    policy = DevicePolicy(
        device_id=DEVICE_ID,
        match_src_ip="192.0.2.10",  # the real Q10's IP, used here only as a label/matcher in simulation
        cloud_host="127.0.0.1", cloud_port=cloud_port,
        local_host="127.0.0.1", local_port=local_port,
        prefer_local=True,
    )
    router = ApplianceRouter(PolicyTable([policy]), RouterConfig(health_check_timeout=1.0), event_sink=router_event_sink)

    async def router_listen_handler(reader, writer):
        await router.handle_connection(
            reader, writer,
            src_ip="192.0.2.10", src_port=50256, src_mac="02:00:00:00:00:01",
            dst_ip="203.0.113.50", dst_port=8883,  # the real cloud endpoint, used only as a label here
        )

    router_server = await asyncio.start_server(router_listen_handler, "127.0.0.1", 0)
    router_port = router_server.sockets[0].getsockname()[1]

    # ---- "simulated appliance": connects through the router, exactly as a
    # real device would connect to its configured MQTT host:port. ----
    print(f"[fake-device] connecting through router at 127.0.0.1:{router_port}")
    dev_reader, dev_writer = await asyncio.open_connection("127.0.0.1", router_port)

    synthetic_status = json.dumps({"dps": {"121": {"state": "charging", "battery": 100}}}).encode()
    print("[fake-device] sending synthetic status payload (the kind of bytes a real Q10's MQTT status update would carry, pre-decryption)")
    dev_writer.write(synthetic_status)
    await dev_writer.drain()

    reply = await asyncio.wait_for(dev_reader.read(65536), timeout=3)
    reply_dps = json.loads(reply)["dps"]
    print(f"[fake-device] received command back through the router: dps={reply_dps}")

    dev_writer.close()
    for s in (local_server, cloud_server, router_server):
        s.close()
    await asyncio.sleep(0.1)

    print()
    print("Demo complete: fake device -> Project 1 router (unmodified pass-through, metadata recorded)")
    print("             -> local endpoint -> Project 2 translator -> standardized event -> HA consumer")
    print("             -> HA issues standardized command -> Project 2 translates -> back through router -> device")


if __name__ == "__main__":
    asyncio.run(main())
