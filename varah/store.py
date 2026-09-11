from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Callable


def defaults() -> dict:
    return {"brand": {}, "responders": [], "roles": {"human": [], "bot": [], "all": []}, "ticket": None, "ai": {"enabled": True, "channel": None}}


class Store:
    """Single-process atomic JSON store; compatible with the previous JS schema."""

    def __init__(self, file: Path | str):
        self.file = Path(file)
        try:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict) or not all(isinstance(v, dict) for v in self.data.values()):
                raise ValueError("Format data tidak valid")
        except FileNotFoundError:
            self.data = {}
        except (ValueError, OSError) as exc:
            raise ValueError(f"Gagal membaca {self.file}. Pulihkan backup; data tidak ditimpa.") from exc

    def get(self, guild_id: int | str) -> dict:
        config = defaults()
        existing = deepcopy(self.data.get(str(guild_id), {}))
        for key in ("brand", "roles", "ai"):
            config[key].update(existing.pop(key, {}))
        config.update(existing)
        return config

    def update(self, guild_id: int | str, change: Callable[[dict], None]) -> dict:
        config = self.get(guild_id)
        change(config)
        next_data = {**self.data, str(guild_id): config}
        encoded = json.dumps(next_data, ensure_ascii=False, indent=2)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.file.parent, delete=False) as temp:
                temp_name = temp.name
                temp.write(encoded)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, self.file)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
        self.data = deepcopy(next_data)
        return deepcopy(config)
