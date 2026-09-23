from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Создать напоминание или календарную задачу для пользователя.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Короткий текст напоминания.",
                    },
                    "datetime_str": {
                        "type": "string",
                        "description": "Дата и время в ISO 8601, например 2026-06-02T15:00:00+03:00.",
                    },
                },
                "required": ["text", "datetime_str"],
                "additionalProperties": False,
            },
        },
    }
]


@dataclass(slots=True)
class OpenRouterResponse:
    content: str
    message: dict[str, Any]
    tool_calls: list[dict[str, Any]]


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timezone_name: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timezone = ZoneInfo(timezone_name)
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    def system_prompt(self) -> str:
        now = datetime.now(self.timezone).isoformat(timespec="seconds")
        return (
            "Ты персональный Telegram-ассистент. Отвечай кратко, полезно и естественно.\n"
            "\n"
            "ВАЖНО ПО ФОРМАТИРОВАНИЮ:\n"
            "- Используй Markdown, а не HTML.\n"
            "- Для жирного текста используй двойные звездочки вокруг текста.\n"
            "- Для inline code используй одинарные обратные кавычки.\n"
            "- Для блоков кода используй стандартный Markdown code block с тройными обратными кавычками. Если известен язык, указывай его после открывающих кавычек.\n"
            "- Не используй HTML-теги вроде <b>, <strong>, <code>, <pre>, <br> и другие HTML-теги.\n"
            "- Не используй Telegram HTML-разметку.\n"
            "\n"
            "МАТЕМАТИКА:\n"
            "- Для inline-формул используй LaTeX в формате \\( формула \\).\n"
            "- Для отдельных математических блоков используй $$ формула $$.\n"
            "- Для сложных формул предпочитай отдельный блок $$ ... $$.\n"
            "- Передавай содержимое LaTeX как обычный LaTeX, без HTML-экранирования.\n"
            "- Не заменяй математические формулы их текстовым описанием, если формулу можно нормально записать в LaTeX.\n"
            "- Не помещай LaTeX в code block.\n"
            "\n"
            "НАПОМИНАНИЯ:\n"
            "- Если пользователь просит напомнить, запланировать, поставить задачу или событие, обязательно вызови функцию create_reminder.\n"
            "- В datetime_str всегда передавай конкретную дату и время в ISO 8601 с часовым поясом.\n"
            f"- Текущее время: {now}."
        )

    async def chat(
        self,
        history: list[dict[str, Any]],
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> OpenRouterResponse:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt()},
            *history,
        ]
        if extra_messages:
            messages.extend(extra_messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            # OpenRouter совместим с OpenAI Chat Completions tool calling.
            "tools": TOOLS,
            "tool_choice": "auto",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost",
            "X-Title": "Telegram OpenRouter Assistant",
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                    raw_text = await resp.text()
                    if resp.status >= 400:
                        raise OpenRouterError(f"OpenRouter HTTP {resp.status}: {raw_text[:500]}")
                    data = json.loads(raw_text)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise OpenRouterError("OpenRouter временно недоступен") from exc
        except json.JSONDecodeError as exc:
            raise OpenRouterError("OpenRouter вернул некорректный JSON") from exc

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError(f"Неожиданный ответ OpenRouter: {data}") from exc

        return OpenRouterResponse(
            content=message.get("content") or "",
            message=message,
            tool_calls=message.get("tool_calls") or [],
        )


def parse_tool_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    raw_args = tool_call.get("function", {}).get("arguments") or "{}"
    if isinstance(raw_args, dict):
        return raw_args
    return json.loads(raw_args)
