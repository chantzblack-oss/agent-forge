"""Manual source packet support for books, blocked pages, and offline sources."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .schema import Source


DEFAULT_PACKET_PATH = Path(__file__).with_name("manual_source_packets.json")


def load_manual_source_packets(path: Path | None = None) -> dict[str, dict[str, Any]]:
    packet_path = path or DEFAULT_PACKET_PATH
    if not packet_path.exists():
        return {}
    with packet_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return {
        str(source_id): packet
        for source_id, packet in data.items()
        if isinstance(packet, dict)
    }


def apply_manual_source_packets(
    sources: list[Source],
    packets: dict[str, dict[str, Any]] | None = None,
) -> list[Source]:
    source_packets = packets if packets is not None else load_manual_source_packets()
    updated: list[Source] = []

    for source in sources:
        packet = source_packets.get(source.id)
        if not packet:
            updated.append(source)
            continue
        updated.append(replace(
            source,
            verification_status=str(packet.get("verification_status", "manual-packet")),
            verified_title=str(packet.get("verified_title", source.verified_title))[:240],
            verification_excerpt=str(packet.get("verification_excerpt", source.verification_excerpt))[:420],
            verification_error=str(packet.get("verification_error", source.verification_error))[:320],
            checked_at=str(packet.get("checked_at", source.checked_at)),
        ))

    return updated
