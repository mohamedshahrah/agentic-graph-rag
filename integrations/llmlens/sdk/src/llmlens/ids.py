"""Trace/span id generation (hex, OTel-compatible widths)."""

from __future__ import annotations

import secrets


def gen_trace_id() -> str:
    return secrets.token_hex(16)  # 128-bit


def gen_span_id() -> str:
    return secrets.token_hex(8)   # 64-bit
