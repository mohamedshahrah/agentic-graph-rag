"""OpenTelemetry GenAI semantic-convention attribute names.

Using the standard `gen_ai.*` vocabulary keeps us interoperable with the whole
OpenTelemetry ecosystem: the OTLP receiver reads these keys off incoming spans,
and the native SDK emits them too. See
https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
"""

# Request / response
GEN_AI_SYSTEM = "gen_ai.system"                  # provider: openai | anthropic | ...
GEN_AI_OPERATION = "gen_ai.operation.name"        # chat | text_completion | embeddings ...
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_RESPONSE_FINISH = "gen_ai.response.finish_reasons"

# Usage
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

# Content (recorded only when enabled; belongs in events/structured attrs, not
# indexed columns — we store it in a separate ClickHouse table).
GEN_AI_INPUT_MESSAGES = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES = "gen_ai.output.messages"

# llmlens extensions (not part of the OTel spec) for product features.
LLMLENS_USER_ID = "llmlens.user_id"
LLMLENS_SESSION_ID = "llmlens.session_id"
LLMLENS_TAGS = "llmlens.tags"
