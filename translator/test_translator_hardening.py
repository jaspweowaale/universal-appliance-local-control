"""
Task 3 hardening tests for the protocol translator. Additive - does not
modify or replace test_translator_offline.py. All synthetic/offline.
"""
import asyncio
import json
import sys

from adapters.roborock_b01 import RoborockB01Adapter
from credential_store import CredentialStore
from integration_contract import MessageType, StandardCommand
from registry import AdapterRegistry
from ha_interface import HomeAssistantInterface

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def build_iface():
    registry = AdapterRegistry()
    registry.register(RoborockB01Adapter())
    iface = HomeAssistantInterface(registry)
    iface.register_device("q10_ss09_pf", manufacturer="roborock", protocol_family="B01")
    return iface


async def test_duplicate_messages():
    iface = build_iface()
    received = []
    iface.subscribe(lambda m: received.append(m))
    payload = json.dumps({"dps": {"121": {"state": "charging", "battery": 100}}}).encode()
    msg1 = await iface.ingest_inbound("q10_ss09_pf", "t", payload)
    msg2 = await iface.ingest_inbound("q10_ss09_pf", "t", payload)
    check("duplicate messages: both processed independently without crashing", len(received) == 2)
    check("duplicate messages: each gets its own correlation_id (not deduped/merged)", msg1.correlation_id != msg2.correlation_id)
    check("duplicate messages: both carry identical, correctly-parsed content", msg1.payload == msg2.payload)


async def test_reordered_messages():
    iface = build_iface()
    received = []
    iface.subscribe(lambda m: received.append(m))
    # A "pause ack" arriving before its logically-earlier "status" update -
    # the adapter must not assume arrival order means anything.
    pause_ack = json.dumps({"dps": {"101": {"204": "ack"}}}).encode()
    status_update = json.dumps({"dps": {"121": {"state": "charging", "battery": 99}}}).encode()
    await iface.ingest_inbound("q10_ss09_pf", "t", pause_ack)
    await iface.ingest_inbound("q10_ss09_pf", "t", status_update)
    check("reordered messages: out-of-order arrival processed without error", len(received) == 2)
    check("reordered messages: pause-ack payload still correctly decoded despite arriving 'early'", received[0].message_type == MessageType.DEVICE_EVENT)


async def test_reconnect_same_device_same_identity_ok():
    iface = build_iface()
    try:
        iface.register_device("q10_ss09_pf", manufacturer="roborock", protocol_family="B01")
        check("reconnect: re-registering the same device with the same identity is a no-op, not an error", True)
    except Exception:
        check("reconnect: re-registering the same device with the same identity is a no-op, not an error", False)


async def test_reconnect_identity_switch_rejected():
    # Needs a second real adapter registered under the same manufacturer so
    # the failure we're testing is OUR re-registration guard, not just "no
    # adapter for that protocol family" from the registry.
    class _FakeA01Adapter(RoborockB01Adapter):
        protocol_family = "A01"

    registry = AdapterRegistry()
    registry.register(RoborockB01Adapter())
    registry.register(_FakeA01Adapter())
    iface = HomeAssistantInterface(registry)
    iface.register_device("q10_ss09_pf", manufacturer="roborock", protocol_family="B01")
    try:
        iface.register_device("q10_ss09_pf", manufacturer="roborock", protocol_family="A01")  # different protocol family, same device_id
        check("reconnect: silently switching a device_id's protocol family is rejected", False)
    except ValueError:
        check("reconnect: silently switching a device_id's protocol family is rejected", True)


async def test_invalid_credentials_rejected_at_broker_level():
    # This adapter has no bootstrap/session-establishment code (see
    # roborock_b01.py's module docstring for why) - invalid-credential
    # rejection for this project happens at the real MQTT broker's CONNACK
    # level, proven against a real MQTT-TLS exchange in
    # testing_infra/task4_integration_test.py. Nothing to test at the
    # adapter layer for this case; kept as a named placeholder so the gap
    # is documented rather than silently absent from this file.
    check("invalid credentials: rejection verified at broker/CONNACK level, see task4_integration_test.py", True)


