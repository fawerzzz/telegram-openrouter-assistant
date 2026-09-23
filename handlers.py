from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, Update

from assistant_service import AssistantRequest, process_assistant_request
from database import Database
from openrouter_client import OpenRouterClient, OpenRouterError
from response_renderer import answer_guest_response, render_response, send_response
from scheduler import ReminderScheduler


logger = logging.getLogger(__name__)
router = Router()


def get_thread_id(message: Message) -> int:
    return message.message_thread_id or 0


def regular_context_key(message: Message) -> str:
    return f"thread:{get_thread_id(message)}"


def guest_context_key(message: Message) -> str:
    return f"guest:{message.chat.id}:{get_thread_id(message)}"


async def answer_in_thread(message: Message, text: str) -> None:
    await send_response(message, render_response(text))


def strip_guest_bot_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text.strip()

    mention = f"@{bot_username}".lower()
    stripped = text.strip()
    if not stripped.lower().startswith(mention):
        return stripped

    return stripped[len(mention) :].lstrip(" \t\n\r:,.").strip()


def message_text(message: Message) -> str | None:
    return message.text or message.caption


def display_sender(message: Message) -> str:
    if message.from_user:
        return message.from_user.full_name
    if message.sender_chat:
        return message.sender_chat.title or str(message.sender_chat.id)
    return "неизвестный отправитель"


def format_message_reference(label: str, message: Message) -> str | None:
    text = message_text(message)
    if not text:
        return None
    return f"{label} от {display_sender(message)}:\n{text.strip()}"


def format_external_reply(external_reply: Any) -> str | None:
    origin = getattr(external_reply, "origin", None)
    chat = getattr(external_reply, "chat", None)
    parts: list[str] = []

    if chat:
        title = getattr(chat, "title", None) or getattr(chat, "username", None)
        if title:
            parts.append(f"чат: {title}")

    if origin:
        sender_user = getattr(origin, "sender_user", None)
        sender_chat = getattr(origin, "sender_chat", None)
        sender_name = getattr(origin, "sender_user_name", None)
        if sender_user:
            parts.append(f"автор: {sender_user.full_name}")
        elif sender_chat:
            parts.append(f"автор: {sender_chat.title or sender_chat.id}")
        elif sender_name:
            parts.append(f"автор: {sender_name}")

    if not parts:
        return None
    return "Внешнее сообщение, на которое ответил пользователь: " + ", ".join(parts)


def extract_extra_reference_messages(source: Any) -> Any:
    model_extra = getattr(source, "model_extra", None)
    if model_extra:
        return model_extra.get("reference_messages")
    return getattr(source, "reference_messages", None)


def append_extra_reference_messages(references: list[str], extra_reference_messages: Any) -> None:
    if not extra_reference_messages:
        return

    for index, reference_message in enumerate(extra_reference_messages, start=1):
        if isinstance(reference_message, Message):
            reference = format_message_reference(f"Reference message {index}", reference_message)
        elif isinstance(reference_message, dict):
            text = reference_message.get("text") or reference_message.get("caption")
            reference = f"Reference message {index}:\n{text.strip()}" if text else None
        else:
            reference = None

        if reference:
            references.append(reference)


def collect_reference_context(message: Message, update: Update | None = None) -> list[str]:
    references: list[str] = []

    if message.reply_to_message:
        reference = format_message_reference("Сообщение, на которое ответил пользователь", message.reply_to_message)
        if reference:
            references.append(reference)

    if message.quote and message.quote.text:
        references.append(f"Цитата из сообщения:\n{message.quote.text.strip()}")

    if message.external_reply:
        reference = format_external_reply(message.external_reply)
        if reference:
            references.append(reference)

    append_extra_reference_messages(references, extract_extra_reference_messages(message))
    if update:
        append_extra_reference_messages(references, extract_extra_reference_messages(update))

    return references


async def answer_guest_message(message: Message, text: str) -> None:
    if not message.guest_query_id:
        logger.warning("Получен guest_message без guest_query_id: %s", message.message_id)
        return

    await answer_guest_response(message, render_response(text), str(uuid4()))


@router.message(Command("start", "help"))
async def help_handler(message: Message) -> None:
    await answer_in_thread(
        message,
        "Я ассистент для группы с темами. Пишите в нужной теме, и я сохраню "
        "контекст отдельно. Для напоминаний используйте обычный текст, например: "
        "напомни завтра в 15:00 проверить код.",
    )


@router.message(F.text)
async def text_handler(
    message: Message,
    db: Database,
    openrouter: OpenRouterClient,
    reminder_scheduler: ReminderScheduler,
    timezone_name: str,
) -> None:
    if not message.text or not message.from_user:
        return

    thread_id = get_thread_id(message)
    user_text = message.text.strip()

    try:
        answer = await process_assistant_request(
            AssistantRequest(
                context_key=regular_context_key(message),
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                thread_id=thread_id,
                text=user_text,
            ),
            db=db,
            openrouter=openrouter,
            reminder_scheduler=reminder_scheduler,
            timezone_name=timezone_name,
        )
        await answer_in_thread(message, answer)
    except (OpenRouterError, ValueError, KeyError) as exc:
        logger.exception("Ошибка обработки сообщения")
        await answer_in_thread(message, f"Не смог обработать запрос: {exc}")
    except Exception:
        logger.exception("Неожиданная ошибка")
        await answer_in_thread(message, "Произошла внутренняя ошибка. Подробности записаны в лог.")


@router.guest_message(F.text | F.caption)
async def guest_text_handler(
    message: Message,
    db: Database,
    openrouter: OpenRouterClient,
    reminder_scheduler: ReminderScheduler,
    timezone_name: str,
    bot_username: str | None = None,
    event_update: Update | None = None,
) -> None:
    raw_text = message_text(message)
    if not raw_text:
        return

    user_text = strip_guest_bot_mention(raw_text, bot_username)
    if not user_text:
        await answer_guest_message(message, "Напишите вопрос после упоминания бота.")
        return

    user_id = message.from_user.id if message.from_user else 0
    thread_id = get_thread_id(message)

    try:
        answer = await process_assistant_request(
            AssistantRequest(
                context_key=guest_context_key(message),
                user_id=user_id,
                chat_id=message.chat.id,
                thread_id=thread_id,
                text=user_text,
                reference_context=collect_reference_context(message, event_update),
            ),
            db=db,
            openrouter=openrouter,
            reminder_scheduler=reminder_scheduler,
            timezone_name=timezone_name,
        )
        await answer_guest_message(message, answer)
    except (OpenRouterError, ValueError, KeyError) as exc:
        logger.exception("Ошибка обработки guest message")
        await answer_guest_message(message, f"Не смог обработать запрос: {exc}")
    except Exception:
        logger.exception("Неожиданная ошибка в guest message")
        await answer_guest_message(message, "Произошла внутренняя ошибка. Подробности записаны в лог.")
