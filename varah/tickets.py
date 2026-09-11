import logging

import discord

from .errors import report_error
from .utils import UserError, branded, parse_ticket, ticket_overwrites, ticket_topic

log = logging.getLogger("varah.tickets")


class TicketService:
    def __init__(self, store):
        self.store = store
        self.locks = set()

    async def open(self, i: discord.Interaction) -> None:
        if not i.guild:
            raise UserError("Gunakan tiket di dalam server.")
        key = (i.guild_id, i.user.id)
        if key in self.locks:
            raise UserError("Tiket sedang diproses. Tunggu sebentar.")
        self.locks.add(key)
        try:
            config = self.store.get(i.guild_id)
            settings = config["ticket"]
            if not settings:
                raise UserError("Tiket belum dikonfigurasi oleh admin.")
            channels = await i.guild.fetch_channels()
            for channel in channels:
                ticket = parse_ticket(getattr(channel, "topic", None))
                if ticket and ticket["owner"] == i.user.id and ticket["status"] == "open":
                    await i.edit_original_response(content=f"Anda masih memiliki tiket aktif: {channel.mention}.")
                    return
            category = next((c for c in channels if c.id == int(settings["category"])), None)
            staff = discord.utils.get(await i.guild.fetch_roles(), id=int(settings["staff"]))
            if not isinstance(category, discord.CategoryChannel) or not staff or staff.is_default() or staff.managed:
                raise UserError("Kategori/role staf tidak valid. Minta admin menjalankan /ticket setup.")
            me = i.guild.me
            perms = category.permissions_for(me)
            if not all((perms.view_channel, perms.manage_channels, perms.manage_roles)):
                raise UserError("Bot perlu View Channel, Manage Channels, dan Manage Roles di kategori tiket.")
            owner = await i.guild.fetch_member(i.user.id)
            room = await i.guild.create_text_channel(
                name=f"ticket-{i.user.id}", category=category,
                topic=ticket_topic(i.user.id, staff.id),
                overwrites=ticket_overwrites(i.guild.default_role, me, owner, staff),
                reason=f"Tiket dibuka oleh {i.user.id}",
            )
            try:
                await room.send(
                    content=f"{owner.mention} {staff.mention}",
                    allowed_mentions=discord.AllowedMentions(users=[owner], roles=[staff], everyone=False, replied_user=False),
                    embed=branded(config, title="Tiket Bantuan", description="Silakan jelaskan masalah Anda. Tim staf akan membantu.\nTombol tutup mengarsipkan percakapan untuk staf."),
                    view=CloseTicketView(self),
                )
            except Exception:
                try:
                    await room.delete(reason="Pembuatan tiket gagal")
                except discord.HTTPException:
                    log.error("Gagal membersihkan channel tiket %s", room.id)
                raise
            await i.edit_original_response(content=f"Tiket Anda sudah dibuat: {room.mention}")
        finally:
            self.locks.discard(key)

    async def close(self, i: discord.Interaction) -> None:
        if not i.guild or not isinstance(i.channel, discord.TextChannel):
            raise UserError("Tombol ini hanya berlaku di channel tiket.")
        key = ("close", i.channel_id)
        if key in self.locks:
            raise UserError("Tiket sedang diproses. Tunggu sebentar.")
        self.locks.add(key)
        try:
            # Fetch current state rather than relying on a stale topic in cache.
            room = await i.guild.fetch_channel(i.channel_id)
            ticket = parse_ticket(room.topic)
            if not ticket:
                raise UserError("Channel ini bukan tiket Varah.")
            member = await i.guild.fetch_member(i.user.id)
            if not (i.user.id == ticket["owner"] or any(r.id == ticket["staff"] for r in member.roles) or member.guild_permissions.manage_guild):
                raise UserError("Hanya pembuka tiket atau staf yang dapat menutupnya.")
            if ticket["status"] == "closed":
                await i.edit_original_response(content="Tiket sudah ditutup.")
                return
            try:
                owner = await i.guild.fetch_member(ticket["owner"])
            except discord.NotFound:
                # Member may have left; fetch a User to retain a member overwrite.
                owner = await i.client.fetch_user(ticket["owner"])
            await room.set_permissions(owner, view_channel=False, send_messages=False, reason="Tiket ditutup")
            await room.edit(name=f"closed-{ticket['owner']}", topic=ticket_topic(ticket["owner"], ticket["staff"], "closed"))
            await i.edit_original_response(content="Tiket ditutup. Riwayat tetap tersimpan untuk staf.")
            try:
                if i.message:
                    await i.message.edit(view=None)
                await room.send(f"Tiket ditutup oleh <@{i.user.id}>. Staf dapat menghapus channel setelah riwayat tidak diperlukan lagi.", allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                log.warning("Tiket %s ditutup, tetapi notifikasi gagal.", room.id)
        finally:
            self.locks.discard(key)


class TicketView(discord.ui.View):
    def __init__(self, service: TicketService):
        super().__init__(timeout=None)
        self.service = service

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


class OpenTicketView(TicketView):
    @discord.ui.button(label="Buka Tiket", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.service.open(interaction)


class CloseTicketView(TicketView):
    @discord.ui.button(label="Tutup Tiket", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.service.close(interaction)
