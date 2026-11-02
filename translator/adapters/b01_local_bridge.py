"""B01 Q10 local bridge — connects python-roborock's EXISTING B01 encoder/decoder to a
local MQTT broker (the device-facing local_roborock_server broker role), with request
correlation, timeout, and error handling.

This does NOT reimplement the B01 protocol: it uses roborock.protocols.b01_q10_protocol's
encode_mqtt_payload / decode_rpc_response and the roborock.data.b01_q10 code map. It is the
thin HA-side publish/receive adapter identified as the missing piece in SESSION8.

Correlation model: the Q10 B01 MQTT envelope ({"dps": {code: params}}) has no per-request id,
so a command is correlated to the device reply by the Data Point (DP) code expected in the
response (e.g. START_CLEAN -> state DP 121; FAN_LEVEL -> DP 123; REQUEST_DPS -> any/full dump).
Errors in one inbound message never tear down the listener; timeouts raise B01CommandTimeout.
"""
from __future__ import annotations
import asyncio, logging
from typing import Any

from roborock.roborock_message import RoborockMessage, RoborockMessageProtocol
from roborock.protocols.b01_q10_protocol import encode_mqtt_payload, decode_rpc_response
from roborock.data.b01_q10.b01_q10_code_mappings import B01_Q10_DP

_LOGGER = logging.getLogger(__name__)
B01 = b"B01"


class B01CommandTimeout(TimeoutError):
    """Raised when no correlated response arrives for a command within the timeout."""


class B01LocalBridge:
    """HA-side adapter over an aiomqtt client connected to the local broker."""

    def __init__(self, client: Any, cmd_topic: str, status_topic: str) -> None:
        self._client = client
        self._cmd_topic = cmd_topic
        self._status_topic = status_topic
        # pending waiters: expected DP code (or None=any) -> future resolved with decoded dict
        self._waiters: list[tuple[int | None, asyncio.Future]] = []
        self._listener: asyncio.Task | None = None
        self.decode_errors = 0  # observable: malformed inbound messages survived
        # The Q10 B01 envelope carries no echoed request id, so DP-code correlation alone
        # cannot disambiguate two in-flight commands that expect the SAME DP (e.g. START_CLEAN
        # and STOP both reply on DP 121). Serialize commands to guarantee at most one waiter
        # is live at a time, so a matching reply can only belong to the current command.
        self._send_lock = asyncio.Lock()

    async def start(self) -> None:
        await self._client.subscribe(self._status_topic)
        self._listener = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        async for msg in self._client.messages:
            try:
                decoded = decode_rpc_response(RoborockMessage(
                    protocol=RoborockMessageProtocol.RPC_RESPONSE, version=B01,
                    payload=bytes(msg.payload)))
            except Exception as ex:  # malformed/garbage inbound must not kill the listener
                self.decode_errors += 1
                _LOGGER.debug("B01LocalBridge: dropped undecodable inbound message: %s", ex)
                continue
            codes = {k.code for k in decoded}
            for i, (want, fut) in enumerate(list(self._waiters)):
                if fut.done():
                    continue
                if want is None or want in codes:
                    fut.set_result(decoded)
                    self._waiters.remove((want, fut))

    async def send_command(self, command: B01_Q10_DP, params: Any = None, *,
                           expect_dp: int | None = None, timeout: float = 5.0) -> dict:
        """Encode + publish a command; await the correlated decoded response.

        expect_dp: the DP code the response must carry to be matched to this command
        (None = accept the next decoded response). Raises B01CommandTimeout on timeout.
        """
        async with self._send_lock:  # serialize: at most one live waiter at a time
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._waiters.append((expect_dp, fut))
            rmsg = encode_mqtt_payload(command, params)
            await self._client.publish(self._cmd_topic, rmsg.payload)
            try:
                return await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError as ex:
                if (expect_dp, fut) in self._waiters:
                    self._waiters.remove((expect_dp, fut))
                raise B01CommandTimeout(
                    f"no response carrying DP {expect_dp} within {timeout}s for {command.name}") from ex

    async def aclose(self) -> None:
        if self._listener:
            self._listener.cancel()
            try:
                await self._listener
            except asyncio.CancelledError:
                pass
