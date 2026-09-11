import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import json
import time

import aiohttp

from .config import Settings
from .utils import UserError


class OllamaClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings):
        self.session = session
        self.settings = settings

    async def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            async with self.session.request(
                method, f"{self.settings.ollama_url}{path}", json=payload,
                timeout=aiohttp.ClientTimeout(total=self.settings.ollama_timeout),
                allow_redirects=False,
                headers={"Authorization": f"Bearer {self.settings.ollama_api_key}"} if self.settings.ollama_api_key else {},
            ) as response:
                if response.status == 404:
                    raise UserError("Layanan AI belum siap. Coba lagi nanti.")
                if response.status != 200:
                    raise UserError("Layanan AI menolak permintaan. Coba lagi nanti.")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise UserError("Respons AI terlalu besar. Coba pertanyaan lebih singkat.")
                data = json.loads(body)
                if not isinstance(data, dict) or data.get("error"):
                    raise UserError("Layanan AI mengalami kesalahan. Coba lagi nanti.")
                return data
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise UserError("Layanan AI terlalu lama merespons. Coba lagi nanti.") from exc
        except aiohttp.ClientError as exc:
            raise UserError("Tidak dapat menghubungi layanan AI. Coba lagi nanti.") from exc
        except (ValueError, UnicodeError) as exc:
            raise UserError("Layanan AI mengirim respons yang tidak valid.") from exc

    async def models(self) -> list[str]:
        data = await self.request("GET", "/api/tags")
        models = data.get("models")
        if not isinstance(models, list):
            raise UserError("Layanan AI mengirim daftar model yang tidak valid.")
        return [m["name"] for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)]

    async def chat(self, messages: list[dict]) -> str:
        data = await self.request("POST", "/api/chat", {
            "model": self.settings.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 512, "num_ctx": 4096, "temperature": 0.7},
        })
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise UserError("AI mengirim respons kosong. Coba pertanyaan lain.")
        if len(content) > 6000:
            content = content[:5900] + "\n\n[Jawaban dipotong. Minta bagian berikutnya bila diperlukan.]"
        return content.strip()


@dataclass
class Conversation:
    messages: list[dict] = field(default_factory=list)
    touched: float = 0
    system: str = ""


class ChatService:
    def __init__(self, ollama: OllamaClient, settings: Settings, clock=time.monotonic):
        self.ollama, self.settings, self.clock = ollama, settings, clock
        self.histories: OrderedDict[tuple, Conversation] = OrderedDict()
        self.cooldowns: dict[tuple, float] = {}
        self.active: set[tuple] = set()
        self.active_users: set[tuple] = set()

    def prune(self) -> None:
        now = self.clock()
        for key, conversation in list(self.histories.items()):
            if now - conversation.touched >= self.settings.history_ttl:
                del self.histories[key]
        self.cooldowns = {k: expiry for k, expiry in self.cooldowns.items() if expiry > now}

    async def ask(self, key: tuple, prompt: str, system: str | None = None) -> str:
        if not self.settings.ai_enabled:
            raise UserError("Chat AI belum diaktifkan pada hosting ini (AI_ENABLED=false).")
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 2000:
            raise UserError("Pesan chat harus berisi 1–2.000 karakter.")
        self.prune()
        user_key = (key[0], key[2])
        if user_key in self.active_users:
            raise UserError("Pesan Anda sebelumnya masih diproses. Tunggu jawabannya dahulu.")
        if len(self.active) >= self.settings.max_concurrent:
            raise UserError("Chat sedang sibuk. Coba lagi sebentar.")
        remaining = self.cooldowns.get(user_key, 0) - self.clock()
        if remaining > 0:
            raise UserError(f"Tunggu {int(remaining) + 1} detik sebelum chat lagi.")
        # No await between checks and reservation; concurrent requests cannot race.
        self.active.add(key)
        self.active_users.add(user_key)
        self.cooldowns[user_key] = self.clock() + self.settings.cooldown
        try:
            system = system or self.settings.system_prompt
            old = self.histories.get(key)
            history = list(old.messages) if old and old.system == system else []
            history = history[-2 * (self.settings.history_turns - 1):] if self.settings.history_turns > 1 else []
            # Bound context independently of turn count; discard whole user/assistant pairs.
            while history and sum(len(m["content"]) for m in history) + len(prompt) > 10000:
                history = history[2:]
            question = {"role": "user", "content": prompt}
            answer = await self.ollama.chat([{"role": "system", "content": system}, *history, question])
            history.extend([question, {"role": "assistant", "content": answer}])
            self.histories[key] = Conversation(history[-self.settings.history_turns * 2:], self.clock(), system)
            self.histories.move_to_end(key)
            while len(self.histories) > self.settings.max_conversations:
                self.histories.popitem(last=False)
            return answer
        finally:
            self.active.discard(key)
            self.active_users.discard(user_key)

    def reset(self, guild_id: int, channel_id: int, user_id: int) -> int:
        prefix = (guild_id, channel_id, user_id)
        if any(k[:3] == prefix for k in self.active):
            raise UserError("Tunggu jawaban yang sedang diproses sebelum menghapus ingatan chat.")
        keys = [key for key in self.histories if key[:3] == prefix]
        for key in keys:
            del self.histories[key]
        return len(keys)


def check_access(config: dict, channel_id: int, parent_id: int | None = None) -> None:
    ai = config.get("ai", {})
    if not ai.get("enabled", True):
        raise UserError("Chat AI dinonaktifkan di server ini oleh admin.")
    allowed = ai.get("channel")
    if allowed and str(allowed) not in {str(channel_id), str(parent_id)}:
        raise UserError(f"Chat AI tersedia di <#{allowed}> dan thread di dalamnya.")