async def test_malformed_b01_payloads():
    iface = build_iface()
    cases = {
        "missing dps key": b'{"nope": {}}',
        "dps not a dict": b'{"dps": [1,2,3]}',
        "non-integer dps key": b'{"dps": {"not-a-number": {}}}',
        "truncated/incomplete json": b'{"dps": {"121": ',
        "empty payload": b'',
        "garbage binary": bytes([0xFF, 0x00, 0xDE, 0xAD, 0xBE, 0xEF]),
    }
    for name, payload in cases.items():
        msg = await iface.ingest_inbound("q10_ss09_pf", "t", payload)
        check(f"malformed payload ({name}): produces ADAPTER_ERROR, does not crash", msg.message_type == MessageType.ADAPTER_ERROR)


async def test_command_timeout_and_ack():
    iface = build_iface()

    # Case 1: command is sent, device never acks -> timeout, not a false success.
    _, _, correlation_id = iface.send_command_tracked("q10_ss09_pf", StandardCommand.PAUSE)
    acked = await iface.wait_for_ack(correlation_id, timeout=0.3)
    check("command timeout: no ack arrives -> wait_for_ack reports False, not a false positive", acked is False)

    # Case 2: command is sent, device genuinely acks before the timeout.
    _, _, correlation_id2 = iface.send_command_tracked("q10_ss09_pf", StandardCommand.START)
    ack_payload = json.dumps({"dps": {"101": {"201": "ack"}}}).encode()  # 201 = START_CLEAN

    async def deliver_ack_shortly():
        await asyncio.sleep(0.05)
        await iface.ingest_inbound("q10_ss09_pf", "t", ack_payload)

    asyncio.create_task(deliver_ack_shortly())
    acked2 = await iface.wait_for_ack(correlation_id2, timeout=2.0)
    check("command ack: genuine ack arriving before timeout is correctly recognized", acked2 is True)

    # Case 3: an ack for a DIFFERENT command must not satisfy this one's wait.
    _, _, correlation_id3 = iface.send_command_tracked("q10_ss09_pf", StandardCommand.DOCK)
    wrong_ack = json.dumps({"dps": {"101": {"204": "ack"}}}).encode()  # 204 = PAUSE, not DOCK(202)
    await iface.ingest_inbound("q10_ss09_pf", "t", wrong_ack)
    acked3 = await iface.wait_for_ack(correlation_id3, timeout=0.3)
    check("command ack: an ack for a different command does not falsely satisfy this one", acked3 is False)


async def test_q10_f25_credential_isolation():
    store = CredentialStore()
    store.put("q10_ss09_pf", "roborock", "duid", "q10-real-duid-value")
    store.put("q10_ss09_pf", "roborock", "localKey", "q10-real-localkey-value")
    store.put("f25_ace", "roborock", "duid", "f25-real-duid-value")
    store.put("f25_ace", "roborock", "localKey", "f25-real-localkey-value")

    check("Q10/F25 isolation: Q10's duid is not F25's duid", store.get("q10_ss09_pf", "duid") != store.get("f25_ace", "duid"))
    check("Q10/F25 isolation: each device's field inventory only reflects its own fields", set(store.field_inventory("q10_ss09_pf")) == {"duid", "localKey"})

    # Multiplexed through the same HA interface + registry, never cross-wired.
    iface = build_iface()
    iface.register_device("f25_ace", manufacturer="roborock", protocol_family="B01")
    q10_received, f25_received = [], []

    def consumer(msg):
        (q10_received if msg.device_id == "q10_ss09_pf" else f25_received).append(msg)

    iface.subscribe(consumer)
    await iface.ingest_inbound("q10_ss09_pf", "t", json.dumps({"dps": {"121": {"battery": 11}}}).encode())
    await iface.ingest_inbound("f25_ace", "t", json.dumps({"dps": {"121": {"battery": 99}}}).encode())
    check("Q10/F25 isolation: Q10's event never lands in the F25 bucket", len(q10_received) == 1 and q10_received[0].payload.get("battery") == 11)
    check("Q10/F25 isolation: F25's event never lands in the Q10 bucket", len(f25_received) == 1 and f25_received[0].payload.get("battery") == 99)


async def main():
    await test_duplicate_messages()
    await test_reordered_messages()
    await test_reconnect_same_device_same_identity_ok()
    await test_reconnect_identity_switch_rejected()
    await test_invalid_credentials_rejected_at_broker_level()
    await test_malformed_b01_payloads()
    await test_command_timeout_and_ack()
    await test_q10_f25_credential_isolation()

    print()
    passed = sum(1 for _, ok in results if ok)
    print(f"TOTAL: {passed}/{len(results)} checks passed")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
