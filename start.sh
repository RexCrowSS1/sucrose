#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$PROJECT_DIR"

case "${1:-}" in
  -h|--help)
    echo "Pemakaian: ./start.sh"
    echo "Menjalankan bot dengan .env dan menyalakan Ollama lokal bila diperlukan."
    echo "Control + C menghentikan bot dan Ollama yang dimulai oleh script ini."
    exit 0
    ;;
  "") ;;
  *) echo "Argumen tidak dikenal. Gunakan ./start.sh --help." >&2; exit 1 ;;
esac

if [[ ! -x .venv/bin/python ]]; then
  echo "Virtual environment belum tersedia. Jalankan di folder proyek:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "File .env belum ada. Salin .env.example ke .env dan isi token bot." >&2
  exit 1
fi

if ! .venv/bin/python -c 'import discord, aiohttp, dotenv' >/dev/null 2>&1; then
  echo "Dependensi belum lengkap. Jalankan: .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

# Python reads .env as data; never source a token/config file as shell code.
exec .venv/bin/python -u - <<'PY'
import fcntl
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from varah.config import ROOT, Settings


def find_running_bot():
    """Also detect an older bot started directly with python bot.py."""
    result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError("Tidak dapat memeriksa proses bot. Periksa izin menjalankan ps.")
    for line in result.stdout.splitlines():
        try:
            pid_text, command = line.strip().split(None, 1)
            args = shlex.split(command)
        except ValueError:
            continue
        if not args or "python" not in Path(args[0]).name.lower():
            continue
        scripts = [arg for arg in args[1:] if Path(arg).name == "bot.py"]
        if not scripts or int(pid_text) == os.getpid():
            continue
        if str(ROOT / "bot.py") in scripts:
            return pid_text
        proc_cwd = Path(f"/proc/{pid_text}/cwd")
        try:
            cwd = proc_cwd.resolve(strict=True)
        except OSError:
            # macOS does not expose /proc; inspect only the candidate's cwd.
            lsof = shutil.which("lsof")
            if not lsof:
                raise RuntimeError("Perlu lsof untuk memeriksa bot yang berjalan di macOS.")
            info = subprocess.run([lsof, "-a", "-p", pid_text, "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=5)
            cwd = next((Path(row[1:]) for row in info.stdout.splitlines() if row.startswith("n")), None)
        if cwd == ROOT:
            return pid_text
    return None


def models_at(url):
    try:
        with urlopen(f"{url}/api/tags", timeout=2) as response:
            data = json.load(response)
        return [model["name"] for model in data["models"]]
    except HTTPError as exc:
        raise RuntimeError(f"Endpoint Ollama menolak akses (HTTP {exc.code}). Periksa OLLAMA_BASE_URL.") from exc
    except (URLError, TimeoutError, OSError):
        return None
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Daftar model Ollama tidak valid. Periksa OLLAMA_BASE_URL.") from exc


def main():
    settings = Settings.from_env()
    settings.require_token()
    runtime = ROOT / ".run"
    runtime.mkdir(exist_ok=True)
    # Keep the inode on disk: deleting a flock file can allow two owners.
    with (runtime / "start.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Bot sudah dijalankan melalui start.sh. Hentikan proses lama terlebih dahulu.")
        existing = find_running_bot()
        if existing:
            raise RuntimeError(f"Bot proyek ini sudah berjalan (PID {existing}). Hentikan dengan kill {existing} sebelum menjalankan start.sh.")

        ollama_process = None
        ollama_log = None
        try:
            models = models_at(settings.ollama_url)
            if models is None:
                url = urlparse(settings.ollama_url)
                if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.path not in {"", "/"}:
                    raise RuntimeError("Ollama belum terhubung. Jalankan layanan pada OLLAMA_BASE_URL yang dikonfigurasi.")
                executable = shutil.which("ollama")
                if not executable:
                    raise RuntimeError("Ollama tidak ditemukan. Instal Ollama atau tambahkan executable-nya ke PATH.")
                print("Menyalakan Ollama lokal...")
                ollama_log = (runtime / "ollama.log").open("a")
                ollama_process = subprocess.Popen(
                    [executable, "serve"], stdout=ollama_log, stderr=subprocess.STDOUT,
                    env={**os.environ, "OLLAMA_HOST": settings.ollama_url}, start_new_session=True,
                )
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    models = models_at(settings.ollama_url)
                    if models is not None:
                        break
                    if ollama_process.poll() is not None:
                        break
                    time.sleep(1)
                if models is None:
                    raise RuntimeError("Ollama gagal siap dalam 30 detik. Lihat .run/ollama.log.")
            model = settings.ollama_model
            if model not in models and not (":" not in model and f"{model}:latest" in models):
                raise RuntimeError(f"Model {model} belum tersedia. Unduh dengan ollama pull {shlex.quote(model)} pada server Ollama yang dikonfigurasi.")
            print(f"Ollama siap; model: {model}")
            print("Menjalankan bot. Tekan Control + C untuk berhenti.")
            sys.argv = [str(ROOT / "bot.py")]
            runpy.run_path(str(ROOT / "bot.py"), run_name="__main__")
        finally:
            # Only stop a server owned by this launcher, never a pre-existing one.
            if ollama_process is not None and ollama_process.poll() is None:
                print("Menghentikan Ollama yang dimulai oleh start.sh...")
                ollama_process.terminate()
                try:
                    ollama_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    ollama_process.kill()
                    ollama_process.wait()
            if ollama_log is not None:
                ollama_log.close()


try:
    main()
except KeyboardInterrupt:
    print("\nDihentikan.")
    sys.exit(0)
except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
    print(f"Tidak berhasil: {error}", file=sys.stderr)
    sys.exit(1)
PY
