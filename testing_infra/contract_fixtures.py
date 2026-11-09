"""Shared, language-neutral contract fixtures for UALC device adapters.

Every frame in this module is **SYNTHETIC**. It is produced by the encoder
below from the documented field layout, not captured from a physical
appliance. That makes these fixtures excellent at proving a decoder is
self-consistent and completely useless as evidence that a real device emits
these bytes. Both facts matter; do not cite the second as the first.

A contributor who supplies *real sanitized captures* for a model upgrades its
support level from DECODED to CAPTURED. See
docs/contributing/DEVICE_CONTRIBUTION.md.

The same case list is executed against:
  * the Level-1 declarative profile  (devices/lg/AIR_910604_WW.json)
  * the Level-2 Lua handler          (plugins/lua/examples/lg_air_910604_ww/)

and both must agree. That equivalence is the whole point: it demonstrates
that the plugin contract is genuinely language-neutral rather than Python
with a Lua afterthought.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Tag constants, mirroring devices/lg/AIR_910604_WW.json.
TAG_POWER = 0x1F7
TAG_MODE = 0x1F9
TAG_FAN = 0x1FA
TAG_PM1 = 0x333
TAG_PM25 = 0x334
TAG_PM10 = 0x335
TAG_AQI = 0x240
TAG_ODOR = 0x241
TAG_ERROR = 0x221
TAG_FILTER_REMAIN = 0x355
TAG_FILTER_LIFE = 0x356

DIALECT_A7 = 0xA7
DIALECT_87 = 0x87


def encode_tlv(tag: int, value: int) -> bytes:
    """Inverse of the decoder in translator/profiles.py.

    Width is chosen by magnitude, exactly as the documented format does:
    values below 0x10 ride in the low nibble of the second byte; otherwise
    1, 2 or 3 big-endian bytes follow.
    """
    if not 0 <= tag <= 0x3FF:
        raise ValueError(f"tag {tag:#x} outside the 10-bit tag space")
    if value < 0:
        raise ValueError("TLV values are unsigned")
    t0 = (tag >> 2) & 0xFF
    tl = (tag & 0x03) << 6
    if value < 0x10:
        return bytes([t0, tl | value])
    if value < 0x100:
        return bytes([t0, tl | 0x10, value])
    if value < 0x10000:
        return bytes([t0, tl | 0x20, (value >> 8) & 0xFF, value & 0xFF])
    if value < 0x1000000:
        return bytes([t0, tl | 0x30, (value >> 16) & 0xFF,
                      (value >> 8) & 0xFF, value & 0xFF])
    raise ValueError("value too large for this encoding")


def build_frame(elements: list[tuple[int, int]], dialect: int = DIALECT_A7,
                envelope_prefix: bytes = b"\x04\x00\x00\x00",
                trailer: bytes = b"\x00\x00") -> bytes:
    """Assemble a full A7-style frame around an encoded TLV body.

    Layout (matching the profile parameters):
        [0:2]   opaque leading header
        [2:6]   envelope prefix 04 00 00 00
        [6]     dialect marker (0xA7)
        [7:11]  opaque sub-header
        [11:-2] TLV body
        [-2:]   16-bit trailer (a real device puts a checksum here; we do not
                compute one, and no decoder in this repo validates it)
    """
    body = b"".join(encode_tlv(tag, value) for tag, value in elements)
    return (b"\x00\x00" + envelope_prefix + bytes([dialect])
            + b"\x00\x00\x00\x00" + body + trailer)


def build_raw_body_frame(body: bytes, dialect: int = DIALECT_A7) -> bytes:
    """Same envelope, but with a caller-supplied (possibly malformed) body."""
    return (b"\x00\x00" + b"\x04\x00\x00\x00" + bytes([dialect])
            + b"\x00\x00\x00\x00" + body + b"\x00\x00")


@dataclass
class ContractCase:
    """One language-neutral expectation.

    `expect_state` is compared exactly against the adapter's decoded state,
    so a decoder that invents an extra key fails rather than passing quietly.
    """
    name: str
    payload: bytes
    expect_error_code: str | None = None
    expect_state: dict[str, Any] | None = None
    expect_partial: bool | None = None
    rationale: str = ""


FULL_STATE_ELEMENTS = [
    (TAG_POWER, 1),
    (TAG_MODE, 16),
    (TAG_FAN, 8),
    (TAG_PM1, 8),
    (TAG_PM25, 10),
    (TAG_PM10, 14),
    (TAG_AQI, 2),
    (TAG_ODOR, 1),
]


def contract_cases() -> list[ContractCase]:
    return [
        ContractCase(
            name="full_state_frame",
            payload=build_frame(FULL_STATE_ELEMENTS),
            expect_state={
                "power": "on", "mode": "auto", "fan_speed": "auto",
                "pm1": 8, "pm25": 10, "pm10": 14,
                "air_quality_index": 2, "odor_index": 1,
            },
            expect_partial=False,
            rationale="Eight known tags decode to eight named fields and the "
                      "frame is recognised as a full state, not a delta.",
        ),
        ContractCase(
            name="single_tag_delta_is_partial",
            payload=build_frame([(TAG_POWER, 0)]),
            expect_state={"power": "off"},
            expect_partial=True,
            rationale="A change notification must be flagged partial so the "
                      "host does not treat absent fields as cleared. This is "
                      "the property that stops a delta frame from wiping "
                      "known state.",
        ),
        ContractCase(
            name="two_byte_value_width",
            payload=build_frame([(TAG_FILTER_REMAIN, 1234),
                                 (TAG_FILTER_LIFE, 4000)]),
            expect_state={"filter_remaining_hours": 1234,
                          "filter_life_hours": 4000},
            expect_partial=True,
            rationale="Values >= 0x100 use the 2-byte big-endian width.",
        ),
        ContractCase(
            name="three_byte_value_width",
            payload=build_frame([(TAG_FILTER_LIFE, 70000)]),
            expect_state={"filter_life_hours": 70000},
            expect_partial=True,
            rationale="Values >= 0x10000 use the 3-byte width. Guards the "
                      "shift arithmetic in both implementations.",
        ),
        ContractCase(
            name="out_of_domain_enum_is_reported_not_coerced",
            payload=build_frame([(TAG_MODE, 99)]),
            expect_state={"mode": "unknown", "mode_raw": 99},
            expect_partial=True,
            rationale="An enum value outside the documented domain is a "
                      "finding about the appliance. Silently clamping it to "
                      "a known mode would manufacture false confidence.",
        ),
        ContractCase(
            name="out_of_domain_power_is_reported",
            payload=build_frame([(TAG_POWER, 2)]),
            expect_state={"power": "unknown", "power_raw": 2},
            expect_partial=True,
            rationale="Regression guard: a truthiness test would call this "
                      "'on'. Both implementations must enumerate {0,1}.",
        ),
        ContractCase(
            name="unknown_tag_counted_not_fatal",
            payload=build_frame([(TAG_POWER, 1), (0x3FF, 5)]),
            expect_state={"power": "on", "unknown_tag_count": 1},
            expect_partial=True,
            rationale="An unrecognised tag must not discard the whole frame; "
                      "it is counted so a contributor can see there is more "
                      "to map.",
        ),
        ContractCase(
            name="wrong_dialect_rejected_distinctly",
            payload=build_frame([(TAG_POWER, 1)], dialect=DIALECT_87),
            expect_error_code="UNSUPPORTED_PROTOCOL_VERSION",
            rationale="0x87 is another appliance class. Reporting it as a "
                      "protocol-version problem rather than a malformed "
                      "frame keeps 'we cannot read this' separate from "
                      "'this is corrupt'.",
        ),
        ContractCase(
            name="bad_envelope_prefix_rejected",
            payload=(b"\x00\x00" + b"\x05\x00\x00\x00" + bytes([DIALECT_A7])
                     + b"\x00\x00\x00\x00"
                     + encode_tlv(TAG_POWER, 1) + b"\x00\x00"),
            expect_error_code="MALFORMED_FRAME",
            rationale="The fixed 04 00 00 00 prefix is the cheapest "
                      "structural check available.",
        ),
        ContractCase(
            name="short_frame_rejected",
            payload=b"\x00\x00\x04\x00\x00\x00\xa7",
            expect_error_code="MALFORMED_FRAME",
            rationale="Too short to contain a body. Must not index past the "
                      "end of the buffer.",
        ),
        ContractCase(
            name="empty_body_rejected",
            payload=build_raw_body_frame(b""),
            expect_error_code="MALFORMED_FRAME",
            rationale="A frame with a valid envelope but no TLV elements "
                      "carries no state and is not a successful decode.",
        ),
        ContractCase(
            name="truncated_trailing_element_flagged",
            # One complete element, then a single orphan byte.
            payload=build_raw_body_frame(encode_tlv(TAG_POWER, 1) + b"\x7f"),
            expect_state={"power": "on", "frame_truncated": True},
            expect_partial=True,
            rationale="Decode what is intact, flag the truncation, do not "
                      "throw away a frame that was otherwise fine.",
        ),
        ContractCase(
            name="truncated_multibyte_element_flagged",
            # Declares a 2-byte value but supplies only one byte.
            payload=build_raw_body_frame(
                encode_tlv(TAG_POWER, 1) + bytes([0x7F, 0x20, 0x01])),
            expect_state={"power": "on", "frame_truncated": True},
            expect_partial=True,
            rationale="The length selector must be validated against the "
                      "remaining buffer, not trusted.",
        ),
    ]
