import logging

import discord
from discord import app_commands

from .utils import UserError

log = logging.getLogger("sucrose")


async def report_error(interaction: discord.Interaction, error: Exception) -> None:
    error = getattr(error, "original", error)
    if isinstance(error, UserError):
        message = str(error)
    elif isinstance(error, app_commands.MissingPermissions):
        message = "Perintah ini membutuhkan izin Manage Server."
    elif isinstance(error, app_commands.CheckFailure):
        message = "Anda tidak dapat menggunakan perintah ini di sini."
    elif isinstance(error, discord.HTTPException):
        message = f"Discord menolak operasi (kode {error.code}). Periksa izin bot, hierarki role, dan konfigurasi."
        log.warning("Discord HTTP error: %s", error.code)
    else:
        message = "Terjadi kesalahan internal. Periksa terminal bot."
        log.error("Unhandled %s", type(error).__name__, exc_info=(type(error), error, error.__traceback__))
    try:
        if interaction.response.is_done():
            await interaction.followup.send(f"Tidak berhasil: {message}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(f"Tidak berhasil: {message}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.warning("Tidak dapat mengirim pesan kesalahan interaksi.")
