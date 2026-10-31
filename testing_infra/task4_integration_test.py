"""
Task 4 - integration test: a complete simulated TLS session through the
router, using REAL MQTT 3.1.1 wire framing (CONNECT/CONNACK/SUBSCRIBE/
SUBACK/PUBLISH) and REAL TLS (self-signed, locally-generated test cert),
not the raw-JSON-over-plain-TCP shortcut the first demo used.

Topology (all on 127.0.0.1, nothing touches the real network):

  device client --TLS--> [ROUTER, pure byte relay] --TLS--> [MINIMAL MQTT BROKER]
                                                                   ^
                                                                   |
                                        translator-side client ---+ (connects directly,
                                        standing in for "the legitimate local endpoint")

The router never terminates TLS and never parses MQTT - it only relays the
encrypted byte stream between the device-side socket and the broker-side
socket, exactly as Project 1 is specified to behave. Both MQTT clients here
are aiomqtt (asyncio-native) - an earlier attempt using paho-mqtt's threaded
client hit a handshake-timeout incompatibility with our asyncio broker
(root cause not pinned down further; aiomqtt integrates cleanly, so we
standardized on it rather than burn more time on paho's threading model).

IMPORTANT: this proves our own prototype's plumbing works under real TLS/
MQTT framing. It proves NOTHING about whether the real Q10 ss09 trusts this
(or any) certificate - that is a completely separate, unverified question.
See ARCHITECTURE.md / Task 5 report.
"""
import asyncio
import json
import ssl
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "router"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "translator"))

import aiomqtt  # noqa: E402

from gen_test_cert import generate as gen_cert  # noqa: E402
from minimal_mqtt_broker import MinimalMqttBroker  # noqa: E402
from policy import DevicePolicy, PolicyTable  # noqa: E402
from proxy import ApplianceRouter, RouterConfig  # noqa: E402
from registry import AdapterRegistry  # noqa: E402
from ha_interface import HomeAssistantInterface  # noqa: E402
from integration_contract import StandardCommand, MessageType  # noqa: E402
from adapters.roborock_b01 import RoborockB01Adapter  # noqa: E402

DEVICE_ID = "q10_ss09_pf"
VALID_USER = "synthetic-mqtt-user"
VALID_PASS = "synthetic-mqtt-pass"
TOPIC_O = "rr/m/o/demo-client-id"  # device publishes status here
TOPIC_I = "rr/m/i/demo-client-id"  # device subscribes for commands here

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def make_server_ssl_context(cert_dir: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_dir / "server_cert.pem"), str(cert_dir / "server_key.pem"))
    return ctx


