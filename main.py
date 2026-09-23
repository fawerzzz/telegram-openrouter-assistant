from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from database import Database
from handlers import router
from openrouter_client import OpenRouterClient
from scheduler import ReminderScheduler


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


async def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot_token = require_env("BOT_TOKEN")
    openrouter_key = require_env("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "openrouter/owl-alpha")
    timezone_name = os.getenv("BOT_TIMEZONE", "Europe/Moscow")

    bot = Bot(token=bot_token)
    bot_info = await bot.get_me()
    db = Database()
    await db.init()

    openrouter = OpenRouterClient(
        api_key=openrouter_key,
        model=model,
        timezone_name=timezone_name,
    )
    reminder_scheduler = ReminderScheduler(bot=bot, db=db, timezone_name=timezone_name)
    await reminder_scheduler.start()

    dp = Dispatcher(
        db=db,
        openrouter=openrouter,
        reminder_scheduler=reminder_scheduler,
        timezone_name=timezone_name,
        bot_username=bot_info.username,
    )
    dp.include_router(router)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await reminder_scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
