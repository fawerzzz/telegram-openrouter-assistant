from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from database import Database, Reminder
from openrouter_client import OpenRouterClient, parse_tool_arguments
from scheduler import ReminderScheduler


@dataclass(slots=True)
class AssistantRequest:
    context_key: str
    chat_id: int
    thread_id: int
    user_id: int
    text: str
    reference_context: list[str] = field(default_factory=list)


def parse_reminder_datetime(value: str, timezone_name: str) -> datetime:
    cleaned = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone_name))
    return dt


def build_user_message(text: str, reference_context: list[str]) -> str:
    user_text = text.strip()
    if not reference_context:
        return user_text

    references = "\n\n".join(reference_context)
    return (
        "Дополнительный контекст из сообщений, на которые ссылается запрос:\n"
        f"{references}\n\n"
        f"Запрос пользователя:\n{user_text}"
    )


async def process_assistant_request(
    request: AssistantRequest,
    db: Database,
    openrouter: OpenRouterClient,
    reminder_scheduler: ReminderScheduler,
    timezone_name: str,
) -> str:
    is_guest = request.context_key.startswith("guest:")
    user_message = build_user_message(request.text, request.reference_context)

    if is_guest:
        history = [{"role": "user", "content": user_message}]
    else:
        await db.add_message(
            request.context_key,
            "user",
            user_message,
            thread_id=request.thread_id
        )
        history = await db.get_history(request.context_key)
    first_response = await openrouter.chat(history)

    if not first_response.tool_calls:
        answer = first_response.content or "Не получил текстовый ответ от модели."

        if not is_guest:
            await db.add_message(
                request.context_key,
                "assistant",
                answer,
                thread_id=request.thread_id
            )

        return answer

    tool_messages = []
    for tool_call in first_response.tool_calls:
        function_name = tool_call.get("function", {}).get("name")
        if function_name != "create_reminder":
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps({"ok": False, "error": "unknown function"}),
                }
            )
            continue

        args = parse_tool_arguments(tool_call)
        reminder_text = str(args["text"]).strip()
        trigger_time = parse_reminder_datetime(str(args["datetime_str"]), timezone_name)
        trigger_time = trigger_time.astimezone(ZoneInfo(timezone_name))

        reminder_id = await db.add_reminder(
            user_id=request.user_id,
            chat_id=request.chat_id,
            thread_id=request.thread_id,
            reminder_text=reminder_text,
            trigger_time=trigger_time,
        )
        reminder = Reminder(
            id=reminder_id,
            user_id=request.user_id,
            chat_id=request.chat_id,
            thread_id=request.thread_id,
            reminder_text=reminder_text,
            trigger_time=trigger_time.isoformat(timespec="seconds"),
            is_sent=0,
        )
        await reminder_scheduler.schedule_reminder(reminder)

        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(
                    {
                        "ok": True,
                        "reminder_id": reminder_id,
                        "trigger_time": trigger_time.isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                ),
            }
        )

    final_response = await openrouter.chat(
        history,
        extra_messages=[first_response.message, *tool_messages],
    )
    answer = final_response.content or "Готово, напоминание создано."
    if not is_guest:
        await db.add_message(
            request.context_key,
            "assistant",
            answer,
            thread_id=request.thread_id
        )
    return answer