def make_client_ssl_context(cert_dir: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(str(cert_dir / "ca_cert.pem"))
    return ctx  # cert has a 127.0.0.1 IP SAN, so default hostname verification just works


async def main():
    cert_dir = Path(tempfile.mkdtemp(prefix="q10_test_certs_"))
    gen_cert(cert_dir)
    print(f"[setup] generated self-signed test CA+cert (with 127.0.0.1 SAN) in {cert_dir}")

    broker = MinimalMqttBroker(valid_credentials={VALID_USER: VALID_PASS})
    broker_server = await broker.start("127.0.0.1", 0, ssl_context=make_server_ssl_context(cert_dir))
    broker_port = broker_server.sockets[0].getsockname()[1]
    print(f"[setup] minimal MQTT-TLS broker listening on 127.0.0.1:{broker_port}")

    events = []

    async def sink(ev):
        events.append(ev)

    policy = DevicePolicy(
        device_id=DEVICE_ID,
        match_src_ip="127.0.0.1",
        cloud_host="127.0.0.1", cloud_port=broker_port,
        local_host="127.0.0.1", local_port=broker_port,
        prefer_local=True,
    )
    router = ApplianceRouter(PolicyTable([policy]), RouterConfig(health_check_timeout=2.0), event_sink=sink)

    async def router_handler(reader, writer):
        peer = writer.get_extra_info("peername")
        await router.handle_connection(
            reader, writer, src_ip="127.0.0.1", src_port=peer[1] if peer else 0,
            src_mac="02:00:00:00:00:01", dst_ip="203.0.113.50", dst_port=8883,
        )

    router_server = await asyncio.start_server(router_handler, "127.0.0.1", 0)
    router_port = router_server.sockets[0].getsockname()[1]
    print(f"[setup] router listening on 127.0.0.1:{router_port}, relaying to the broker")

    registry = AdapterRegistry()
    registry.register(RoborockB01Adapter())
    iface = HomeAssistantInterface(registry)
    iface.register_device(DEVICE_ID, manufacturer="roborock", protocol_family="B01")

    received_events = []

    def ha_consumer(msg):
        if msg.message_type == MessageType.DEVICE_EVENT:
            received_events.append(msg)
            print(f"[HA] standardized event: {msg.payload.get('kind')} state={msg.payload.get('state')} battery={msg.payload.get('battery')}")

    iface.subscribe(ha_consumer)

    client_ctx = make_client_ssl_context(cert_dir)

    # --- translator-side client: connects directly to the broker, standing
    # in for "the legitimate local endpoint" per the architecture doc ---
    async with aiomqtt.Client(
        "127.0.0.1", port=broker_port, identifier="translator-side",
        username=VALID_USER, password=VALID_PASS, tls_context=client_ctx,
    ) as translator_client:
        await translator_client.subscribe(TOPIC_O)
        check("translator client: connected + subscribed over real MQTT-TLS", True)

        # --- device-side client: connects THROUGH the router ---
        async with aiomqtt.Client(
            "127.0.0.1", port=router_port, identifier="demo-client-id",
            username=VALID_USER, password=VALID_PASS, tls_context=client_ctx,
        ) as device_client:
            check("device client: connected through router over real MQTT-TLS (router never terminated TLS)", True)
            await device_client.subscribe(TOPIC_I)
            await asyncio.sleep(0.1)
            check("router: recorded connection_opened for this session", any(e["message_type"] == "connection_opened" for e in events))

            synthetic_status = json.dumps({"dps": {"121": {"state": "charging", "battery": 100}}}).encode()
            await device_client.publish(TOPIC_O, synthetic_status)

            # translator receives the status, feeds the adapter, issues PAUSE back
            async def translator_loop():
                async for message in translator_client.messages:
                    await iface.ingest_inbound(DEVICE_ID, str(message.topic), message.payload)
                    topic, payload = iface.send_command(DEVICE_ID, StandardCommand.PAUSE)
                    await translator_client.publish(topic.replace("{client-id}", "demo-client-id"), payload)
                    return

            await asyncio.wait_for(translator_loop(), timeout=5)

            got_command = False
            dps = {}
            async def device_loop():
                nonlocal got_command, dps
                async for message in device_client.messages:
                    dps = json.loads(message.payload)["dps"]
                    got_command = True
                    return

            await asyncio.wait_for(device_loop(), timeout=5)
            check("round trip: device received a command back through the router", got_command)
            check("round trip: command is the correct DP 204 (PAUSE)", "204" in dps)
            check("translator: HA layer received the standardized event", len(received_events) == 1)
            if received_events:
                check("translator: standardized event has correct battery value", received_events[0].payload.get("battery") == 100)

    # --- invalid credentials, checked at the real MQTT protocol level ---
    rejected = False
    try:
        async with aiomqtt.Client(
            "127.0.0.1", port=broker_port, identifier="bad-creds-client",
            username="wrong-user", password="wrong-pass", tls_context=client_ctx,
        ):
            pass
    except aiomqtt.MqttError:
        rejected = True
    check("invalid credentials: broker rejects at real CONNACK level (not accepted)", rejected)

    router_server.close()
    broker_server.close()
    await asyncio.sleep(0.1)

    print()
    passed = sum(1 for _, ok in results if ok)
    print(f"TOTAL: {passed}/{len(results)} checks passed")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
