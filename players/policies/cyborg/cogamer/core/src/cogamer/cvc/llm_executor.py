"""LLMExecutor — runs multi-turn LLM conversations with tool use."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from cogamer.cvc.proglet import Program


class LLMExecutor:
    """Executor that drives an Anthropic-compatible LLM through a multi-turn
    conversation loop, dispatching tool-use requests via the *invoke* callback."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def run(
        self,
        program: Program,
        context: Any,
        invoke: Callable[[str, Any], Awaitable[Any]],
    ) -> Any:
        # 1. Build system prompt (callable or string)
        system = program.system
        if callable(system):
            system = system(context)

        # 2. Build tool definitions from program.tools
        tools = self._build_tools(program.tools) if program.tools else []

        # 3. Config
        max_turns = program.config.get("max_turns", 1)
        model = program.config.get("model", "claude-sonnet-4-20250514")
        max_tokens = program.config.get("max_tokens", 1024)
        temperature = program.config.get("temperature", 0.2)

        # 4. Context -> first user message
        user_content = context if isinstance(context, str) else str(context)
        messages = [{"role": "user", "content": user_content}]

        # 5. Conversation loop
        for _ in range(max_turns):
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system:
                kwargs["system"] = system
            if tools:
                kwargs["tools"] = tools

            response = self.client.messages.create(**kwargs)

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await invoke(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(result),
                            }
                        )
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                text = self._extract_text(response)
                return program.parser(text) if program.parser else text

        return None  # max_turns exhausted

    def _build_tools(self, tool_names: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": f"Invoke the '{name}' program",
                "input_schema": {"type": "object", "additionalProperties": True},
            }
            for name in tool_names
        ]

    def _extract_text(self, response: Any) -> str:
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""
