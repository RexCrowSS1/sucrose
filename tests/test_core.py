import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands

from varah.client import VarahBot
from varah.config import Settings
from varah.store import Store
from varah.utils import UserError, branded, chunks, color, image_url, matches, mention_prompt, parse_ticket, template, ticket_overwrites, ticket_topic, validate_role


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"

    def test_persistence_and_isolation(self):
        store = Store(self.path)
        store.update(1, lambda c: c["brand"].update(name="Varah"))
        copy = store.get(1)
        copy["brand"]["name"] = "Changed"
        self.assertEqual(Store(self.path).get(1)["brand"]["name"], "Varah")
        self.assertEqual(store.get(2)["brand"], {})

    def test_previous_javascript_data_remains_compatible(self):
        original = {"1": {"brand": {"color": 123, "name": "Old"}, "responders": [{"trigger": "hi"}],
                          "roles": {"human": ["456"], "bot": [], "all": []}, "ticket": {"category": "789", "staff": "123"}}}
        self.path.write_text(json.dumps(original))
        store = Store(self.path)
        config = store.get(1)
        self.assertEqual(config["roles"]["human"], ["456"])
        self.assertEqual(config["ticket"], original["1"]["ticket"])
        self.assertEqual(config["ai"], {"enabled": True, "channel": None})
        store.update(1, lambda c: c["ai"].update(enabled=False))
        self.assertEqual(Store(self.path).get(1)["brand"]["name"], "Old")

    def test_broken_data_is_never_overwritten(self):
        self.path.write_text("broken")
        with self.assertRaisesRegex(ValueError, "data tidak ditimpa"):
            Store(self.path)
        self.assertEqual(self.path.read_text(), "broken")

    def test_failed_write_does_not_change_memory_or_existing_file(self):
        store = Store(self.path)
        store.update(1, lambda c: c["brand"].update(name="Before"))
        with patch("varah.store.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                store.update(1, lambda c: c["brand"].update(name="After"))
        self.assertEqual(store.get(1)["brand"]["name"], "Before")
        self.assertEqual(Store(self.path).get(1)["brand"]["name"], "Before")
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)


