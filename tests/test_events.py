from pathlib import Path
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock

import discord

from sucrose.client import SucroseBot
from sucrose.config import Settings


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bot = SucroseBot(Settings(data_file=Path(self.directory.name) / "config.json"))
        self.bot._connection.user = Obj(id=123)
        self.bot.chat = Obj(ask=AsyncMock(return_value="Halo dari Ollama"))
        self.addAsyncCleanup(self.bot.close)

    def message(self, content="halo"):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id, channel.parent_id, channel.send = 2, None, AsyncMock()
        channel.typing.return_value = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        return Obj(guild=Obj(id=1, name="Server", member_count=10), author=Obj(id=3, bot=False, name="User"),
                   channel=channel, webhook_id=None, is_system=lambda: False, content=content, reply=AsyncMock())

    def add_rule(self, **changes):
        rule = {"trigger": "halo", "response": "Halo {username}", "mode": "contains", "channel": None, "embed": False, "cooldown": 5, **changes}
        self.bot.store.update(1, lambda c: c["responders"].append(rule))

    async def test_regular_message_still_uses_autoresponder_with_cooldown(self):
        self.add_rule()
        message = self.message()
        await self.bot.on_message(message)
        await self.bot.on_message(message)
        message.reply.assert_awaited_once_with("Halo User", mention_author=False)
        self.bot.chat.ask.assert_not_awaited()

    async def test_mention_takes_priority_over_autoresponder(self):
        self.add_rule()
        message = self.message("<@123> halo")
        await self.bot.on_message(message)
        self.bot.chat.ask.assert_awaited_once_with((1, 2, 3, "public"), "halo", None, action=ANY)
        message.reply.assert_awaited_once()
        self.assertEqual(message.reply.call_args.args[0], "Halo dari Ollama")
        self.assertFalse(message.reply.call_args.kwargs["allowed_mentions"].everyone)

    async def test_reply_to_bot_also_starts_chat(self):
        message = self.message("lanjutkan penjelasannya")
        message.reference = Obj(resolved=Obj(author=Obj(id=123)))
        await self.bot.on_message(message)
        self.bot.chat.ask.assert_awaited_once_with((1, 2, 3, "public"), "lanjutkan penjelasannya", None, action=ANY)
        message.reply.assert_awaited_once()

    async def test_bot_and_webhook_messages_ignored(self):
        message = self.message("<@123> halo")
        message.author.bot = True
        await self.bot.on_message(message)
        message.author.bot, message.webhook_id = False, 44
        await self.bot.on_message(message)
        self.bot.chat.ask.assert_not_awaited()
        message.reply.assert_not_awaited()

    async def test_autoresponder_channel_filter(self):
        self.add_rule(channel="999")
        message = self.message()
        await self.bot.on_message(message)
        message.reply.assert_not_awaited()

    async def test_member_join_combines_all_and_human_or_bot_roles(self):
        self.bot.store.update(1, lambda c: c.update(roles={"all": ["5"], "human": ["6", "5"], "bot": ["7"]}))
        class Role:
            def __init__(self, id):
                self.id, self.managed = id, False
            def is_default(self):
                return False
            def __ge__(self, other):
                return self.id >= other
        roles = {n: Role(n) for n in (5, 6, 7)}
        member = Obj(bot=False, guild=Obj(id=1, get_role=roles.get, me=Obj(top_role=10)), add_roles=AsyncMock())
        await self.bot.on_member_join(member)
        self.assertEqual([call.args[0].id for call in member.add_roles.call_args_list], [5, 6])
        member.bot = True
        member.add_roles.reset_mock()
        await self.bot.on_member_join(member)
        self.assertEqual([call.args[0].id for call in member.add_roles.call_args_list], [5, 7])


if __name__ == "__main__":
    unittest.main()
