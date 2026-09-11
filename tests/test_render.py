import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp.test_utils import make_mocked_request
import psycopg

from sucrose.ai import ChatService, OllamaClient
from sucrose.client import SucroseBot
from sucrose.config import Settings
from sucrose.hosting import create_app, run_web
from sucrose.postgres import PostgresStore, StorageError
from sucrose.utils import UserError


def connection():
    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock()
    return conn


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_loads_existing_configs(self):
        store = PostgresStore("postgresql://secret")
        conn = connection()
        cursor = Obj(fetchall=AsyncMock(return_value=[("1", {"brand": {"name": "Saved"}})]))
        conn.execute.return_value = cursor
        store.connect = AsyncMock(return_value=conn)
        await store.initialize()
        self.assertEqual(store.get(1)["brand"]["name"], "Saved")
        self.assertEqual(store.get(1)["roles"]["all"], [])

    async def test_write_reads_locked_row_and_publishes_cache_after_commit(self):
        store = PostgresStore("postgresql://secret")
        store.data = {"1": {"brand": {"name": "stale"}}}
        conn = connection()
        conn.execute.return_value = Obj(fetchone=AsyncMock(return_value=({"brand": {"name": "latest"}},)))
        store.connect = AsyncMock(return_value=conn)
        await store.update_async(1, lambda c: c["brand"].update(footer="new"))
        self.assertEqual(store.get(1)["brand"], {"name": "latest", "footer": "new"})
        self.assertIn("FOR UPDATE", conn.execute.call_args_list[1].args[0])
        self.assertEqual(conn.execute.call_args_list[1].args[1], ("1",))
        conn.__aexit__.assert_awaited_once()

    async def test_commit_failure_does_not_publish_unsaved_config(self):
        store = PostgresStore("postgresql://secret")
        store.data = {"1": {"brand": {"name": "before"}}}
        conn = connection()
        conn.execute.return_value = Obj(fetchone=AsyncMock(return_value=({"brand": {"name": "before"}},)))
        conn.__aexit__.side_effect = psycopg.OperationalError("secret connection information")
        store.connect = AsyncMock(return_value=conn)
        with self.assertRaises(StorageError) as raised:
            await store.update_async(1, lambda c: c["brand"].update(name="after"))
        self.assertEqual(store.get(1)["brand"]["name"], "before")
        self.assertNotIn("secret", str(raised.exception))

    async def test_database_outage_never_silently_falls_back_to_json(self):
        store = PostgresStore("postgresql://secret")
        store.connect = AsyncMock(side_effect=psycopg.OperationalError("secret password"))
        with self.assertRaises(StorageError) as raised:
            await store.initialize()
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(store.data, {})

    async def test_invalid_mutation_does_not_update_cache_or_database(self):
        store = PostgresStore("postgresql://secret")
        conn = connection()
        conn.execute.return_value = Obj(fetchone=AsyncMock(return_value=({},)))
        store.connect = AsyncMock(return_value=conn)
        def fail(config):
            raise ValueError("bad input")
        with self.assertRaises(ValueError):
            await store.update_async(1, fail)
        self.assertEqual(conn.execute.await_count, 2)
        self.assertEqual(store.data, {})

    async def test_import_only_inserts_missing_guilds(self):
        store = PostgresStore("postgresql://secret")
        source = Obj(data={"1": {}, "2": {}}, get=lambda key: {"brand": {"name": key}})
        conn = connection()
        conn.execute.side_effect = [Obj(fetchone=AsyncMock(return_value=None)), Obj(fetchone=AsyncMock(return_value=("2",)))]
        store.connect = AsyncMock(return_value=conn)
        store.initialize = AsyncMock()
        self.assertEqual(await store.import_missing(source), 1)
        self.assertTrue(all("ON CONFLICT DO NOTHING" in call.args[0] for call in conn.execute.call_args_list))
        store.initialize.assert_awaited_once()

    async def test_admin_write_defers_before_network_and_responds_after_save(self):
        bot = SucroseBot(Settings(database_url="postgresql://secret"))
        self.addAsyncCleanup(bot.close)
        bot.store.update_async = AsyncMock()
        response = Obj(is_done=MagicMock(return_value=False), defer=AsyncMock(), send_message=AsyncMock())
        i = Obj(guild_id=1, response=response, followup=Obj(send=AsyncMock()))
        async def deferred(**kwargs):
            response.is_done.return_value = True
        response.defer.side_effect = deferred
        await bot.tree.get_command("brand").get_command("reset").callback(i)
        response.defer.assert_awaited_once()
        bot.store.update_async.assert_awaited_once()
        i.followup.send.assert_awaited_once()
        response.send_message.assert_not_awaited()


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def endpoint(self, path, ready=False):
        bot = Obj(is_ready=lambda: ready, is_closed=lambda: False)
        app = create_app(bot)
        route = next(route for route in app.router.routes() if route.method == "GET" and route.resource.canonical == path)
        return await route.handler(make_mocked_request("GET", path))

    async def test_health_is_alive_while_gateway_connects(self):
        response = await self.endpoint("/health")
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), {"status": "alive", "discord_connected": False})

    async def test_ready_tracks_actual_discord_connection(self):
        self.assertEqual((await self.endpoint("/ready")).status, 503)
        self.assertEqual((await self.endpoint("/ready", True)).status, 200)

    async def test_home_does_not_expose_configuration_or_member_data(self):
        response = await self.endpoint("/")
        self.assertEqual(response.status, 200)
        self.assertNotIn("DATABASE_URL", response.text)
        self.assertNotIn("DISCORD_TOKEN", response.text)
        self.assertIn("sedang menghubungkan", response.text)

    async def test_web_mode_requires_persistent_storage(self):
        with self.assertRaisesRegex(ValueError, "DATABASE_URL"):
            await run_web(Settings())

    async def test_bot_failure_cleans_up_http_and_propagates_error(self):
        bot = MagicMock()
        bot.__aenter__ = AsyncMock(return_value=bot)
        bot.__aexit__ = AsyncMock(return_value=False)
        bot.close = AsyncMock()
        bot.start = AsyncMock(side_effect=UserError("login failed"))
        runner = Obj(setup=AsyncMock(), cleanup=AsyncMock())
        site = Obj(start=AsyncMock())
        loop = asyncio.get_running_loop()
        with patch("sucrose.hosting.SucroseBot", return_value=bot), patch("sucrose.hosting.web.AppRunner", return_value=runner), patch("sucrose.hosting.web.TCPSite", return_value=site), patch.object(loop, "add_signal_handler"), patch.object(loop, "remove_signal_handler"):
            with self.assertRaisesRegex(UserError, "login failed"):
                await run_web(Settings(database_url="postgresql://secret"))
        runner.cleanup.assert_awaited_once()
        bot.close.assert_awaited_once()


class AIHostingTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_ai_never_calls_ollama(self):
        ollama = Obj(chat=AsyncMock())
        service = ChatService(ollama, Settings(ai_enabled=False))
        with self.assertRaisesRegex(UserError, "AI_ENABLED"):
            await service.ask((1, 2, 3, "public"), "halo")
        ollama.chat.assert_not_awaited()

    async def test_remote_api_key_attached_only_when_configured(self):
        from tests.test_ai import Response
        session = MagicMock()
        session.request.return_value = Response({"models": []})
        settings = Settings(ollama_api_key="test-key")
        await OllamaClient(session, settings).models()
        self.assertEqual(session.request.call_args.kwargs["headers"], {"Authorization": "Bearer test-key"})
        self.assertNotIn("test-key", repr(settings))


if __name__ == "__main__":
    unittest.main()
