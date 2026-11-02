"""Test B01LocalBridge end-to-end over a real local MQTT-TLS broker + python-roborock's Q10
device model. Demonstrates: HA-side command interface -> B01 envelope -> local broker ->
simulated robot -> correlated decoded response, plus timeout and error handling. Cloud-free.
"""
import asyncio, ssl, sys, tempfile, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))                       # testing_infra
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "translator")) # adapters pkg parent
if "aioresponses" not in sys.modules:
    _m = types.ModuleType("aioresponses"); _m.CallbackResult = object; _m.aioresponses = object
    sys.modules["aioresponses"] = _m

import aiomqtt
from gen_test_cert import generate as gen_cert
from minimal_mqtt_broker import MinimalMqttBroker
from roborock.roborock_message import RoborockMessage, RoborockMessageProtocol
from roborock.data.b01_q10.b01_q10_code_mappings import B01_Q10_DP
from roborock.testing.b01_q10_simulator import Q10VacuumSimulator
from adapters.b01_local_bridge import B01LocalBridge, B01CommandTimeout

USER, PW = "synthetic-mqtt-user", "synthetic-mqtt-pass"
CMD, STATUS = "rr/m/i/q10-ss09", "rr/m/o/q10-ss09"
results = []
def check(n, c): results.append((n, bool(c))); print(f"[{'PASS' if c else 'FAIL'}] {n}")
def dp(code): return B01_Q10_DP.from_code_optional(code)
def _s(d): c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); c.load_cert_chain(str(d/"server_cert.pem"), str(d/"server_key.pem")); return c
def _c(d): c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); c.load_verify_locations(str(d/"ca_cert.pem")); return c

async def main():
    cert = Path(tempfile.mkdtemp(prefix="b01br_")); gen_cert(cert)
    broker = MinimalMqttBroker(valid_credentials={USER: PW})
    srv = await broker.start("127.0.0.1", 0, ssl_context=_s(cert))
    port = srv.sockets[0].getsockname()[1]
    sim = Q10VacuumSimulator(duid="q10-ss09"); cctx = _c(cert)

    async def device(ready):
        async with aiomqtt.Client("127.0.0.1", port=port, identifier="device-ss09",
                                  username=USER, password=PW, tls_context=cctx) as dev:
            await dev.subscribe(CMD); ready.set()
            # expose a malformed-injection hook for the error-handling check
            device.inject = lambda raw: asyncio.create_task(dev.publish(STATUS, raw))
            async for m in dev.messages:
                out = []
                sim.mqtt_channel.notify_subscribers = lambda msg: out.append(msg.payload)
                await sim._handle_publish(RoborockMessage(
                    protocol=RoborockMessageProtocol.RPC_REQUEST, version=b"B01",
                    payload=bytes(m.payload)), sim.mqtt_channel)
                for p in out: await dev.publish(STATUS, p)

    ready = asyncio.Event(); dtask = asyncio.create_task(device(ready)); await ready.wait()

    async with aiomqtt.Client("127.0.0.1", port=port, identifier="ha", username=USER,
                              password=PW, tls_context=cctx) as ha:
        bridge = B01LocalBridge(ha, CMD, STATUS)
        await bridge.start(); await asyncio.sleep(0.1)

        # 1) full HA-interface loop: command -> envelope -> broker -> robot -> correlated decode
        d = await bridge.send_command(dp(201), 1, expect_dp=121, timeout=5)   # START_CLEAN
        check("full loop: START_CLEAN correlated to STATE dp(121)=CLEANING(5)",
              {k.code: v for k, v in d.items()}.get(121) == 5)

        # 2) correlation: two different commands matched to their own DP replies
        fan = await bridge.send_command(dp(123), 2, expect_dp=123, timeout=5)  # FAN_LEVEL
        water = await bridge.send_command(dp(124), 1, expect_dp=124, timeout=5)  # WATER_LEVEL
        check("correlation: FAN_LEVEL reply carries dp(123)=2", {k.code: v for k, v in fan.items()}.get(123) == 2)
        check("correlation: WATER_LEVEL reply carries dp(124)=1", {k.code: v for k, v in water.items()}.get(124) == 1)

        # 3) REQUEST_DPS full dump (expect_dp=None accepts the next reply)
        dump = await bridge.send_command(dp(102), None, expect_dp=None, timeout=5)
        check("REQUEST_DPS full status dump decoded (>3 typed DPs)", len(dump) > 3)

        # 4) timeout: ask for a DP the device never returns -> B01CommandTimeout
        timed_out = False
        try:
            await bridge.send_command(dp(102), None, expect_dp=999, timeout=1.5)
        except B01CommandTimeout:
            timed_out = True
        check("timeout: unmatched DP raises B01CommandTimeout", timed_out)

        # 5) error handling: a malformed status message must not kill the listener
        before = bridge.decode_errors
        device.inject(b"this-is-not-valid-json"); await asyncio.sleep(0.3)
        check("error handling: malformed inbound counted + listener survived", bridge.decode_errors == before + 1)
        d2 = await bridge.send_command(dp(206), None, expect_dp=121, timeout=5)  # STOP still works after
        check("listener still works after malformed message (STOP->IDLE 121=3)",
              {k.code: v for k, v in d2.items()}.get(121) == 3)

        await bridge.aclose()
    dtask.cancel(); srv.close()
    try: await asyncio.wait_for(dtask, timeout=1)
    except (asyncio.CancelledError, asyncio.TimeoutError): pass
    p = sum(1 for _, ok in results if ok)
    print(f"\nTOTAL: {p}/{len(results)} checks passed (cloud-free)")
    sys.exit(0 if p == len(results) else 1)

if __name__ == "__main__":
    asyncio.run(main())
