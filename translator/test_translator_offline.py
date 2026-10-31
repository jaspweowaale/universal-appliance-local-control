"""Offline validation of Project 2 using synthetic fixtures only - same
status/start/pause/dock cases already proven in Phase A5, now exercised
through the adapter/registry/HA-interface layers instead of called directly."""
import asyncio
import json
import sys

from adapters.roborock_b01 import RoborockB01Adapter
from credential_store import CredentialStore
from integration_contract import MessageType, StandardCommand, StandardEventKind
from registry import AdapterRegistry
from ha_interface import DeviceNotRegistered, HomeAssistantInterface

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


async def main():
    registry = AdapterRegistry()
    registry.register(RoborockB01Adapter())
    iface = HomeAssistantInterface(registry)

    # --- Device isolation: using before registering must fail closed ---
    try:
        iface.send_command("unregistered_device", StandardCommand.START)
        check("unregistered device: rejected", False)
    except DeviceNotRegistered:
        check("unregistered device: rejected", True)

    iface.register_device("q10_ss09_pf", manufacturer="roborock", protocol_family="B01")

    received = []
    iface.subscribe(lambda msg: received.append(msg))

    # --- Inbound: synthetic status+battery payload ---
    synthetic_payload = json.dumps({"dps": {"121": {"state": "charging", "battery": 100}}}).encode()
    msg = await iface.ingest_inbound("q10_ss09_pf", "rr/m/o/synthetic-client-id", synthetic_payload)
    check("inbound: produces DEVICE_EVENT", msg.message_type == MessageType.DEVICE_EVENT)
    check("inbound: standardized battery kind detected", msg.payload.get("kind") == StandardEventKind.BATTERY.value)
    check("inbound: battery value preserved", msg.payload.get("battery") == 100)
    check("subscriber received the same event", received and received[-1] is msg)

    # --- Inbound: malformed payload produces ADAPTER_ERROR, not a crash ---
    bad_msg = await iface.ingest_inbound("q10_ss09_pf", "rr/m/o/synthetic-client-id", b"not json")
    check("inbound malformed: produces ADAPTER_ERROR not a crash", bad_msg.message_type == MessageType.ADAPTER_ERROR)

    # --- Outbound: all four core commands build without error ---
    for cmd in (StandardCommand.GET_STATUS, StandardCommand.START, StandardCommand.PAUSE, StandardCommand.DOCK):
        topic, payload = iface.send_command("q10_ss09_pf", cmd)
        dps = json.loads(payload)["dps"]
        check(f"outbound {cmd.value}: produces non-empty dps payload", len(dps) == 1)

    # --- Outbound: unsupported command raises cleanly ---
    try:
        iface.send_command("q10_ss09_pf", StandardCommand.GET_MAP)
        check("outbound GET_MAP: raises NotImplementedError (map data not yet supported)", False)
    except NotImplementedError:
        check("outbound GET_MAP: raises NotImplementedError (map data not yet supported)", True)

    # --- Credential isolation: cannot mix manufacturers under one device_id ---
    store = CredentialStore()
    store.put("q10_ss09_pf", "roborock", "duid", "synthetic-duid-value")
    store.put("q10_ss09_pf", "roborock", "localKey", "synthetic-localkey-value")
    try:
        store.put("q10_ss09_pf", "some_other_vendor", "secret", "x")
        check("credential store: refuses to mix manufacturers under one device_id", False)
    except ValueError:
        check("credential store: refuses to mix manufacturers under one device_id", True)
    inventory = store.field_inventory("q10_ss09_pf")
    check("credential inventory: reports field presence without exposing values", inventory == {"duid": True, "localKey": True})

    # --- Redaction: StandardMessage.redacted() strips secret-shaped keys ---
    from integration_contract import StandardMessage, Direction, MessageType as MT
    sensitive = StandardMessage(
        device_id="q10_ss09_pf", protocol_adapter="roborock_b01", direction=Direction.OUTBOUND,
        message_type=MT.DEVICE_COMMAND, payload={"command": "pause", "localkey": "should-not-appear", "nested": {"token": "should-not-appear-either"}},
    )
    red = sensitive.redacted()
    dumped = json.dumps(red)
    check("redaction: top-level secret key scrubbed", "should-not-appear" not in dumped and red["payload"]["localkey"] == "<redacted>")
    check("redaction: nested secret key scrubbed", red["payload"]["nested"]["token"] == "<redacted>")

    print()
    passed = sum(1 for _, ok in results if ok)
    print(f"TOTAL: {passed}/{len(results)} checks passed")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
