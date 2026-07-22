"""Cost calculation from token usage + a pricing table.

Loaded once in the worker (refreshed periodically) so cost enrichment doesn't hit
Postgres per span. Matching tries exact (provider, model), then a prefix match so
`gpt-4o-2024-08-06` still resolves to `gpt-4o`."""

from __future__ import annotations

from llmlens_server.pricing.seed import SEED_PRICING


class PricingTable:
    def __init__(self, prices: dict[tuple[str, str], tuple[float, float]]) -> None:
        self._prices = prices

    @classmethod
    def from_seed(cls) -> PricingTable:
        return cls({(p.lower(), m.lower()): (i, o) for p, m, i, o in SEED_PRICING})

    @classmethod
    def from_rows(cls, rows: list[dict]) -> PricingTable:
        table = {
            (r["provider"].lower(), r["model"].lower()): (
                float(r["input_per_1k"]), float(r["output_per_1k"])
            )
            for r in rows
        }
        # Fall back to seed for anything the DB doesn't have.
        for p, m, i, o in SEED_PRICING:
            table.setdefault((p.lower(), m.lower()), (i, o))
        return cls(table)

    def get(self, provider: str, model: str) -> tuple[float, float] | None:
        provider, model = (provider or "").lower(), (model or "").lower()
        if (provider, model) in self._prices:
            return self._prices[(provider, model)]
        # prefix match within the same provider (handles dated model snapshots)
        best: tuple[str, tuple[float, float]] | None = None
        for (p, m), price in self._prices.items():
            if (
                p == provider and m and model.startswith(m)
                and (best is None or len(m) > len(best[0]))
            ):
                best = (m, price)
        if best:
            return best[1]
        # provider-wide default (e.g. ollama -> free)
        return self._prices.get((provider, ""))


def compute_cost(
    table: PricingTable, provider: str, model: str, input_tokens: int, output_tokens: int
) -> float | None:
    price = table.get(provider, model)
    if price is None:
        return None
    inp, out = price
    return (input_tokens / 1000.0) * inp + (output_tokens / 1000.0) * out
