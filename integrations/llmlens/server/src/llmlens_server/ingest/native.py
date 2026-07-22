"""Parse the native SDK payload (already close to canonical) into canonical
events, attaching the authenticated project and filling required defaults."""

from __future__ import annotations

from llmlens_server.core.errors import IngestError

_REQUIRED = ("trace_id", "span_id", "start_time")


def parse_native(events: list[dict], project_id: str) -> list[dict]:
    out: list[dict] = []
    for ev in events:
        for field in _REQUIRED:
            if not ev.get(field):
                raise IngestError(f"event missing required field: {field}")
        ev = dict(ev)
        ev["project_id"] = project_id
        ev.setdefault("kind", "span")
        out.append(ev)
    return out
