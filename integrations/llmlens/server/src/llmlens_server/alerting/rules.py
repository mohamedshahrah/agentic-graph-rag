"""Alert rule types.

- error_rate  : fraction of generations that errored, over the window (0..1)
- cost_spike  : total USD spent over the window
- latency_p95 : p95 generation latency (ms) over the window
- volume      : request count over the window

A rule fires when its measured value exceeds `threshold`.
"""

RULE_TYPES = {"error_rate", "cost_spike", "latency_p95", "volume"}


def validate_rule_type(rule_type: str) -> str:
    if rule_type not in RULE_TYPES:
        raise ValueError(f"Unknown alert rule type: {rule_type}")
    return rule_type
