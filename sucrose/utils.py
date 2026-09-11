import re
from urllib.parse import urlparse

import discord


class UserError(discord.app_commands.AppCommandError):
    """An expected failure with a safe, user-facing explanation."""


def image_url(value: str | None) -> str | None:
    if not value:
        return None
    url = urlparse(value)
    if url.scheme != "https" or not url.hostname or url.username:
        raise UserError("URL gambar harus berupa URL HTTPS yang valid.")
    return value


def color(value: str) -> int:
    if not re.fullmatch(r"#?[\da-fA-F]{6}", value):
        raise UserError("Warna harus hex, misalnya #F5A9D0.")
    return int(value.lstrip("#"), 16)


def matches(content: str, rule: dict) -> bool:
    text, trigger = content.lower(), rule["trigger"].lower()
    if rule["mode"] == "contains":
        return trigger in text
    if rule["mode"] == "startswith":
        return text.startswith(trigger)
    return text == trigger


def template(text: str, member, guild) -> str:
    values = {"user": f"<@{member.id}>", "username": member.name, "server": guild.name, "membercount": str(guild.member_count)}
    return re.sub(r"\{(user|username|server|membercount)\}", lambda m: values[m[1]], text)


def branded(config: dict, *, title=None, description=None, banner=None, avatar=None, colour=None, footer=None) -> discord.Embed:
    brand = config["brand"]
    embed = discord.Embed(title=title, description=description, color=colour if colour is not None else brand.get("color", 0xF5A9D0))
    if banner or brand.get("banner"):
        embed.set_image(url=banner or brand["banner"])
    if avatar or brand.get("avatar"):
        embed.set_thumbnail(url=avatar or brand["avatar"])
    if brand.get("name"):
        embed.set_author(name=brand["name"], icon_url=brand.get("avatar"))
    if footer or brand.get("footer"):
        embed.set_footer(text=footer or brand["footer"])
    if len(embed) > 6000:
        raise UserError("Total teks embed melebihi 6.000 karakter.")
    return embed


def validate_role(role, guild, bot, actor) -> None:
    if role.id == guild.id or role.managed:
        raise UserError("Role @everyone atau role integrasi tidak bisa dipakai.")
    if not bot.guild_permissions.manage_roles or role >= bot.top_role:
        raise UserError("Bot perlu Manage Roles dan posisi role bot harus di atas role target.")
    if actor.id != guild.owner_id and role >= actor.top_role:
        raise UserError("Role target harus di bawah role tertinggi Anda.")


def parse_ticket(topic: str | None) -> dict | None:
    match = re.fullmatch(r"(?:sucrose|varah)-ticket:(\d+):(\d+):(open|closed)", topic or "")
    return {"owner": int(match[1]), "staff": int(match[2]), "status": match[3]} if match else None


def ticket_topic(owner: int, staff: int, status="open") -> str:
    return f"sucrose-ticket:{owner}:{staff}:{status}"


def ticket_overwrites(everyone, bot, owner, staff) -> dict:
    access = dict(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
    return {
        everyone: discord.PermissionOverwrite(view_channel=False),
        bot: discord.PermissionOverwrite(**access, manage_channels=True, manage_roles=True),
        owner: discord.PermissionOverwrite(**access),
        staff: discord.PermissionOverwrite(**access),
    }


def chat_key(guild_id: int, channel_id: int, user_id: int, private: bool = False) -> tuple:
    # Private slash chats never feed history into public mentions or public /chat.
    return (guild_id, channel_id, user_id, "private" if private else "public")


def mention_prompt(content: str, bot_id: int) -> str | None:
    pattern = rf"<@!?{bot_id}>"
    return re.sub(pattern, "", content).strip() if re.search(pattern, content) else None


def chunks(text: str, limit=1900) -> list[str]:
    # Count UTF-16 code units too: Discord snowflake messages can include emoji.
    result, part, size = [], [], 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if size + units > limit:
            result.append("".join(part))
            part, size = [], 0
        part.append(char)
        size += units
    if part:
        result.append("".join(part))
    return result or ["(Respons kosong)"]
