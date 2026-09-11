"""HTTP lifecycle for Render Web Services; no self-ping or keep-alive traffic."""
import asyncio
import logging
import os
import signal

from aiohttp import web

from .client import SucroseBot, SucroseBot

log = logging.getLogger("sucrose.hosting")


def create_app(bot):
    async def home(request):
        state = "terhubung" if bot.is_ready() else "sedang menghubungkan"
        return web.Response(text=(
            "<!doctype html><html lang='id'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>sucrose Bot</title><body><h1>sucrose Bot</h1>"
            f"<p>Discord: {state}.</p>"
            "<p>Gunakan command bot di Discord. Halaman ini tidak menyediakan chat publik.</p>"
            "<p>Render Free dapat tidur saat tidak ada trafik masuk.</p></body></html>"
        ), content_type="text/html", headers={"Cache-Control": "no-store"})

    async def health(request):
        return web.json_response({"status": "alive", "discord_connected": bot.is_ready()}, headers={"Cache-Control": "no-store"})

    async def ready(request):
        connected = bot.is_ready() and not bot.is_closed()
        return web.json_response({"status": "ready" if connected else "connecting"}, status=200 if connected else 503,
                                 headers={"Cache-Control": "no-store"})

    app = web.Application(client_max_size=1024)
    app.router.add_get("/", home)
    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    return app


async def run_web(settings):
    if not settings.database_url:
        raise ValueError("Mode --web memerlukan DATABASE_URL agar konfigurasi tidak hilang di Render Free.")
    try:
        port = int(os.getenv("PORT", "10000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("PORT harus angka antara 1 dan 65535.") from None
    loop = asyncio.get_running_loop()
    shutdown = asyncio.Event()
    signals = []
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, shutdown.set)
            signals.append(signum)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        async with SucroseBot(settings) as bot:
            runner = web.AppRunner(create_app(bot), access_log=None)
            await runner.setup()
            bot_task = stop_task = None
            try:
                await web.TCPSite(runner, "0.0.0.0", port).start()
                log.info("HTTP siap di port %s; /health untuk proses, /ready untuk Discord.", port)
                bot_task = asyncio.create_task(bot.start(settings.token))
                stop_task = asyncio.create_task(shutdown.wait())
                completed, _ = await asyncio.wait((bot_task, stop_task), return_when=asyncio.FIRST_COMPLETED)
                if bot_task in completed:
                    await bot_task  # Fatal bot/database errors must stop the web process too.
            finally:
                try:
                    await bot.close()
                finally:
                    tasks = [task for task in (bot_task, stop_task) if task]
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await runner.cleanup()
    finally:
        for signum in signals:
            loop.remove_signal_handler(signum)
