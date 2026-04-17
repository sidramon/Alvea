from openai import OpenAI
import json
from typing import Any, Callable, Dict, Optional


class LocalLLM:
    """
    Connector for a local AI (Ollama, LM Studio, etc.).
    Forces the AI to respond with structured JSON.

    Set `on_chunk` to a callable before calling `ask_json` to receive
    real-time streaming tokens:
        llm.on_chunk = lambda token: print(token, end="", flush=True)
        result = llm.ask_json(system, user)
        llm.on_chunk = None
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3",
    ):
        self.client = OpenAI(base_url=base_url, api_key="local-ai")
        self.model = model
        self.on_chunk: Optional[Callable[[str], None]] = None

    # ─────────────────────────────────────────────────────────────
    # PUBLIC
    # ─────────────────────────────────────────────────────────────

    def ask_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """
        Sends a prompt and returns the parsed JSON response.
        If `self.on_chunk` is set, the raw text is streamed token-by-token
        via the callback while the full response is accumulated internally.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]
        try:
            if self.on_chunk is not None:
                return self._ask_streaming(messages)
            else:
                return self._ask_blocking(messages)
        except json.JSONDecodeError as e:
            raise ValueError(f"AI did not return valid JSON: {e}")
        except Exception as e:
            raise RuntimeError(f"Error communicating with local AI: {e}")

    # ─────────────────────────────────────────────────────────────
    # PRIVATE
    # ─────────────────────────────────────────────────────────────

    def _ask_blocking(self, messages: list) -> Dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return json.loads(response.choices[0].message.content)

    def _ask_streaming(self, messages: list) -> Dict[str, Any]:
        accumulated = ""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                accumulated += delta
                if self.on_chunk:
                    self.on_chunk(delta)
        return json.loads(accumulated)