class UtilityTests(unittest.TestCase):
    def test_matching_and_templates(self):
        self.assertTrue(matches("HALO", {"trigger": "halo", "mode": "exact"}))
        self.assertFalse(matches("halo semua", {"trigger": "halo", "mode": "exact"}))
        self.assertTrue(matches("halo semua", {"trigger": "halo", "mode": "startswith"}))
        self.assertTrue(matches("butuh bantuan", {"trigger": "bantuan", "mode": "contains"}))
        text = template("{user} {username} {server} {membercount} {unknown}", Obj(id=1, name="$&"), Obj(name="Server", member_count=5))
        self.assertEqual(text, "<@1> $& Server 5 {unknown}")

    def test_branding_and_validation(self):
        self.assertEqual(color("#abcdef"), 0xABCDEF)
        for value in ("pink", "#123", "0000000"):
            with self.assertRaises(UserError):
                color(value)
        for url in ("file:///etc/passwd", "http://example.com/a.png", "https://"):
            with self.assertRaises(UserError):
                image_url(url)
        embed = branded({"brand": {"color": 123, "banner": "https://example.com/banner.png"}}, colour=0, description="Halo")
        self.assertEqual(embed.color.value, 0)
        self.assertEqual(embed.image.url, "https://example.com/banner.png")
        with self.assertRaises(UserError):
            branded({"brand": {}}, description="x" * 6001)

    def test_roles_and_hierarchy(self):
        class Role:
            id = 2
            managed = False
            position = 1
            def __ge__(self, other):
                return self.position >= other
        role = Role()
        guild = Obj(id=1, owner_id=100)
        bot = Obj(guild_permissions=Obj(manage_roles=True), top_role=10)
        actor = Obj(id=3, top_role=5)
        validate_role(role, guild, bot, actor)
        role.position = 5
        with self.assertRaisesRegex(UserError, "Anda"):
            validate_role(role, guild, bot, actor)
        role.position = 10
        with self.assertRaisesRegex(UserError, "Bot perlu"):
            validate_role(role, guild, bot, actor)
        role.position, role.id = 1, 1
        with self.assertRaises(UserError):
            validate_role(role, guild, bot, actor)
        role.id, role.managed = 2, True
        with self.assertRaises(UserError):
            validate_role(role, guild, bot, actor)

    def test_ticket_topics_and_permissions(self):
        self.assertEqual(parse_ticket(ticket_topic(3, 4)), {"owner": 3, "staff": 4, "status": "open"})
        self.assertIsNone(parse_ticket("other-topic"))
        overwrites = ticket_overwrites("everyone", "bot", "owner", "staff")
        self.assertFalse(overwrites["everyone"].view_channel)
        self.assertTrue(all(overwrites[k].view_channel for k in ("bot", "owner", "staff")))
        self.assertIsNone(overwrites["owner"].manage_channels)

    def test_mention_requires_explicit_bot_mention(self):
        self.assertEqual(mention_prompt("<@123> halo", 123), "halo")
        self.assertEqual(mention_prompt("Halo <@!123>", 123), "Halo")
        self.assertIsNone(mention_prompt("<@999> halo", 123))
        self.assertIsNone(mention_prompt("halo semua", 123))
        self.assertEqual(mention_prompt("<@123>", 123), "")

    def test_long_answers_preserve_unicode_and_stay_within_discord_limit(self):
        text = "a😀\n" * 1600
        parts = chunks(text)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(p.encode("utf-16-le")) // 2 <= 1900 for p in parts))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bot = VarahBot(Settings(data_file=Path(self.directory.name) / "config.json"))
        self.addAsyncCleanup(self.bot.close)

    async def test_commands_serialize_and_restrict_installs(self):
        commands = self.bot.tree.get_commands()
        self.assertEqual({c.name for c in commands}, {"help", "ping", "brand", "autoresponder", "autorole", "embed", "ticket", "profile", "chat", "chat-reset", "ai"})
        for command in commands:
            data = command.to_dict(self.bot.tree)
            self.assertEqual(data["contexts"], [0])
            self.assertEqual(data["integration_types"], [0])
            if command.name not in {"help", "ping", "chat", "chat-reset"}:
                self.assertEqual(int(data["default_member_permissions"]), discord.Permissions(manage_guild=True).value)

    async def test_runtime_admin_check_cannot_be_bypassed_by_command_visibility(self):
        i = Obj(guild=Obj(id=1), command=self.bot.tree.get_command("brand").get_command("set"), permissions=discord.Permissions.none())
        with self.assertRaises(app_commands.MissingPermissions):
            await self.bot.tree.interaction_check(i)
        i.permissions.manage_guild = True
        self.assertTrue(await self.bot.tree.interaction_check(i))
        i.command = self.bot.tree.get_command("chat")
        i.permissions.manage_guild = False
        self.assertTrue(await self.bot.tree.interaction_check(i))
        i.guild = None
        with self.assertRaises(app_commands.AppCommandError):
            await self.bot.tree.interaction_check(i)

    async def test_profile_rejects_non_owner_before_reading_upload(self):
        command = self.bot.tree.get_command("profile")
        with self.assertRaisesRegex(UserError, "OWNER_IDS"):
            await command.callback(Obj(user=Obj(id=999)), avatar=MagicMock())

    async def test_chat_splits_reply_and_keeps_private_history_private(self):
        self.bot.chat = Obj(ask=AsyncMock(return_value="x" * 4000))
        i = Obj(guild_id=1, channel_id=2, user=Obj(id=3), channel=Obj(parent_id=None),
                response=Obj(defer=AsyncMock()), edit_original_response=AsyncMock(), followup=Obj(send=AsyncMock()))
        await self.bot.tree.get_command("chat").callback(i, "Halo", True)
        self.assertEqual(self.bot.chat.ask.call_args.args[0], (1, 2, 3, "private"))
        i.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertEqual(i.followup.send.await_count, 2)
        for call in i.followup.send.call_args_list:
            self.assertTrue(call.kwargs["ephemeral"])
            self.assertFalse(call.kwargs["allowed_mentions"].everyone)

    async def test_disabled_ai_does_not_call_ollama(self):
        self.bot.store.update(1, lambda c: c["ai"].update(enabled=False))
        self.bot.chat = Obj(ask=AsyncMock())
        i = Obj(guild_id=1, channel_id=2, channel=Obj(parent_id=None))
        with self.assertRaisesRegex(UserError, "dinonaktifkan"):
            await self.bot.tree.get_command("chat").callback(i, "Halo")
        self.bot.chat.ask.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
