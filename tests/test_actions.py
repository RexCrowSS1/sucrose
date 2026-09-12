import tempfile
from pathlib import Path
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import AsyncMock

from sucrose.actions import CommandActions
from sucrose.ai import ChatService
from sucrose.client import SucroseBot
from sucrose.config import Settings
from sucrose.utils import UserError


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bot = SucroseBot(Settings(data_file=Path(self.directory.name) / 'config.json'))
        self.actor = Obj(id=3, guild_permissions=Obj(manage_guild=True))
        self.source = Obj(guild=Obj(id=1, fetch_member=AsyncMock(return_value=self.actor)),
                          channel=Obj(id=2), author=self.actor, reply=AsyncMock())
        self.actions = CommandActions(self.bot, self.source)
        self.bot.ollama = Obj(chat=AsyncMock())

    async def test_executes_real_command_and_delivers_result(self):
        self.bot.ollama.chat.return_value = '{"command":"autoresponder add","arguments":{"trigger":"halo","response":"Hai!"}}'
        result = await self.actions('tambahkan balasan halo menjadi Hai!')
        self.assertIn('/autoresponder add', result)
        self.assertEqual(self.bot.store.get(1)['responders'][0]['response'], 'Hai!')
        self.source.reply.assert_awaited_once()

    async def test_checks_fresh_permissions_before_mutation(self):
        self.actor.guild_permissions.manage_guild = False
        with self.assertRaisesRegex(UserError, 'Manage Server'):
            await self.actions.execute({'command': 'brand set', 'arguments': {'name': 'Changed'}})
        self.assertEqual(self.bot.store.get(1)['brand'], {})

    async def test_rejects_invalid_arguments_before_mutation(self):
        for arguments in ({'name': 'x' * 101}, {'unknown': 'x'}, {'name': True}):
            with self.assertRaises(UserError):
                await self.actions.execute({'command': 'brand set', 'arguments': arguments})
        for command in ('chat', 'chat-reset', 'delete-server'):
            with self.assertRaises(UserError):
                await self.actions.execute({'command': command, 'arguments': {}})
        self.assertEqual(self.bot.store.get(1)['brand'], {})

    async def test_missing_required_argument_does_not_execute(self):
        with self.assertRaisesRegex(UserError, 'response'):
            await self.actions.execute({'command': 'autoresponder add', 'arguments': {'trigger': 'hi'}})
        self.assertEqual(self.bot.store.get(1)['responders'], [])

    async def test_normal_chat_and_malformed_plan(self):
        self.bot.ollama.chat.return_value = 'null'
        self.assertIsNone(await self.actions('halo'))
        self.bot.ollama.chat.return_value = 'Sudah selesai!'
        with self.assertRaises(UserError):
            await self.actions('ubah branding')
        self.source.reply.assert_not_awaited()

    async def test_action_uses_chat_cooldown_and_releases_reservation(self):
        service = ChatService(self.bot.ollama, self.bot.settings)
        action = AsyncMock(return_value='done')
        self.assertEqual(await service.ask((1, 2, 3), 'ping', action=action), 'done')
        self.assertFalse(service.active)
        with self.assertRaisesRegex(UserError, 'Tunggu'):
            await service.ask((1, 2, 3), 'ping', action=action)
        action.assert_awaited_once()
        self.bot.ollama.chat.assert_not_awaited()
