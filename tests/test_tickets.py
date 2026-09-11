import asyncio
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from varah.tickets import TicketService, OpenTicketView, CloseTicketView
from varah.utils import UserError, parse_ticket, ticket_topic


def fixture():
    category = MagicMock(spec=discord.CategoryChannel)
    category.id = 10
    category.permissions_for.return_value = discord.Permissions(view_channel=True, manage_channels=True, manage_roles=True)
    staff = MagicMock(spec=discord.Role)
    staff.id, staff.managed, staff.mention = 4, False, "<@&4>"
    staff.is_default.return_value = False
    member = MagicMock(spec=discord.Member)
    member.id, member.mention, member.roles = 3, "<@3>", []
    member.guild_permissions = discord.Permissions.none()
    room = MagicMock(spec=discord.TextChannel)
    room.id, room.topic, room.mention = 99, ticket_topic(3, 4), "<#99>"
    room.send, room.delete, room.set_permissions, room.edit = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    guild = Obj(id=1, default_role=MagicMock(spec=discord.Role), me=MagicMock(spec=discord.Member),
                fetch_channels=AsyncMock(return_value=[category]), fetch_roles=AsyncMock(return_value=[staff]),
                fetch_member=AsyncMock(return_value=member), create_text_channel=AsyncMock(return_value=room),
                fetch_channel=AsyncMock(return_value=room))
    i = Obj(guild=guild, guild_id=1, channel=room, channel_id=99, user=Obj(id=3),
            edit_original_response=AsyncMock(), message=Obj(edit=AsyncMock()), client=Obj(fetch_user=AsyncMock()))
    store = Obj(get=lambda _: {"brand": {}, "ticket": {"category": "10", "staff": "4"}})
    return Obj(service=TicketService(store), i=i, category=category, staff=staff, member=member, room=room)


class TicketTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_creates_private_room_and_close_control(self):
        f = fixture()
        await f.service.open(f.i)
        options = f.i.guild.create_text_channel.call_args.kwargs
        self.assertIs(options["category"], f.category)
        self.assertEqual(options["topic"], "varah-ticket:3:4:open")
        self.assertFalse(options["overwrites"][f.i.guild.default_role].view_channel)
        self.assertEqual(len(options["overwrites"]), 4)
        view = f.room.send.call_args.kwargs["view"]
        self.assertEqual(view.children[0].custom_id, "ticket:close")
        self.assertTrue(view.is_persistent())

    async def test_old_ticket_topic_prevents_duplicates_after_restart(self):
        f = fixture()
        f.i.guild.fetch_channels.return_value.append(f.room)
        await f.service.open(f.i)
        f.i.guild.create_text_channel.assert_not_awaited()
        self.assertIn("tiket aktif", f.i.edit_original_response.call_args.kwargs["content"])

    async def test_closed_ticket_does_not_block_new_ticket(self):
        f = fixture()
        f.room.topic = ticket_topic(3, 4, "closed")
        f.i.guild.fetch_channels.return_value.append(f.room)
        await f.service.open(f.i)
        f.i.guild.create_text_channel.assert_awaited_once()

    async def test_failed_initial_send_cleans_up_channel_and_releases_lock(self):
        f = fixture()
        f.room.send.side_effect = RuntimeError("send failed")
        with self.assertRaisesRegex(RuntimeError, "send failed"):
            await f.service.open(f.i)
        f.room.delete.assert_awaited_once()
        self.assertFalse(f.service.locks)

    async def test_missing_staff_and_category_permission_fail_before_creation(self):
        f = fixture()
        f.i.guild.fetch_roles.return_value = []
        with self.assertRaises(UserError):
            await f.service.open(f.i)
        f.i.guild.fetch_roles.return_value = [f.staff]
        f.category.permissions_for.return_value = discord.Permissions.none()
        with self.assertRaisesRegex(UserError, "Manage Channels"):
            await f.service.open(f.i)
        f.i.guild.create_text_channel.assert_not_awaited()

    async def test_simultaneous_clicks_are_locked(self):
        f = fixture()
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed():
            started.set()
            await release.wait()
            return [f.category]
        f.i.guild.fetch_channels.side_effect = delayed
        task = asyncio.create_task(f.service.open(f.i))
        await started.wait()
        try:
            with self.assertRaisesRegex(UserError, "sedang diproses"):
                await f.service.open(f.i)
        finally:
            release.set()
            await task
        f.i.guild.create_text_channel.assert_awaited_once()

    async def test_unauthorized_close_cannot_modify_ticket(self):
        f = fixture()
        f.i.user.id = 5
        with self.assertRaisesRegex(UserError, "Hanya pembuka"):
            await f.service.close(f.i)
        f.room.set_permissions.assert_not_awaited()
        f.room.edit.assert_not_awaited()

    async def test_owner_close_hides_room_and_preserves_history(self):
        f = fixture()
        await f.service.close(f.i)
        self.assertFalse(f.room.set_permissions.call_args.kwargs["view_channel"])
        self.assertEqual(parse_ticket(f.room.edit.call_args.kwargs["topic"])["status"], "closed")
        f.room.delete.assert_not_awaited()
        f.i.message.edit.assert_awaited_once_with(view=None)

    async def test_staff_can_close_ticket(self):
        f = fixture()
        f.i.user.id = 5
        f.member.roles = [f.staff]
        await f.service.close(f.i)
        f.room.edit.assert_awaited_once()

    async def test_views_keep_previous_javascript_custom_ids(self):
        f = fixture()
        for view, custom_id in ((OpenTicketView(f.service), "ticket:open"), (CloseTicketView(f.service), "ticket:close")):
            self.assertTrue(view.is_persistent())
            self.assertEqual(view.children[0].custom_id, custom_id)


if __name__ == "__main__":
    unittest.main()
