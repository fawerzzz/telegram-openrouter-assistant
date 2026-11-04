import unittest
import sys
import types
from types import SimpleNamespace

# Keep this focused unit test runnable in a minimal checkout. Production
# dependencies are still declared in requirements.txt and used normally.
if "asyncpg" not in sys.modules:
    asyncpg_stub = types.ModuleType("asyncpg")
    asyncpg_stub.create_pool = None
    sys.modules["asyncpg"] = asyncpg_stub

if "apscheduler.schedulers.asyncio" not in sys.modules:
    apscheduler_stub = types.ModuleType("apscheduler")
    schedulers_stub = types.ModuleType("apscheduler.schedulers")
    asyncio_stub = types.ModuleType("apscheduler.schedulers.asyncio")

    class AsyncIOScheduler:
        pass

    asyncio_stub.AsyncIOScheduler = AsyncIOScheduler
    sys.modules["apscheduler"] = apscheduler_stub
    sys.modules["apscheduler.schedulers"] = schedulers_stub
    sys.modules["apscheduler.schedulers.asyncio"] = asyncio_stub

from app.assistant_service import AssistantRequest, process_assistant_request


class FakeDatabase:
    def __init__(self):
        self.messages = []

    async def add_message(self, context_key, user_id, role, content, thread_id=0):
        self.messages.append(
            {
                "context_key": context_key,
                "user_id": user_id,
                "role": role,
                "content": content,
                "thread_id": thread_id,
            }
        )

    async def get_history(self, context_key, user_id, limit=10):
        rows = [
            message
            for message in self.messages
            if message["context_key"] == context_key
            and message["user_id"] == user_id
        ][-limit:]
        return [{"role": row["role"], "content": row["content"]} for row in rows]


class FakeOpenRouter:
    def __init__(self):
        self.histories = []

    async def chat(self, history, extra_messages=None):
        self.histories.append(list(history))
        return SimpleNamespace(content="Ответ", tool_calls=[], message={})


class ConversationIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_users_have_independent_histories_and_same_user_keeps_context(self):
        db = FakeDatabase()
        openrouter = FakeOpenRouter()
        scheduler = SimpleNamespace()

        async def ask(user_id, text):
            return await process_assistant_request(
                AssistantRequest(
                    context_key="thread:0",
                    user_id=user_id,
                    chat_id=100,
                    thread_id=0,
                    text=text,
                ),
                db=db,
                openrouter=openrouter,
                reminder_scheduler=scheduler,
                timezone_name="Europe/Moscow",
            )

        await ask(101, "Меня зовут Андрей")
        await ask(202, "Как меня зовут?")
        await ask(101, "Как меня зовут?")

        self.assertEqual(
            openrouter.histories[1],
            [{"role": "user", "content": "Как меня зовут?"}],
        )
        self.assertEqual(
            openrouter.histories[2],
            [
                {"role": "user", "content": "Меня зовут Андрей"},
                {"role": "assistant", "content": "Ответ"},
                {"role": "user", "content": "Как меня зовут?"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
