include "../llm"

putEnv("COWORLD_LLM_ENDPOINT", paramStr(1))
putEnv("COWORLD_LLM_MODEL", "anthropic/claude-sonnet-4.6")
putEnv(ClaudeCodeBedrockEnv, "1")
putEnv(GuidedBotLlmModelEnv, "retired-model")
doAssert currentProviderName() == "llm-sidecar"
let reply = httpPost("rules", "state")
doAssert reply.kind == LlmOk
doAssert reply.rawResponse == "NATIVE"
echo "Native guided player HTTP passed"
