"""Cloud-free B01 Q10 integration test for universal-appliance-local-control.

Proves, with no manufacturer cloud contacted (localhost MQTT-TLS broker only):

  encode_mqtt_payload(cmd)  --MQTT/TLS-->  local broker  --> device model
     (python-roborock)                     (this repo)      (Q10VacuumSimulator)
        <-- decode_rpc_response <-- status <--/

Reuses the library's EXISTING B01 encoder/decoder + its Q10 device simulator (no new
encoder is written here) and this repo's testing_infra broker + self-signed cert.

Scope: validates the command/response path + local-broker wiring over real MQTT framing
and TLS against python-roborock's device model. It does NOT prove a physical ss09 trusts
this broker/cert or speaks this exactly; that requires the device (see docs/ROBOROCK_Q10.md).
"""
import asyncio, ssl, sys, tempfile, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # testing_infra
if "aioresponses" not in sys.modules:  # library test dep, unused by the simulator
    _m = types.ModuleType("aioresponses"); _m.CallbackResult = object; _m.aioresponses = object
    sys.modules["aioresponses"] = _m

import aiomqtt
from gen_test_cert import generate as gen_cert
from minimal_mqtt_broker import MinimalMqttBroker
from roborock.roborock_message import RoborockMessage, RoborockMessageProtocol
from roborock.protocols.b01_q10_protocol import encode_mqtt_payload, decode_rpc_response
from roborock.data.b01_q10.b01_q10_code_mappings import B01_Q10_DP
from roborock.testing.b01_q10_simulator import Q10VacuumSimulator

USER, PW = "synthetic-mqtt-user", "synthetic-mqtt-pass"
CMD_TOPIC, STATUS_TOPIC = "rr/m/i/q10-ss09", "rr/m/o/q10-ss09"
results = []
def check(n, c): results.append((n, bool(c))); print(f"[{'PASS' if c else 'FAIL'}] {n}")
def dp(code): return B01_Q10_DP.from_code_optional(code)
def _sctx(d): c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); c.load_cert_chain(str(d/"server_cert.pem"), str(d/"server_key.pem")); return c
def _cctx(d): c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c.load_verify_locations(str(d/"ca_cert.pem")); return c

async def main():
    cert = Path(tempfile.mkdtemp(prefix="b01cf_")); gen_cert(cert)
    broker = MinimalMqttBroker(valid_credentials={USER: PW})
    srv = await broker.start("127.0.0.1", 0, ssl_context=_sctx(cert))
    port = srv.sockets[0].getsockname()[1]
    print(f"[setup] local MQTT-TLS broker 127.0.0.1:{port} (no cloud)")
    sim = Q10VacuumSimulator(duid="q10-ss09"); cctx = _cctx(cert)

    async def bridge(ready):
        async with aiomqtt.Client("127.0.0.1", port=port, identifier="device-ss09",
                                  username=USER, password=PW, tls_context=cctx) as dev:
            await dev.subscribe(CMD_TOPIC); ready.set()
            async for msg in dev.messages:
                out = []
                sim.mqtt_channel.notify_subscribers = lambda m: out.append(m.payload)
                await sim._handle_publish(RoborockMessage(
                    protocol=RoborockMessageProtocol.RPC_REQUEST, version=b"B01",
                    payload=bytes(msg.payload)), sim.mqtt_channel)
                for p in out: await dev.publish(STATUS_TOPIC, p)

    ready = asyncio.Event(); t = asyncio.create_task(bridge(ready)); await ready.wait()
    async with aiomqtt.Client("127.0.0.1", port=port, identifier="ha-client",
                              username=USER, password=PW, tls_context=cctx) as ha:
        await ha.subscribe(STATUS_TOPIC); await asyncio.sleep(0.1)
        async def rpc(code, params):
            await ha.publish(CMD_TOPIC, encode_mqtt_payload(dp(code), params).payload)
            async def one():
                async for m in ha.messages:
                    return decode_rpc_response(RoborockMessage(
                        protocol=RoborockMessageProtocol.RPC_RESPONSE, version=b"B01",
                        payload=bytes(m.payload)))
            return await asyncio.wait_for(one(), timeout=5)
        d = await rpc(102, None)
        check("REQUEST_DPS -> decoded typed status over local broker", bool(d) and len(d) > 3)
        check("status includes device STATE dp(121)", any(k.code == 121 for k in d))
        st = lambda dd: {k.code: v for k, v in dd.items()}.get(121)
        check("START_CLEAN -> CLEANING(121=5)", st(await rpc(201, 1)) == 5)
        check("PAUSE -> PAUSED(121=10)", st(await rpc(204, None)) == 10)
        check("STOP -> IDLE(121=3)", st(await rpc(206, None)) == 3)
    t.cancel(); srv.close()
    try: await asyncio.wait_for(t, timeout=1)
    except (asyncio.CancelledError, asyncio.TimeoutError): pass
    p = sum(1 for _, ok in results if ok)
    print(f"\nTOTAL: {p}/{len(results)} cloud-free checks passed")
    sys.exit(0 if p == len(results) else 1)

if __name__ == "__main__":
    asyncio.run(main())
