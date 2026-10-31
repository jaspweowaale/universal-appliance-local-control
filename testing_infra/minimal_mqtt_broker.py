"""
Minimal MQTT 3.1.1 broker, QoS 0 only, exact-topic matching only. This is
test infrastructure, not part of either production project - it exists
solely so our integration test exercises real MQTT wire framing (CONNECT/
CONNACK/SUBSCRIBE/SUBACK/PUBLISH/PINGREQ/PINGRESP) under real TLS, instead
of raw JSON bytes over plain TCP like the earlier demo did.

No new dependency was installed to build this - mosquitto is not available
and was not installed without approval; this exists specifically so the
"no system-wide installs" restriction didn't block getting real MQTT
framing into the integration test.
"""
from __future__ import annotations

import asyncio
import ssl
import struct


def _encode_remaining_length(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n % 128
        n //= 128
        if n > 0:
            byte |= 0x80
        out.append(byte)
        if n == 0:
            break
    return bytes(out)


async def _read_remaining_length(reader: asyncio.StreamReader) -> int:
    multiplier = 1
    value = 0
    while True:
        b = await reader.readexactly(1)
        byte = b[0]
        value += (byte & 0x7F) * multiplier
        if (byte & 0x80) == 0:
            break
        multiplier *= 128
    return value


def _encode_string(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


class MinimalMqttBroker:
    def __init__(self, valid_credentials: dict[str, str] | None = None):
        """valid_credentials: {username: password}. If None, any CONNECT is accepted
        (auth disabled). If set, a username must be present and match."""
        self.valid_credentials = valid_credentials
        self._subscriptions: dict[str, set[asyncio.StreamWriter]] = {}
        self._writer_to_client_id: dict[asyncio.StreamWriter, str] = {}
        self.connect_log: list[dict] = []
        self.publish_log: list[dict] = []

    async def start(self, host: str, port: int, ssl_context: ssl.SSLContext | None = None):
        server = await asyncio.start_server(self._handle_client, host, port, ssl=ssl_context)
        return server

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        client_id = None
        try:
            while True:
                header = await reader.readexactly(1)
                packet_type = header[0] >> 4
                remaining = await _read_remaining_length(reader)
                body = await reader.readexactly(remaining) if remaining else b""

                if packet_type == 1:  # CONNECT
                    client_id, ok = self._parse_connect(body)
                    self._writer_to_client_id[writer] = client_id
                    self.connect_log.append({"client_id": client_id, "accepted": ok})
                    writer.write(bytes([0x20, 0x02, 0x00, 0x00 if ok else 0x04]))
                    await writer.drain()
                    if not ok:
                        writer.close()
                        return

                elif packet_type == 8:  # SUBSCRIBE
                    packet_id = body[0:2]
                    pos = 2
                    return_codes = []
                    while pos < len(body):
                        topic_len = struct.unpack(">H", body[pos:pos + 2])[0]
                        pos += 2
                        topic = body[pos:pos + topic_len].decode()
                        pos += topic_len
                        qos = body[pos]
                        pos += 1
                        self._subscriptions.setdefault(topic, set()).add(writer)
                        return_codes.append(0x00)
                    suback = bytes([0x90]) + _encode_remaining_length(2 + len(return_codes)) + packet_id + bytes(return_codes)
                    writer.write(suback)
                    await writer.drain()

                elif packet_type == 3:  # PUBLISH (QoS 0 only, no packet id)
                    topic_len = struct.unpack(">H", body[0:2])[0]
                    topic = body[2:2 + topic_len].decode()
                    payload = body[2 + topic_len:]
                    self.publish_log.append({"topic": topic, "from_client_id": client_id, "bytes": len(payload)})
                    subs = self._subscriptions.get(topic, set())
                    out_packet = bytes([0x30]) + _encode_remaining_length(2 + topic_len + len(payload)) + body
                    for sub_writer in list(subs):
                        if sub_writer is writer:
                            continue  # never echo back to the publisher itself
                        try:
                            sub_writer.write(out_packet)
                            await sub_writer.drain()
                        except Exception:
                            subs.discard(sub_writer)

                elif packet_type == 12:  # PINGREQ
                    writer.write(bytes([0xD0, 0x00]))
                    await writer.drain()

                elif packet_type == 14:  # DISCONNECT
                    writer.close()
                    return

                else:
                    # Unknown/unsupported packet type for this minimal broker.
                    writer.close()
                    return
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            for subs in self._subscriptions.values():
                subs.discard(writer)
            self._writer_to_client_id.pop(writer, None)
            try:
                writer.close()
            except Exception:
                pass

    def _parse_connect(self, body: bytes) -> tuple[str, bool]:
        pos = 0
        proto_name_len = struct.unpack(">H", body[pos:pos + 2])[0]
        pos += 2 + proto_name_len  # skip "MQTT"
        pos += 1  # protocol level
        connect_flags = body[pos]
        pos += 1
        pos += 2  # keepalive
        client_id_len = struct.unpack(">H", body[pos:pos + 2])[0]
        pos += 2
        client_id = body[pos:pos + client_id_len].decode()
        pos += client_id_len

        has_will = bool(connect_flags & 0x04)
        has_username = bool(connect_flags & 0x80)
        has_password = bool(connect_flags & 0x40)

        if has_will:
            will_topic_len = struct.unpack(">H", body[pos:pos + 2])[0]
            pos += 2 + will_topic_len
            will_msg_len = struct.unpack(">H", body[pos:pos + 2])[0]
            pos += 2 + will_msg_len

        username = None
        password = None
        if has_username:
            u_len = struct.unpack(">H", body[pos:pos + 2])[0]
            pos += 2
            username = body[pos:pos + u_len].decode()
            pos += u_len
        if has_password:
            p_len = struct.unpack(">H", body[pos:pos + 2])[0]
            pos += 2
            password = body[pos:pos + p_len].decode()
            pos += p_len

        if self.valid_credentials is None:
            return client_id, True
        ok = username is not None and self.valid_credentials.get(username) == password
        return client_id, ok
