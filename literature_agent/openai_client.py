from __future__ import annotations

import json
import os
import re
from typing import Any

from .utils import post_json


class OpenAIClient:
    def __init__(self, api_key: str | None, model: str = "gpt-5.2", base_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or None
        self.model = self._normalize_model(model)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def text(self, instructions: str, prompt: str, *, max_output_tokens: int = 3500) -> str:
        if not self.api_key:
            raise RuntimeError("OpenAI API key is not configured.")
        if self._uses_chat_completions:
            return self._chat_completions_text(instructions, prompt, max_output_tokens=max_output_tokens)
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
        }
        data = post_json(
            "https://api.openai.com/v1/responses",
            payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=120,
        )
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        return "\n".join(chunks).strip()

    @property
    def _uses_chat_completions(self) -> bool:
        return bool(self.base_url and "api.openai.com" not in self.base_url)

    def _normalize_model(self, model: str) -> str:
        if self.base_url and "deepseek" in self.base_url.lower() and model.startswith("gpt-"):
            return os.getenv("OPENAI_MODEL", "deepseek-chat")
        return model

    def _chat_completions_text(self, instructions: str, prompt: str, *, max_output_tokens: int) -> str:
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_output_tokens,
            "temperature": 0.2,
        }
        data = post_json(
            endpoint,
            payload,
            headers={"Authorization": f"Bearer {self.api_key.strip()}"},
            timeout=120,
        )
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                return reasoning_content
        return ""

    def json(self, instructions: str, prompt: str, *, fallback: dict[str, Any]) -> dict[str, Any]:
        raw = self.text(instructions, prompt)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return fallback
