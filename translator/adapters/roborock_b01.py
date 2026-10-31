"""
Roborock B01 protocol adapter. Development test target: Roborock Q10 (model
string "roborock.vacuum.ss09"), firmware 03.13.00. Confirmed via direct TCP
service-discovery testing that this exact unit has no locally reachable
service on any of the standard candidate ports - this adapter's inbound/
outbound encode-decode path is proven correct, but nothing in this repo has
been shown to establish a real local session with this or any other B01
device. See ../../docs/ARCHITECTURE.md for the full status.

This adapter depends on `python-roborock` (GPL-3.0-only license - see
THIRD_PARTY_NOTICES.md) at runtime for its production, already-shipped
encode/decode logic (`roborock.protocols.b01_q10_protocol`,
`roborock.data.b01_q10.b01_q10_code_mappings`). That dependency is what the
real, cloud-connected Home Assistant Roborock integration also uses - high
confidence, not something this project wrote.

Intentionally NOT included here: a bootstrap/session-establishment helper.
An earlier development version of this adapter wrapped functions from
`Python-roborock/local_roborock_server` PR #96 (a still-open draft PR, as of
this writing paused pending a responsible-disclosure window on the bootstrap
mechanism it implements). This repo does not vendor or wrap that code, to
avoid republishing details of an unresolved disclosure process ahead of
upstream. If you need that functionality, go to the upstream PR directly and
judge its disclosure status for yourself - do not ask this project to point
you to a workaround.
"""
from __future__ import annotations

from roborock.data.b01_q10.b01_q10_code_mappings import B01_Q10_DP
from roborock.protocols.b01_q10_protocol import decode_rpc_response, encode_mqtt_payload
from roborock.roborock_message import RoborockMessage, RoborockMessageProtocol

from integration_contract import AuthStatus, Direction, MessageType, StandardCommand, StandardEventKind, StandardMessage
from base import ProtocolAdapter

_COMMAND_TO_DP = {
    StandardCommand.GET_STATUS: B01_Q10_DP.STATUS,
    StandardCommand.START: B01_Q10_DP.START_CLEAN,
    StandardCommand.PAUSE: B01_Q10_DP.PAUSE,
    StandardCommand.DOCK: B01_Q10_DP.START_BACK,
}


class RoborockB01Adapter(ProtocolAdapter):
    manufacturer = "roborock"
    protocol_family = "B01"

    # Kept as an explicit attribute (not hardcoded inline) so a sibling
    # adapter for a different B01 model can be added by subclassing, not by
    # copy-pasting this file.
    model = "roborock.vacuum.ss09"

    def supported_commands(self) -> set[StandardCommand]:
        return set(_COMMAND_TO_DP.keys())

    def parse_inbound(self, device_id: str, topic: str, payload: bytes) -> StandardMessage:
        try:
            msg = RoborockMessage(
                protocol=RoborockMessageProtocol.RPC_RESPONSE,
                version=b"B01",
                payload=payload,
            )
            decoded = decode_rpc_response(msg)
        except Exception as exc:
            return StandardMessage(
                device_id=device_id,
                protocol_adapter="roborock_b01",
                direction=Direction.INBOUND,
                message_type=MessageType.ADAPTER_ERROR,
                payload={"error": str(exc), "topic": topic},
                auth_status=AuthStatus.UNVERIFIED,
            )

        event_payload: dict = {}
        kind = StandardEventKind.STATUS
        if B01_Q10_DP.STATUS in decoded:
            status_dp = decoded[B01_Q10_DP.STATUS]
            if isinstance(status_dp, dict):
                event_payload.update(status_dp)
                if "battery" in status_dp:
                    kind = StandardEventKind.BATTERY

        return StandardMessage(
            device_id=device_id,
            protocol_adapter="roborock_b01",
            direction=Direction.INBOUND,
            message_type=MessageType.DEVICE_EVENT,
            payload={"kind": kind.value, **event_payload, "raw_dps": {dp.name: v for dp, v in decoded.items()}},
            auth_status=AuthStatus.UNVERIFIED,  # topic-level MQTT auth is the router's/broker's concern, not ours
        )

    def is_ack_for(self, command: StandardCommand, inbound_payload: dict) -> bool:
        dp = _COMMAND_TO_DP.get(command)
        if dp is None:
            return False
        return dp.name in inbound_payload.get("raw_dps", {})

    def build_outbound(self, device_id: str, command: StandardCommand) -> tuple[str, bytes]:
        dp = _COMMAND_TO_DP.get(command)
        if dp is None:
            raise NotImplementedError(f"RoborockB01Adapter does not support {command}")
        msg = encode_mqtt_payload(dp, {} if command != StandardCommand.GET_STATUS else None)
        topic = "rr/m/i/{client-id}"  # client-id filled in by the caller/session layer, not by this adapter
        return topic, msg.payload
