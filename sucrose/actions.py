"""Validated bridge from natural language to the registered command callbacks."""
import json
import re

import discord

from .utils import UserError


class CommandContext:
    """Deliver existing command responses through either chat entry point."""
    def __init__(self, source):
        self.source = source
        self.guild = source.guild
        self.guild_id = source.guild.id
        self.channel = source.channel
        self.channel_id = source.channel.id
        self.user = source.user if hasattr(source, 'response') else source.author
        self.response = self
        self.followup = self

    def is_done(self):
        return True

    async def defer(self, **kwargs):
        pass

    async def send(self, content=None, **kwargs):
        kwargs.pop('thinking', None)
        kwargs['allowed_mentions'] = discord.AllowedMentions.none()
        if hasattr(self.source, 'response'):
            kwargs['ephemeral'] = True
            return await self.source.followup.send(content, **kwargs)
        kwargs.pop('ephemeral', None)
        return await self.source.reply(content, mention_author=False, **kwargs)

    send_message = send
    edit_original_response = send


class CommandActions:
    def __init__(self, bot, source):
        self.bot = bot
        self.context = CommandContext(source)
        # Chat recursion/reset during an active request is deliberately excluded.
        self.commands = {c.qualified_name: c for c in bot.tree.walk_commands()
                         if hasattr(c, 'parameters') and c.name not in {'chat', 'chat-reset'}}

    def catalog(self):
        return [{"command": name, "description": c.description, "arguments": {
            p.name: {"type": p.type.name, "required": p.required,
                     "choices": [v.value for v in p.choices],
                     "min": p.min_value, "max": p.max_value}
            for p in c.parameters}} for name, c in self.commands.items()]

    def convert(self, parameter, value):
        kind = parameter.type.name
        if value is None and not parameter.required:
            return parameter.default
        types = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool}
        if kind in types:
            if not isinstance(value, types[kind]) or (kind in {'integer', 'number'} and isinstance(value, bool)):
                raise UserError(f"Nilai {parameter.name} harus berupa {kind}.")
            size = len(value) if kind == 'string' else value
            if parameter.min_value is not None and size < parameter.min_value or parameter.max_value is not None and size > parameter.max_value:
                raise UserError(f"Nilai {parameter.name} di luar batas command.")
            if parameter.choices and value not in [c.value for c in parameter.choices]:
                raise UserError(f"Pilihan {parameter.name} tidak valid.")
            return value
        if not isinstance(value, str):
            raise UserError(f"Gunakan ID atau nama untuk {parameter.name}.")
        if kind == 'attachment':
            attachments = getattr(self.context.source, 'attachments', [])
            candidates = [a for a in attachments if str(a.id) == value or a.filename == value]
        else:
            pool = self.context.guild.roles if kind == 'role' else self.context.guild.channels
            identifier = re.sub(r'[<#@&>]', '', value)
            candidates = [obj for obj in pool if str(obj.id) == identifier or obj.name == value.lstrip('#')]
        if len(candidates) != 1:
            raise UserError(f"{parameter.name} tidak ditemukan atau namanya ambigu. Sertakan mention/ID yang tepat.")
        result = candidates[0]
        if kind == 'channel':
            if parameter.channel_types and result.type not in parameter.channel_types:
                raise UserError(f"Jenis channel {parameter.name} tidak sesuai.")
            if not result.permissions_for(self.context.user).view_channel:
                raise UserError("Anda tidak memiliki akses ke channel tersebut.")
        return result

    async def execute(self, plan):
        if not isinstance(plan, dict) or set(plan) != {'command', 'arguments'}:
            raise UserError("Rencana command AI tidak valid. Coba perjelas permintaan.")
        name, arguments = plan['command'], plan['arguments']
        if not isinstance(name, str) or name not in self.commands or not isinstance(arguments, dict):
            raise UserError("Command AI tidak dikenali.")
        command = self.commands[name]
        actor = await self.context.guild.fetch_member(self.context.user.id)
        self.context.user = actor
        if name not in {'help', 'ping'} and not actor.guild_permissions.manage_guild:
            raise UserError("Anda perlu izin Manage Server untuk menjalankan command ini.")
        parameters = {p.name: p for p in command.parameters}
        if arguments.keys() - parameters.keys():
            raise UserError("Argumen command AI tidak dikenali.")
        converted = {}
        for name, parameter in parameters.items():
            if name not in arguments:
                if parameter.required:
                    raise UserError(f"Lengkapi parameter {name} untuk /{command.qualified_name}.")
                converted[name] = parameter.default
            else:
                converted[name] = self.convert(parameter, arguments[name])
        await command.callback(self.context, **converted)
        return f"Selesai menjalankan /{command.qualified_name}."

    async def __call__(self, prompt):
        instruction = (
            'Pilih maksimal satu slash command untuk permintaan TERBARU pengguna. '
            'Balas JSON saja: {"command":"nama command","arguments":{...}} atau null '
            'jika hanya percakapan/pertanyaan/panduan, bukan permintaan eksekusi. '
            'Jangan mengarang ID, parameter, atau izin. Gunakan nama/mention/ID yang diberikan. '
            'Jika parameter wajib belum diberikan, hilangkan parameter itu. '
            'Untuk beberapa tindakan pilih hanya tindakan pertama. '
            'chat-reset harus dijalankan langsung lewat /chat-reset. '
            'Attachment hanya dapat dipilih dari lampiran pesan dengan ID/nama file. '
            'Daftar command: ' + json.dumps(self.catalog(), ensure_ascii=False)
        )
        raw = await self.bot.ollama.chat([{'role': 'system', 'content': instruction}, {'role': 'user', 'content': prompt}])
        try:
            plan = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise UserError("AI belum menghasilkan rencana yang valid. Perjelas permintaan atau gunakan slash command langsung.") from exc
        if plan is None:
            return None
        return await self.execute(plan)
