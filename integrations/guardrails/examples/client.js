// Minimal Node client for a running guardrails server (Node 18+ has global fetch).
//
//   guardrails-server           # GUARD_LLM_PROVIDER=mock
//   node examples/client.js
//
// Demonstrates the two-call pattern: guard the input, then guard the output.

const BASE_URL = process.env.GUARD_URL || "http://localhost:8080";
const API_KEY = process.env.GUARD_API_KEY;
const headers = {
  "Content-Type": "application/json",
  ...(API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {}),
};

async function guardInput(text, policyId = "default") {
  const res = await fetch(`${BASE_URL}/v1/guard/input`, {
    method: "POST",
    headers,
    body: JSON.stringify({ input: text, policy_id: policyId }),
  });
  if (!res.ok) throw new Error(`guard/input ${res.status}`);
  return res.json();
}

async function guardOutput(userInput, output, docs = [], policyId = "default") {
  const res = await fetch(`${BASE_URL}/v1/guard/output`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      input: userInput,
      output,
      context_docs: docs.map((d) => ({ text: d })),
      policy_id: policyId,
    }),
  });
  if (!res.ok) throw new Error(`guard/output ${res.status}`);
  return res.json();
}

async function main() {
  const userText = "How do I reset my password?";

  const vin = await guardInput(userText);
  console.log("input verdict:", vin.action, vin.reasons);
  if (vin.action === "block") {
    console.log("refuse:", vin.refusal_message);
    return;
  }

  // ... your app calls its own LLM here to produce modelOutput ...
  const modelOutput = "Contact support at help@example.com to reset your password.";

  const vout = await guardOutput(userText, modelOutput, ["Password resets go through support."]);
  console.log("output verdict:", vout.action, vout.reasons);
  const safe = vout.action === "block" ? "<blocked>" : vout.sanitized_output;
  console.log("return to user:", safe);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
