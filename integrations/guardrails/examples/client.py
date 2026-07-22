"""Minimal Python client for a running guardrails server.

    guardrails-server            # in one terminal (GUARD_LLM_PROVIDER=mock)
    python examples/client.py    # in another

Shows the two-call pattern an app uses around its own LLM: guard the user input first, then
guard the model's output before returning it.
"""

from __future__ import annotations

import os

import httpx

BASE_URL = os.environ.get("GUARD_URL", "http://localhost:8080")
API_KEY = os.environ.get("GUARD_API_KEY")  # only if the server was started with one
HEADERS = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


def guard_input(text: str, policy_id: str = "default") -> dict:
    r = httpx.post(
        f"{BASE_URL}/v1/guard/input",
        json={"input": text, "policy_id": policy_id},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def guard_output(user_input: str, output: str, docs: list[str] | None = None,
                 system_prompt: str | None = None, policy_id: str = "default") -> dict:
    r = httpx.post(
        f"{BASE_URL}/v1/guard/output",
        json={
            "input": user_input,
            "output": output,
            "context_docs": [{"text": d} for d in (docs or [])],
            "system_prompt": system_prompt,
            "policy_id": policy_id,
        },
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main() -> None:
    user_text = "How do I reset my password?"

    verdict_in = guard_input(user_text)
    print("input verdict:", verdict_in["action"], verdict_in["reasons"])
    if verdict_in["action"] == "block":
        print("refuse:", verdict_in["refusal_message"])
        return

    # ... your app calls its own LLM here to produce `model_output` ...
    model_output = "Contact support at help@example.com to reset your password."

    verdict_out = guard_output(user_text, model_output, docs=["Password resets go through support."])
    print("output verdict:", verdict_out["action"], verdict_out["reasons"])
    safe = verdict_out["sanitized_output"] if verdict_out["action"] != "block" else "<blocked>"
    print("return to user:", safe)


if __name__ == "__main__":
    main()
