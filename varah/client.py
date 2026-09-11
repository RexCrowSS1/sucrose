import logging
import time

import aiohttp
import discord
from discord import app_commands

from .ai import ChatService, OllamaClient, check_access
from .commands import register_commands
from .config import Settings
from .errors import report_error
from .store import Store
from .tickets import CloseTicketView, OpenTicketView, TicketService
from .utils import UserError, branded, chat_key, chunks, matches, mention_prompt, template

log = logging.getLogger("varah")
PUBLIC_COMMANDS = {"help", "ping", "chat", "chat-reset"}


class VarahTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            raise UserError("Gunakan bot di dalam server.")
        command = interaction.command
        if command is None:
            raise UserError("Command tidak ditemukan. Jalankan python bot.py --sync untuk memperbarui command.")
        root = command.root_parent or command
        if root.name not in PUBLIC_COMMANDS and not interaction.permissions.manage_guild:
            raise app_commands.MissingPermissions(["manage_guild"])
        return True

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


class VarahBot(discord.Client):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents, application_id=settings.application_id, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        if settings.database_url:
            from .postgres import PostgresStore
            self.store = PostgresStore(settings.database_url)
        else:
            self.store = Store(settings.data_file)
        self.tree = VarahTree(self, allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False),
                              allowed_installs=app_commands.AppInstallationType(guild=True, user=False))
        self.tickets = TicketService(self.store)
        self.session: aiohttp.ClientSession | None = None
        self.ollama: OllamaClient | None = None
        self.chat: ChatService | None = None
        self.response_cooldowns = {}
        register_commands(self)

    async def setup_hook(self):
        if self.settings.database_url:
            await self.store.initialize()
        self.session = aiohttp.ClientSession()
        self.ollama = OllamaClient(self.session, self.settings)
        self.chat = ChatService(self.ollama, self.settings)
        self.add_view(OpenTicketView(self.tickets))
        self.add_view(CloseTicketView(self.tickets))

    async def save_config(self, interaction, change):
        if self.settings.database_url:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            return await self.store.update_async(interaction.guild_id, change)
        return self.store.update(interaction.guild_id, change)

    async def sync_commands(self):
        guild = discord.Object(id=self.settings.guild_id) if self.settings.guild_id else None
        if guild:
            self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("%s command terdaftar (%s).", len(synced), self.settings.guild_id or "global")

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    async def on_ready(self):
        log.info("Varah aktif sebagai %s di %s server. Model: %s", self.user, len(self.guilds), self.settings.ollama_model)

    async def on_member_join(self, member: discord.Member):
        config = self.store.get(member.guild.id)["roles"]
        ids = dict.fromkeys([*config["all"], *config["bot" if member.bot else "human"]])
        for role_id in ids:
            role = member.guild.get_role(int(role_id))
            if not role or role.managed or role.is_default() or role >= member.guild.me.top_role:
                continue
            try:
                await member.add_roles(role, reason="Varah: role otomatis anggota baru")
            except discord.HTTPException as exc:
                log.warning("Autorole gagal, role=%s kode=%s", role_id, exc.code)

    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or message.webhook_id or message.is_system():
            return
        config = self.store.get(message.guild.id)
        prompt = mention_prompt(message.content, self.user.id)
        if prompt is not None:
            try:
                check_access(config, message.channel.id, getattr(message.channel, "parent_id", None))
                if not prompt:
                    raise UserError("Tulis pesan setelah mention, misalnya @Varah halo! Anda juga bisa memakai /chat.")
                async with message.channel.typing():
                    answer = await self.chat.ask(chat_key(message.guild.id, message.channel.id, message.author.id), prompt, config["ai"].get("system_prompt"))
                for index, part in enumerate(chunks(answer)):
                    if index == 0:
                        await message.reply(part, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                    else:
                        await message.channel.send(part, allowed_mentions=discord.AllowedMentions.none())
            except UserError as exc:
                try:
                    await message.reply(str(exc), mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    log.warning("Tidak dapat mengirim balasan chat di channel %s.", message.channel.id)
            except discord.HTTPException as exc:
                log.warning("Pengiriman chat gagal, kode=%s", exc.code)
            return
        rule = next((r for r in config["responders"] if (not r["channel"] or str(r["channel"]) == str(message.channel.id)) and matches(message.content, r)), None)
        if not rule:
            return
        now = time.monotonic()
        self.response_cooldowns = {k: expiry for k, expiry in self.response_cooldowns.items() if expiry > now}
        key = (message.guild.id, message.author.id, rule["trigger"])
        if key in self.response_cooldowns:
            return
        self.response_cooldowns[key] = now + rule["cooldown"]
        response = template(rule["response"], message.author, message.guild)
        try:
            if rule["embed"]:
                await message.reply(embed=branded(config, description=chunks(response, 4000)[0]), mention_author=False)
            else:
                await message.reply(chunks(response, 2000)[0], mention_author=False)
        except (discord.HTTPException, UserError) as exc:
            log.warning("Autoresponder gagal: %s", type(exc).__name__)
