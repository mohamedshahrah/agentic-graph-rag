"""Safety layer — the Guardrails integration.

Wraps every answer the agent produces in two checks against the standalone
**Guardrails & Safety Layer** service (vendored under `integrations/guardrails`,
its own repo): the user's message is judged *before* the model runs, and the
model's answer *after*, before it reaches the user.

The client is deliberately **fail-open by default and always optional**: with
`safety.enabled: false` (the default) nothing here runs, and when the guard is
switched on but unreachable, a query still returns an answer rather than a 500 —
`safety.fail_open` decides whether an unreachable guard allows or blocks.
"""

from __future__ import annotations

from graphrag.safety.guardrails import GuardrailsClient, GuardVerdict

__all__ = ["GuardrailsClient", "GuardVerdict"]
