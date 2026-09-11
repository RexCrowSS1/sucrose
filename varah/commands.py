from io import BytesIO
from typing import Literal

import discord
from discord import app_commands

from .ai import check_access
from .tickets import OpenTicketView
from .utils import UserError, branded, chat_key, chunks, color as parse_color, image_url, validate_role


async def respond(i, *args, **kwargs):
    if i.response.is_done():
        return await i.followup.send(*args, **kwargs)
    return await i.response.send_message(*args, **kwargs)


async def send_target(i: discord.Interaction, channel: discord.TextChannel, **payload):
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != i.guild_id:
        raise UserError("Pilih channel teks server yang valid.")
    actor = await i.guild.fetch_member(i.user.id)
    user_permissions = channel.permissions_for(actor)
    permissions = channel.permissions_for(i.guild.me)
    if not (user_permissions.view_channel and user_permissions.send_messages):
        raise UserError("Anda tidak memiliki akses mengirim pesan ke channel tujuan.")
    if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
        raise UserError("Bot perlu View Channel, Send Messages, dan Embed Links di channel tujuan.")
    return await channel.send(**payload, allowed_mentions=discord.AllowedMentions.none())


def register_commands(bot) -> None:
    tree, store = bot.tree, bot.store

    def group(name, description):
        result = app_commands.Group(name=name, description=description, guild_only=True, default_permissions=discord.Permissions(manage_guild=True))
        tree.add_command(result)
        return result

    @tree.command(name="help", description="Panduan bot Varah")
    async def help_command(i: discord.Interaction):
        await respond(i, embed=branded(store.get(i.guild_id), title="Varah • Panduan Bot", description=(
            "**Chat AI**\n`/chat pesan:...` atau mention bot untuk ngobrol.\n"
            "`/chat privat:true` — jawaban hanya terlihat oleh Anda.\n"
            "`/chat-reset` — hapus ingatan chat Anda di channel ini.\n"
            "`/ping` — cek koneksi.\n\n"
            "**Admin (Manage Server)**\n"
            "`/brand set|preview|reset` — branding embed\n"
            "`/autoresponder add|remove|list` — balasan otomatis\n"
            "`/autorole add|remove|list` — role manusia/bot/semua\n"
            "`/embed` — kirim embed custom\n"
            "`/ticket setup` lalu `/ticket panel` — tiket privat\n"
            "`/profile` — avatar/banner global (pemilik bot)\n"
            "`/ai setup|status` — pengaturan chat AI\n\n"
            "Variabel autoresponder: `{user}`, `{username}`, `{server}`, `{membercount}`."
        )), ephemeral=True)

    @tree.command(name="ping", description="Cek koneksi bot")
    async def ping(i: discord.Interaction):
        await respond(i, f"Pong! WebSocket: {bot.latency * 1000:.0f} ms.", ephemeral=True)

    brand = group("brand", "Atur tampilan embed bot di server ini")

    @brand.command(name="set", description="Ubah branding server")
    async def brand_set(i: discord.Interaction, name: app_commands.Range[str, 1, 100] | None = None,
                        color: app_commands.Range[str, 6, 7] | None = None,
                        banner: app_commands.Range[str, 1, 1000] | None = None,
                        avatar: app_commands.Range[str, 1, 1000] | None = None,
                        footer: app_commands.Range[str, 1, 200] | None = None):
        patch = {k: v for k, v in {"name": name, "color": parse_color(color) if color else None,
                 "banner": image_url(banner), "avatar": image_url(avatar), "footer": footer}.items() if v is not None}
        if not patch:
            raise UserError("Isi minimal satu pilihan branding.")
        await bot.save_config(i, lambda c: c["brand"].update(patch))
        await respond(i, embed=branded(store.get(i.guild_id), title="Preview Branding", description="Tampilan embed bot di server ini."), ephemeral=True)

    @brand.command(name="preview", description="Lihat branding saat ini")
    async def brand_preview(i: discord.Interaction):
        await respond(i, embed=branded(store.get(i.guild_id), title="Preview Branding", description="Tampilan embed bot di server ini."), ephemeral=True)

    @brand.command(name="reset", description="Kembalikan branding default")
    async def brand_reset(i: discord.Interaction):
        await bot.save_config(i, lambda c: c.update(brand={}))
        await respond(i, "Branding dikembalikan ke default.", ephemeral=True)

    responders = group("autoresponder", "Kelola balasan otomatis")

    @responders.command(name="add", description="Tambah atau ganti respons dengan trigger yang sama")
    async def responder_add(i: discord.Interaction, trigger: app_commands.Range[str, 1, 100],
                            response: app_commands.Range[str, 1, 1500],
                            mode: Literal["exact", "contains", "startswith"] = "exact",
                            channel: discord.TextChannel | None = None, embed: bool = False,
                            cooldown: app_commands.Range[int, 1, 3600] = 5):
        trigger = trigger.strip().lower()
        if not trigger or not response.strip():
            raise UserError("Trigger dan respons tidak boleh kosong.")
        rules = store.get(i.guild_id)["responders"]
        if len(rules) >= 100 and not any(r["trigger"] == trigger for r in rules):
            raise UserError("Maksimal 100 autoresponder per server.")
        rule = {"trigger": trigger, "response": response.replace("\\n", "\n"), "mode": mode,
                "channel": str(channel.id) if channel else None, "embed": embed, "cooldown": cooldown}
        def update(c):
            c["responders"] = [r for r in c["responders"] if r["trigger"] != trigger] + [rule]
        await bot.save_config(i, update)
        await respond(i, "Autoresponder disimpan. Maksimal satu balasan per pesan; pesan bot diabaikan.", ephemeral=True)

    @responders.command(name="remove", description="Hapus respons")
    async def responder_remove(i: discord.Interaction, trigger: app_commands.Range[str, 1, 100]):
        trigger = trigger.strip().lower()
        if not any(r["trigger"] == trigger for r in store.get(i.guild_id)["responders"]):
            raise UserError("Trigger tidak ditemukan.")
        def update(c):
            c["responders"] = [r for r in c["responders"] if r["trigger"] != trigger]
        await bot.save_config(i, update)
        await respond(i, "Autoresponder dihapus.", ephemeral=True)

    @responders.command(name="list", description="Daftar semua trigger")
    async def responder_list(i: discord.Interaction):
        rules = store.get(i.guild_id)["responders"]
        if not rules:
            await respond(i, "Belum ada autoresponder.", ephemeral=True)
            return
        lines = [f"{n}. {r['trigger']} • {r['mode']} • {r['cooldown']}s • {r['channel'] or 'semua channel'} • {'embed' if r['embed'] else 'teks'}" for n, r in enumerate(rules, 1)]
        await respond(i, f"{len(rules)} autoresponder tersimpan:", file=discord.File(BytesIO("\n".join(lines).encode()), filename="autoresponders.txt"), ephemeral=True)

    roles = group("autorole", "Role otomatis saat anggota baru bergabung")

    @roles.command(name="add", description="Tambah role otomatis")
    async def role_add(i: discord.Interaction, target: Literal["human", "bot", "all"], role: discord.Role):
        await i.response.defer(ephemeral=True)
        actor = await i.guild.fetch_member(i.user.id)
        validate_role(role, i.guild, i.guild.me, actor)
        def update(c):
            c["roles"][target] = list(dict.fromkeys([*c["roles"][target], str(role.id)]))
        await bot.save_config(i, update)
        await i.edit_original_response(content=f"Role otomatis {target} diperbarui. Berlaku untuk anggota baru.")

    @roles.command(name="remove", description="Hapus aturan role otomatis")
    async def role_remove(i: discord.Interaction, target: Literal["human", "bot", "all"], role: discord.Role):
        def update(c):
            c["roles"][target] = [r for r in c["roles"][target] if str(r) != str(role.id)]
        await bot.save_config(i, update)
        await respond(i, f"Role otomatis {target} diperbarui.", ephemeral=True)

    @roles.command(name="list", description="Lihat pengaturan role otomatis")
    async def role_list(i: discord.Interaction):
        text = "\n".join(f"**{kind}**: " + (", ".join(f"<@&{role}>" for role in ids) or "belum diatur") for kind, ids in store.get(i.guild_id)["roles"].items())
        if len(text) > 1900:
            await respond(i, file=discord.File(BytesIO(text.encode()), filename="autoroles.txt"), ephemeral=True)
        else:
            await respond(i, text, ephemeral=True)

    @tree.command(name="embed", description="Kirim embed custom ke channel")
    @app_commands.default_permissions(manage_guild=True)
    async def embed_command(i: discord.Interaction, description: app_commands.Range[str, 1, 3500],
                            channel: discord.TextChannel | None = None,
                            title: app_commands.Range[str, 1, 256] | None = None,
                            banner: app_commands.Range[str, 1, 1000] | None = None,
                            avatar: app_commands.Range[str, 1, 1000] | None = None,
                            color: app_commands.Range[str, 6, 7] | None = None,
                            footer: app_commands.Range[str, 1, 200] | None = None):
        await i.response.defer(ephemeral=True)
        embed = branded(store.get(i.guild_id), title=title, description=description.replace("\\n", "\n"),
                        banner=image_url(banner), avatar=image_url(avatar), colour=parse_color(color) if color else None, footer=footer)
        message = await send_target(i, channel or i.channel, embed=embed)
        await i.edit_original_response(content=f"Embed terkirim: {message.jump_url}")

    tickets = group("ticket", "Konfigurasi tiket privat")

    @tickets.command(name="setup", description="Atur kategori dan role staf")
    async def ticket_setup(i: discord.Interaction, category: discord.CategoryChannel, staff: discord.Role):
        if staff.is_default() or staff.managed:
            raise UserError("Gunakan role staf khusus, bukan @everyone atau role integrasi.")
        perms = category.permissions_for(i.guild.me)
        if not (perms.view_channel and perms.manage_channels and perms.manage_roles):
            raise UserError("Bot perlu View Channel, Manage Channels, dan Manage Roles di kategori tiket.")
        await bot.save_config(i, lambda c: c.update(ticket={"category": str(category.id), "staff": str(staff.id)}))
        await respond(i, "Tiket dikonfigurasi. Jalankan /ticket panel untuk mengirim tombol.", ephemeral=True)

    @tickets.command(name="panel", description="Kirim panel tombol untuk membuka tiket")
    async def ticket_panel(i: discord.Interaction, channel: discord.TextChannel,
                           title: app_commands.Range[str, 1, 256] = "Pusat Bantuan",
                           description: app_commands.Range[str, 1, 3500] = "Butuh bantuan? Klik tombol untuk berbicara privat dengan staf."):
        if not store.get(i.guild_id)["ticket"]:
            raise UserError("Jalankan /ticket setup terlebih dahulu.")
        await i.response.defer(ephemeral=True)
        message = await send_target(i, channel, embed=branded(store.get(i.guild_id), title=title, description=description.replace("\\n", "\n")), view=OpenTicketView(bot.tickets))
        await i.edit_original_response(content=f"Panel tiket terkirim: {message.jump_url}")

    @tree.command(name="profile", description="Pemilik bot: ubah avatar/banner global akun bot")
    @app_commands.default_permissions(manage_guild=True)
    async def profile(i: discord.Interaction, avatar: discord.Attachment | None = None, banner: discord.Attachment | None = None):
        if i.user.id not in bot.settings.owner_ids:
            raise UserError("Hanya pemilik di OWNER_IDS yang dapat mengubah profil global bot.")
        if not avatar and not banner:
            raise UserError("Upload avatar dan/atau banner.")
        await i.response.defer(ephemeral=True)
        images = {}
        for key, attachment in (("avatar", avatar), ("banner", banner)):
            if attachment:
                if attachment.content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"} or attachment.size > 8 * 1024 * 1024:
                    raise UserError("Gunakan gambar PNG/JPG/GIF/WebP maksimal 8 MB.")
                images[key] = await attachment.read()
                if len(images[key]) > 8 * 1024 * 1024:
                    raise UserError("Gambar terlalu besar.")
        try:
            await bot.user.edit(**images)
        except ValueError as exc:
            raise UserError("Format gambar tidak didukung Discord. Upload PNG/JPG/GIF/WebP yang valid.") from exc
        await i.edit_original_response(content="Profil bot diperbarui untuk semua server. Discord membatasi frekuensi perubahan profil.")

    @tree.command(name="chat", description="Ngobrol dengan Varah melalui Ollama lokal")
    @app_commands.describe(pesan="Pesan untuk Varah", privat="Jawaban hanya terlihat oleh Anda (default: publik)")
    async def chat(i: discord.Interaction, pesan: app_commands.Range[str, 1, 2000], privat: bool = False):
        config = store.get(i.guild_id)
        check_access(config, i.channel_id, getattr(i.channel, "parent_id", None))
        await i.response.defer(ephemeral=privat, thinking=True)
        answer = await bot.chat.ask(chat_key(i.guild_id, i.channel_id, i.user.id, privat), pesan, config["ai"].get("system_prompt"))
        parts = chunks(answer)
        await i.edit_original_response(content=parts[0], allowed_mentions=discord.AllowedMentions.none())
        for part in parts[1:]:
            await i.followup.send(part, ephemeral=privat, allowed_mentions=discord.AllowedMentions.none())

    @tree.command(name="chat-reset", description="Hapus ingatan chat publik dan privat Anda di channel ini")
    async def chat_reset(i: discord.Interaction):
        bot.chat.reset(i.guild_id, i.channel_id, i.user.id)
        await respond(i, "Ingatan chat Anda di channel ini dihapus. Pesan Discord yang sudah terkirim tetap ada.", ephemeral=True)

    ai = group("ai", "Pengaturan chat Ollama di server ini")

    @ai.command(name="setup", description="Aktifkan AI, batasi channel, atau atur kepribadian")
    @app_commands.describe(enabled="Aktif/nonaktifkan chat AI", channel="Batasi chat ke channel ini beserta thread-nya",
                           all_channels="Hapus pembatasan channel", system_prompt="Instruksi kepribadian Varah di server ini",
                           reset_prompt="Kembalikan kepribadian default dari .env")
    async def ai_setup(i: discord.Interaction, enabled: bool | None = None, channel: discord.TextChannel | None = None,
                       all_channels: bool = False, system_prompt: app_commands.Range[str, 1, 1500] | None = None,
                       reset_prompt: bool = False):
        if channel and all_channels:
            raise UserError("Pilih channel atau all_channels, tidak keduanya.")
        if system_prompt and reset_prompt:
            raise UserError("Isi system_prompt atau reset_prompt, tidak keduanya.")
        if enabled is None and not channel and not all_channels and not system_prompt and not reset_prompt:
            raise UserError("Isi minimal satu pengaturan AI.")
        def update(c):
            if enabled is not None:
                c["ai"]["enabled"] = enabled
            if channel or all_channels:
                c["ai"]["channel"] = str(channel.id) if channel else None
            if system_prompt:
                c["ai"]["system_prompt"] = system_prompt
            if reset_prompt:
                c["ai"].pop("system_prompt", None)
        await bot.save_config(i, update)
        await respond(i, "Pengaturan AI disimpan. Lihat /ai status.", ephemeral=True)

    @ai.command(name="status", description="Periksa pengaturan AI dan koneksi Ollama")
    async def ai_status(i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        config = store.get(i.guild_id)["ai"]
        if not bot.settings.ai_enabled:
            await i.edit_original_response(content="AI dinonaktifkan pada hosting (AI_ENABLED=false). Fitur bot lainnya tetap aktif.")
            return
        try:
            models = await bot.ollama.models()
            model = bot.settings.ollama_model
            available = model in models or (":" not in model and f"{model}:latest" in models)
            status = "terhubung; model tersedia" if available else "terhubung; model belum tersedia"
        except UserError as exc:
            status = str(exc)
        await i.edit_original_response(content=(
            f"AI: {'aktif' if config['enabled'] else 'nonaktif'}\n"
            f"Channel: {'<#' + config['channel'] + '>' if config['channel'] else 'semua channel'}\n"
            f"Model: {bot.settings.ollama_model}\nOllama: {status}\n"
            f"Ingatan: {bot.settings.history_turns} putaran, kedaluwarsa setelah {bot.settings.history_ttl // 60} menit tidak aktif."
        ))
