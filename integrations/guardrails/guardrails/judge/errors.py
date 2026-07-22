"""Typed judge errors.

Each carries a ``kind`` that maps 1:1 onto ``JudgeInfo.error`` and drives the pipeline's
``fail_mode`` handling. Nothing here ever reaches the client as a 5xx — the pipeline
converts these into a verdict.
"""

from __future__ import annotations

from typing import Literal

JudgeErrorKind = Literal["timeout", "api_error", "parse_error", "refusal"]


class JudgeError(Exception):
    """Base class for all judge failures."""

    kind: JudgeErrorKind = "api_error"


class JudgeTimeout(JudgeError):
    kind = "timeout"


class JudgeAPIError(JudgeError):
    kind = "api_error"


class JudgeParseError(JudgeError):
    kind = "parse_error"


class JudgeRefusal(JudgeError):
    kind = "refusal"
