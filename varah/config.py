from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = (
    "Kamu Varah, teman ngobrol di Discord. Jawab dengan ramah, jelas, dan ringkas "
    "dalam bahasa Indonesia kecuali diminta bahasa lain."
)


def integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} harus berupa angka.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} harus antara {minimum} dan {maximum}.")
    return value


@dataclass(frozen=True)
class Settings:
    token: str = field(default="", repr=False)
    application_id: int | None = None
    guild_id: int | None = None
    owner_ids: frozenset[int] = frozenset()
    data_file: Path = ROOT / "data/config.json"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:latest"
    ollama_timeout: int = 120
    system_prompt: str = DEFAULT_PROMPT
    cooldown: int = 5
    history_turns: int = 6
    history_ttl: int = 1800
    max_conversations: int = 500
    max_concurrent: int = 2
    database_url: str = field(default="", repr=False)
    ai_enabled: bool = True
    ollama_api_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("OLLAMA_BASE_URL harus URL HTTP/HTTPS server Ollama yang valid.")
        model = os.getenv("OLLAMA_MODEL", "llama3.2:latest").strip()
        if not model:
            raise ValueError("OLLAMA_MODEL tidak boleh kosong.")
        try:
            app_id = os.getenv("CLIENT_ID", "").strip()
            guild_id = os.getenv("GUILD_ID", "").strip()
            owners = frozenset(int(v.strip()) for v in os.getenv("OWNER_IDS", "").split(",") if v.strip())
            # Application ID is optional: discord.py can obtain it from the token.
            application_id = int(app_id) if app_id and app_id != "isi_application_id" else None
            server_id = int(guild_id) if guild_id else None
        except ValueError as exc:
            raise ValueError("CLIENT_ID, GUILD_ID, dan OWNER_IDS harus berisi ID Discord numerik.") from exc
        path = Path(os.getenv("DATA_FILE", "./data/config.json"))
        ai_enabled = os.getenv("AI_ENABLED", "true").lower()
        if ai_enabled not in {"true", "false"}:
            raise ValueError("AI_ENABLED harus true atau false.")
        database_url = os.getenv("DATABASE_URL", "").strip()
        if database_url and urlparse(database_url).scheme not in {"postgres", "postgresql"}:
            raise ValueError("DATABASE_URL harus berupa connection string PostgreSQL.")
        return cls(
            token=os.getenv("DISCORD_TOKEN", ""), application_id=application_id,
            guild_id=server_id, owner_ids=owners, data_file=path if path.is_absolute() else ROOT / path,
            ollama_url=url, ollama_model=model,
            ollama_timeout=integer("OLLAMA_TIMEOUT", 120, 5, 600),
            system_prompt=os.getenv("OLLAMA_SYSTEM_PROMPT", DEFAULT_PROMPT),
            cooldown=integer("AI_COOLDOWN_SECONDS", 5, 1, 3600),
            history_turns=integer("AI_HISTORY_TURNS", 6, 1, 20),
            history_ttl=integer("AI_HISTORY_TTL_SECONDS", 1800, 60, 86400),
            max_conversations=integer("AI_MAX_CONVERSATIONS", 500, 1, 10000),
            max_concurrent=integer("AI_MAX_CONCURRENT", 2, 1, 10),
            database_url=database_url, ai_enabled=ai_enabled == "true",
            ollama_api_key=os.getenv("OLLAMA_API_KEY", ""),
        )

    def require_token(self) -> None:
        if not self.token or self.token == "isi_token_bot_di_sini":
            raise ValueError("Isi DISCORD_TOKEN di .env terlebih dahulu. Lihat README.md.")
