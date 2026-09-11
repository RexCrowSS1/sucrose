# Deploy Sucrose ke Render Free

Proyek sudah menyediakan mode Web Service: `python -u bot.py --web`, endpoint HTTP, Blueprint `render.yaml`, dan penyimpanan PostgreSQL. Tidak perlu menjalankan `start.sh` atau mengunggah `.venv` ke Render.

Render Free tetap dapat tidur setelah 15 menit tanpa trafik masuk dan mempunyai kuota pemakaian. Membuka URL web dapat membangunkannya, tetapi bot Discord tidak dapat membangunkan dirinya lewat command saat proses sedang tidur. Endpoint ini tidak menjamin bot online 24/7 dan tidak melakukan self-ping. [Ketentuan Render Free](https://render.com/docs/free)

## 1. Siapkan database PostgreSQL eksternal

Contoh penyedia dengan paket gratis: [Neon](https://neon.com/pricing). Buat proyek/database khusus bot, buka **Connect**, lalu salin connection string PostgreSQL. Pilih koneksi **direct/non-pooled** untuk langkah awal dan pertahankan parameter TLS bawaan, misalnya `sslmode=require`. Periksa kuota dan masa berlaku layanan pada paket yang Anda pilih. [Panduan koneksi Neon](https://neon.com/docs/connect/query-with-psql-editor)

Simpan connection string sebagai `DATABASE_URL` di Environment Render. Jangan masukkan ke repository, screenshot publik, atau chat.

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
```

Bot otomatis membuat atau memakai tabel `varah_guild_config` dan membaca konfigurasi saat startup. Nama tabel lama dipertahankan agar konfigurasi existing tidak hilang setelah rename bot menjadi Sucrose. Akun database perlu izin membuat tabel serta membaca/menulis tabel tersebut. Semua branding, autoresponder, role, pengaturan AI per server, dan konfigurasi tiket disimpan di PostgreSQL. Riwayat AI tetap di memori; channel/percakapan tiket tetap di Discord.

Mode `--web` menolak berjalan tanpa `DATABASE_URL`. Jika database gagal, bot tidak beralih diam-diam ke file sementara. Penulisan yang gagal tidak dilaporkan sebagai berhasil. Tidak ada koneksi polling database terus-menerus; koneksi digunakan saat startup dan perubahan konfigurasi.

## 2. Upload kode ke repository GitHub

Sertakan `bot.py`, `sucrose/`, `requirements.txt`, dan `render.yaml`. `.gitignore` sudah mengecualikan `.env`, `.venv`, `.run`, serta `data/`. Jangan mengunggah token bot atau konfigurasi rahasia. Pastikan versi terbaru proyek sudah di-push ke repository Anda.

## 3. Deploy dengan Blueprint

Di Render pilih **New → Blueprint**, hubungkan repository, lalu pilih file `render.yaml`. Blueprint membuat satu **Web Service dengan plan Free**. Tidak membuat worker berbayar, database Render, atau layanan Ollama. Periksa ringkasan layanan sebelum mengonfirmasi pembuatan. [Render Blueprints](https://render.com/docs/infrastructure-as-code)

Isi nilai berikut ketika diminta:

| Environment | Isi |
| --- | --- |
| `DISCORD_TOKEN` | Token aplikasi bot Anda |
| `CLIENT_ID` | Application ID bot; untuk aplikasi saat ini gunakan nilai dari `.env` lokal |
| `OWNER_IDS` | ID akun pemilik yang diizinkan memakai `/profile`; akun Anda: `750267305677684828` |
| `DATABASE_URL` | Connection string database eksternal |
| `AI_ENABLED` | Blueprint mengatur `false` sampai Ollama siap |

`PYTHON_VERSION` dan `OLLAMA_MODEL` sudah diisi Blueprint. `PORT` disediakan Render. `GUILD_ID` boleh tidak diisi untuk memakai command global yang sudah didaftarkan. Jangan mengubah aplikasi/token bila ingin mempertahankan bot dan command yang sudah ada.

Alternatif pembuatan manual melalui **New → Web Service**:

| Pengaturan | Nilai |
| --- | --- |
| Runtime | Python |
| Instance Type | Free |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -u bot.py --web` |
| Health Check Path | `/health` |
| Environment `PYTHON_VERSION` | `3.14.3` |

Tambahkan environment wajib pada tabel sebelumnya secara manual. Tidak perlu persistent disk karena data berada di PostgreSQL eksternal.

## 4. Pindahkan konfigurasi lokal jika sudah ada

Langkah ini opsional. Jangan unggah JSON yang berisi konfigurasi privat ke GitHub. Di komputer Anda, isi `DATABASE_URL` pada `.env` lokal dengan database tujuan, pasang dependensi terbaru, lalu jalankan:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python bot.py --import-config data/config.json
```

Impor hanya menambahkan server yang belum ada di database dan tidak menimpa konfigurasi server yang sudah tersimpan. Lakukan impor sebelum bot Render dijalankan karena konfigurasi dibaca ke memori saat startup. Jika Anda sudah menjalankan bot Render, restart sesudah impor. Kosongkan lagi `DATABASE_URL` lokal jika ingin penggunaan desktop tetap memakai JSON.

## 5. Aktifkan bot di Render

Hentikan bot lokal dan jalankan hanya satu instance aktif dengan token yang sama. Ini mencegah balasan/tiket ganda. Render dapat menjalankan versi lama dan baru sebentar saat pergantian deploy; untuk migrasi/deploy dengan pemisahan ketat, suspend layanan lama sebelum mengaktifkan versi baru. Jangan menjalankan dua layanan terpisah dengan token dan database yang sama.

Log yang diharapkan:

```text
HTTP siap di port ...
Sucrose aktif sebagai ...
```

Periksa URL layanan:

- `/` — halaman status sederhana, sekaligus dapat membangunkan layanan yang sedang tidur.
- `/health` — HTTP 200 ketika proses HTTP hidup; memuat boolean `discord_connected`.
- `/ready` — HTTP 200 hanya ketika gateway Discord siap, HTTP 503 saat belum terhubung.

Halaman ini tidak membocorkan token, alamat database, daftar server, atau isi percakapan. `/health` dipakai Render untuk memantau proses; koneksi ulang Discord sementara tidak menyebabkan restart berulang. Jika login atau inisialisasi database gagal secara fatal, proses HTTP ikut berhenti. `SIGTERM` ditangani untuk menutup koneksi saat layanan dihentikan.

Server Members Intent dan Message Content Intent aplikasi bot sebelumnya sudah diaktifkan. Jika menggunakan aplikasi baru, aktifkan keduanya di Developer Portal dan undang bot ke server.

Command global aplikasi saat ini sudah terdaftar, sehingga tidak perlu sync setiap kali layanan bangun. Setelah menambah/mengubah definisi command, jalankan sekali dari komputer dengan token yang sama:

```sh
.venv/bin/python bot.py --sync
```

## 6. Chat AI setelah Ollama tersedia

Render Free untuk proyek ini menjalankan proses bot Python; tidak memasang model Ollama di dalamnya. Dengan `AI_ENABLED=false`, anggota mendapat penjelasan ketika mencoba chat, sedangkan fitur bot lainnya tetap berjalan.

Jika sudah punya endpoint Ollama yang dapat diakses dari Render, tambahkan Environment:

```dotenv
AI_ENABLED=true
OLLAMA_BASE_URL=https://ALAMAT-ENDPOINT-ANDA
OLLAMA_MODEL=llama3.2:latest
OLLAMA_API_KEY=TOKEN_BEARER_JIKA_DIPERLUKAN
```

Endpoint harus mendukung `/api/chat` dan `/api/tags`. `OLLAMA_API_KEY` opsional dan dikirim sebagai `Authorization: Bearer ...`; gunakan HTTPS untuk endpoint bertoken. Ini bukan integrasi otomatis ke setiap penyedia AI. Alamat `127.0.0.1` pada Render menunjuk layanan Render itu sendiri, bukan komputer Anda. Jika Ollama tetap berjalan di komputer, diperlukan koneksi privat/endpoint terlindungi yang dapat diakses Render dan komputer harus tetap menyala. Jangan membuka port Ollama ke publik tanpa perlindungan akses.

Restart setelah mengubah Environment. Gunakan `/ai status` untuk mengecek koneksi dan `/ai setup enabled:true` jika AI pernah dimatikan pada tingkat server.

## Pengujian sebelum deploy

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q bot.py sucrose tests
.venv/bin/python -m pip check
```

Tes unit menggunakan mock untuk PostgreSQL dan Discord. Uji koneksi database sungguhan baru dapat dilakukan setelah Anda mengisi `DATABASE_URL`. File Blueprint siap dipakai, tetapi layanan Render dan database eksternal belum dibuat oleh proses penyiapan kode ini.

Jika deploy gagal, periksa tipe **Web Service**, start command `--web`, environment wajib, akses PostgreSQL/TLS, serta izin intent bot. Jika `/health` hidup tetapi `discord_connected=false`, lihat log Discord dan coba `/ready` setelah beberapa saat. Memakai PostgreSQL eksternal menjaga konfigurasi melewati restart; jangan gunakan database gratis yang kedaluwarsa sebagai satu-satunya salinan tanpa backup.
