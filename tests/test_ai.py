import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from sucrose.ai import ChatService, OllamaClient, check_access
from sucrose.config import Settings
from sucrose.utils import UserError, chat_key


class ChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100
        self.ollama = Obj(chat=AsyncMock(return_value="Halo!"))
        self.settings = Settings(history_turns=2, max_conversations=2)
        self.service = ChatService(self.ollama, self.settings, clock=lambda: self.now)
        self.key = chat_key(1, 2, 3)

    async def ask(self, key=None, prompt="halo", **kwargs):
        self.now += 6
        return await self.service.ask(key or self.key, prompt, **kwargs)

    async def test_multi_turn_history_is_bounded_and_keeps_system_message(self):
        await self.ask(prompt="first")
        await self.ask(prompt="second")
        await self.ask(prompt="third")
        messages = self.ollama.chat.call_args.args[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[1]["content"], "second")
        self.assertEqual(len(self.service.histories[self.key].messages), 4)

    async def test_history_isolated_by_server_channel_user_and_visibility(self):
        await self.ask(prompt="SECRET")
        for key in (chat_key(2, 2, 3), chat_key(1, 9, 3), chat_key(1, 2, 9), chat_key(1, 2, 3, True)):
            await self.ask(key)
            self.assertNotIn("SECRET", json.dumps(self.ollama.chat.call_args.args[0]))

    async def test_reset_removes_both_visibility_histories_only_for_this_user_channel(self):
        self.service.settings = replace(self.settings, max_conversations=10)
        for key in (self.key, chat_key(1, 2, 3, True), chat_key(1, 9, 3), chat_key(1, 2, 9)):
            await self.ask(key)
        self.assertEqual(self.service.reset(1, 2, 3), 2)
        self.assertEqual(len(self.service.histories), 2)

    async def test_ttl_and_capacity_eviction(self):
        await self.ask()
        self.now += self.settings.history_ttl
        await self.ask()
        self.assertEqual(len(self.ollama.chat.call_args.args[0]), 2)
        await self.ask(chat_key(1, 2, 4))
        await self.ask(chat_key(1, 2, 5))
        self.assertEqual(len(self.service.histories), 2)
        self.assertNotIn(self.key, self.service.histories)

    async def test_cooldown_shared_between_channels_and_public_private(self):
        await self.ask()
        with self.assertRaisesRegex(UserError, "Tunggu"):
            await self.service.ask(chat_key(1, 5, 3, True), "again")

    async def test_failures_do_not_save_history_and_release_busy_state(self):
        self.ollama.chat.side_effect = UserError("timeout")
        with self.assertRaises(UserError):
            await self.ask()
        self.assertFalse(self.service.histories)
        self.assertFalse(self.service.active)
        self.assertFalse(self.service.active_users)
        self.ollama.chat.side_effect = None
        await self.ask()

    async def test_concurrent_and_duplicate_requests_rejected_without_queue(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(messages):
            started.set()
            await release.wait()
            return "ok"
        self.ollama.chat.side_effect = delayed
        self.service.settings = replace(self.settings, max_concurrent=1)
        task = asyncio.create_task(self.ask())
        await started.wait()
        try:
            with self.assertRaisesRegex(UserError, "sebelumnya"):
                await self.service.ask(self.key, "again")
            with self.assertRaisesRegex(UserError, "sibuk"):
                await self.service.ask(chat_key(1, 2, 4), "other")
            with self.assertRaisesRegex(UserError, "sedang diproses"):
                self.service.reset(1, 2, 3)
        finally:
            release.set()
            await task
        self.assertFalse(self.service.active)

    async def test_changed_system_prompt_discards_old_context(self):
        await self.ask(prompt="old")
        await self.ask(system="New personality")
        messages = self.ollama.chat.call_args.args[0]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "New personality")

    async def test_empty_and_oversized_prompts_rejected(self):
        for prompt in ("   ", "x" * 2001):
            with self.assertRaises(UserError):
                await self.ask(prompt=prompt)
        self.ollama.chat.assert_not_awaited()

    def test_server_ai_switch_and_channel_scope(self):
        with self.assertRaisesRegex(UserError, "dinonaktifkan"):
            check_access({"ai": {"enabled": False}}, 2)
        with self.assertRaisesRegex(UserError, "<#2>"):
            check_access({"ai": {"channel": "2"}}, 3)
        check_access({"ai": {"channel": "2"}}, 2)
        check_access({"ai": {"channel": "2"}}, 3, 2)


class Response:
    def __init__(self, payload=None, status=200, raw=None):
        self.status = status
        self.raw = raw if raw is not None else json.dumps(payload).encode()
        self.content = self

    async def iter_chunked(self, size):
        for offset in range(0, len(self.raw), size):
            yield self.raw[offset:offset + size]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class OllamaTests(unittest.IsolatedAsyncioTestCase):
    def client(self, payload=None, status=200, raw=None):
        self.session = MagicMock()
        self.session.request.return_value = Response(payload, status, raw)
        return OllamaClient(self.session, Settings())

    async def test_api_chat_contract(self):
        client = self.client({"message": {"content": "Halo", "thinking": "not public"}})
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(await client.chat(messages), "Halo")
        args, kwargs = self.session.request.call_args
        self.assertEqual(args, ("POST", "http://127.0.0.1:11434/api/chat"))
        self.assertEqual(kwargs["json"]["messages"], messages)
        self.assertFalse(kwargs["json"]["stream"])
        self.assertEqual(kwargs["json"]["model"], "llama3.2:latest")
        self.assertFalse(kwargs["allow_redirects"])

    async def test_tags(self):
        client = self.client({"models": [{"name": "llama3.2:latest"}]})
        self.assertEqual(await client.models(), ["llama3.2:latest"])

    async def test_missing_model_and_server_errors(self):
        for status in (404, 500, 301):
            with self.assertRaises(UserError):
                await self.client({}, status).chat([])

    async def test_network_and_timeout_messages(self):
        client = self.client()
        for error, expected in ((aiohttp.ClientConnectionError(), "menghubungi"), (asyncio.TimeoutError(), "terlalu lama")):
            self.session.request.side_effect = error
            with self.assertRaisesRegex(UserError, expected):
                await client.chat([])

    async def test_invalid_empty_and_oversized_responses(self):
        for response in ({}, {"error": "bad"}, {"message": {"content": ""}}, {"message": None}, []):
            with self.assertRaises(UserError):
                await self.client(response).chat([])
        for raw in (b"not json", b"x" * (2 * 1024 * 1024 + 1)):
            with self.assertRaises(UserError):
                await self.client(raw=raw).chat([])

    async def test_very_long_model_output_is_capped(self):
        answer = await self.client({"message": {"content": "x" * 8000}}).chat([])
        self.assertLessEqual(len(answer), 6000)
        self.assertIn("dipotong", answer)


if __name__ == "__main__":
    unittest.main()
