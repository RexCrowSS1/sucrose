"""Run: python bot.py | python bot.py --sync | python bot.py --check-ollama."""
import argparse
import asyncio
import logging
from pathlib import Path

import aiohttp
import discord

from sucrose.ai import OllamaClient
from sucrose.client import SucroseBot
from sucrose.config import Settings
from sucrose.utils import UserError


async def run(args):
    settings = Settings.from_env()
    if args.import_config:
        if not settings.database_url:
            raise ValueError("Isi DATABASE_URL untuk mengimpor konfigurasi.")
        path = Path(args.import_config)
        if not path.is_file():
            raise ValueError("File konfigurasi sumber tidak ditemukan.")
        from sucrose.postgres import PostgresStore
        from sucrose.store import Store
        storage = PostgresStore(settings.database_url)
        await storage.initialize()
        count = await storage.import_missing(Store(path))
        print(f"{count} konfigurasi server diimpor. Data server yang sudah ada tidak ditimpa.")
        return
    if args.check_ollama or args.smoke_chat:
        async with aiohttp.ClientSession() as session:
            ollama = OllamaClient(session, settings)
            models = await ollama.models()
            print("Ollama terhubung. Model tersedia: " + (", ".join(models) or "belum ada"))
            model = settings.ollama_model
            if model not in models and not (":" not in model and f"{model}:latest" in models):
                raise UserError(f"Model {model} belum tersedia. Jalankan ollama pull {model}.")
            if args.smoke_chat:
                answer = await ollama.chat([{"role": "system", "content": settings.system_prompt}, {"role": "user", "content": "Halo Sucrose, jawab salam ini dalam satu kalimat bahasa Indonesia."}])
                print("Jawaban model: " + answer)
        return
    settings.require_token()
    if args.web:
        from sucrose.hosting import run_web
        await run_web(settings)
        return
    async with SucroseBot(settings) as bot:
        if args.sync:
            await bot.login(settings.token)
            await bot.sync_commands()
        else:
            await bot.start(settings.token)


def main():
    parser = argparse.ArgumentParser(description="Sucrose • Discord + Ollama")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sync", action="store_true", help="Daftarkan slash command tanpa menjalankan gateway")
    group.add_argument("--check-ollama", action="store_true", help="Periksa layanan dan model Ollama tanpa token Discord")
    group.add_argument("--smoke-chat", action="store_true", help="Uji satu balasan Ollama tanpa token Discord")
    group.add_argument("--web", action="store_true", help="Jalankan bot beserta HTTP server untuk Render")
    group.add_argument("--import-config", metavar="PATH", help="Impor JSON lokal ke PostgreSQL; hanya server yang belum ada")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(args))
    except (ValueError, UserError) as exc:
        print(f"Tidak berhasil: {exc}")
        return 1
    except discord.LoginFailure:
        print("Token Discord tidak valid. Periksa DISCORD_TOKEN di .env.")
        return 1
    except discord.PrivilegedIntentsRequired:
        print("Aktifkan Server Members Intent dan Message Content Intent di Developer Portal.")
        return 1
    except discord.HTTPException as exc:
        print(f"Discord menolak permintaan (kode {exc.code}). Periksa konfigurasi dan izin bot.")
        return 1
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
        print("Tidak dapat menghubungi Discord atau membaca file bot. Periksa koneksi internet, DNS, dan izin file.")
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
