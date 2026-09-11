# Sucrose • Discord Bot + Ollama

**Deploy ke Render Free:** ikuti [DEPLOY_RENDER.md](DEPLOY_RENDER.md). Proyek menyediakan `render.yaml`, mode `python bot.py --web`, endpoint HTTP, dan PostgreSQL eksternal untuk konfigurasi persisten. Paket gratis tetap bisa tidur; AI hosting dinonaktifkan sampai Ollama tersedia.

Bot Discord **Python** dengan autoresponder, role otomatis manusia/bot, embed, banner/avatar custom, tiket privat, dan teman chat melalui **Ollama lokal**. Fitur terinspirasi dari Mimu; bukan implementasi seluruh fitur Mimu.

## Mulai cepat

Untuk proyek yang sudah dikonfigurasi, jalankan:

```sh
./start.sh
```

Script memakai `.venv` dan `.env`, memeriksa model, lalu menyalakan Ollama lokal jika belum aktif. Script dapat dipanggil dari folder mana pun memakai path lengkapnya. Tekan **Control + C** untuk menghentikan bot. Ollama yang dimulai oleh script ikut dihentikan; layanan Ollama yang sudah aktif sebelumnya tetap berjalan. Log Ollama yang dimulai script ada di `.run/ollama.log`.

Jika bot proyek ini sudah berjalan, script menampilkan PID dan menolak menjalankan instance kedua. Hentikan proses lama terlebih dahulu. Gunakan `./start.sh --help` untuk petunjuk singkat. Script tidak mendaftarkan ulang slash command; jalankan `python bot.py --sync` bila definisi command berubah.

Memerlukan **Python 3.11+**, aplikasi bot Discord, dan Ollama. Dependensi Python ada di `requirements.txt`. Pada komputer proyek ini Ollama dan model `llama3.2:latest` sudah tersedia; model itu dipakai sebagai default.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Jika `.env` sudah ada, edit file tersebut; jangan timpa token/config Anda. Windows: gunakan `.venv\Scripts\activate` dan `copy .env.example .env`.

Isi `.env` secara lokal:

```dotenv
DISCORD_TOKEN=token_bot_anda
CLIENT_ID=application_id_anda
GUILD_ID=id_server_pengujian
OWNER_IDS=id_akun_discord_anda
DATA_FILE=./data/config.json
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:latest
```

`CLIENT_ID` opsional; discord.py dapat memperoleh Application ID dari token. `GUILD_ID` diisi agar command langsung didaftarkan di satu server; kosongkan untuk command global. `OWNER_IDS` dapat berisi beberapa ID dipisahkan koma dan digunakan untuk membatasi perubahan profil global bot. Jangan bagikan token atau commit `.env`.

Jalankan Ollama di terminal terpisah jika belum aktif:

```sh
ollama serve
```

Jika model belum ada pada komputer yang digunakan, unduh sekali:

```sh
ollama pull llama3.2
```

Uji Ollama, daftarkan command, kemudian mulai bot:

```sh
python bot.py --check-ollama
python bot.py --smoke-chat
python bot.py --sync
python bot.py
```

`--check-ollama` dan `--smoke-chat` tidak memerlukan token Discord. `--smoke-chat` mengirim satu salam ke model lokal. Bot online ketika terminal menampilkan `Sucrose aktif sebagai ...`. Kedua proses, bot Python dan Ollama, harus tetap berjalan. Tidak ada proses Node.js yang diperlukan.

## Pengaturan Discord

1. Buka [Discord Developer Portal](https://discord.com/developers/applications), buat aplikasi, lalu ambil token di halaman **Bot**.
2. Aktifkan **Server Members Intent** dan **Message Content Intent**. Keduanya diperlukan untuk autorole, autoresponder, dan mention chat. Aplikasi yang memerlukan persetujuan intent harus mengajukannya sesuai ketentuan Discord.
3. Aktifkan Developer Mode di Discord agar dapat menyalin ID server dan akun. Ambil Application ID dari General Information jika ingin mengisi `CLIENT_ID`.
4. Di OAuth2 URL Generator pilih scope `bot` dan `applications.commands`. Pilih izin **View Channels**, **Send Messages**, **Send Messages in Threads**, **Embed Links**, **Attach Files**, **Read Message History**, **Manage Roles**, dan **Manage Channels**, lalu undang bot ke server.
5. Letakkan role bot **di atas role yang ingin diberikan otomatis**. Di kategori tiket, pastikan bot mempunyai View Channel, Manage Channels, dan Manage Roles. Bot tidak memerlukan Administrator.
6. Jalankan `python bot.py --sync` setelah menambahkan bot. Sync mengganti daftar command aplikasi pada cakupan yang dipilih; jalankan lagi setelah definisi command berubah. Jika berpindah dari command server ke global, hapus command server lama melalui API Discord agar tidak tampil ganda.

## Chat dengan Sucrose

```text
/chat pesan:Halo Sucrose, bantu aku membuat ide acara server
/chat pesan:Jelaskan lebih singkat
/chat pesan:Aku ingin ngobrol secara privat privat:true
@Sucrose halo, apa kabar?
/chat-reset
```

- **`/chat`**: jawaban publik secara default. `privat:true` membuat respons hanya terlihat oleh pemakai command.
- **Mention langsung**: mention akun bot dalam pesan beserta pertanyaannya. Bot membalas di channel tersebut. Pesan biasa tidak diteruskan ke AI. Untuk setiap balasan lanjutan, mention lagi atau pakai `/chat`.
- **Ingatan percakapan**: terpisah per server, channel/thread, pengguna, dan mode publik/privat. Mention dan `/chat` publik berbagi konteks untuk pengguna yang sama dalam channel yang sama. Riwayat privat tidak digunakan dalam jawaban publik.
- **`/chat-reset`**: hapus ingatan AI publik dan privat Anda di channel saat ini. Ini tidak menghapus pesan Discord yang sudah terkirim. Tunggu permintaan aktif selesai sebelum reset.
- Maksimal 2.000 karakter per pertanyaan. Jawaban panjang dibagi menjadi beberapa pesan. AI tidak memicu notifikasi `@everyone`, role, atau pengguna.
- Default: cooldown 5 detik per pengguna/server, maksimal 2 permintaan AI bersamaan, 6 putaran percakapan, dan kedaluwarsa setelah 30 menit tidak aktif. Riwayat hanya di memori dan hilang setelah restart. Pembersihan riwayat kedaluwarsa dilakukan saat permintaan berikutnya.
- Jika sebuah pesan mention bot sekaligus cocok dengan autoresponder, **chat AI diprioritaskan** sehingga tidak ada balasan ganda. Pesan bot/webhook diabaikan.

Admin dengan **Manage Server** dapat mengatur:

```text
/ai setup enabled:true channel:#ngobrol
/ai setup all_channels:true
/ai setup system_prompt:Kamu Sucrose, teman ngobrol yang ramah dan menjawab singkat dalam bahasa Indonesia.
/ai setup reset_prompt:true
/ai setup enabled:false
/ai status
```

Pembatasan channel berlaku untuk `/chat` dan mention, termasuk thread di dalam channel tersebut. Mengubah kepribadian membuat percakapan berikutnya menggunakan konteks baru. Fitur non-AI tetap dapat digunakan saat Ollama sedang mati.

## Konfigurasi Ollama

| Variabel `.env` | Default | Fungsi |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Alamat layanan Ollama |
| `OLLAMA_MODEL` | `llama3.2:latest` | Model chat yang sudah diunduh |
| `OLLAMA_TIMEOUT` | `120` | Batas waktu respons dalam detik |
| `OLLAMA_SYSTEM_PROMPT` | Kepribadian Sucrose berbahasa Indonesia | Instruksi dasar model |
| `AI_COOLDOWN_SECONDS` | `5` | Jeda per pengguna/server |
| `AI_HISTORY_TURNS` | `6` | Jumlah putaran yang disimpan |
| `AI_HISTORY_TTL_SECONDS` | `1800` | Kedaluwarsa konteks tidak aktif |
| `AI_MAX_CONVERSATIONS` | `500` | Batas jumlah konteks dalam memori |
| `AI_MAX_CONCURRENT` | `2` | Batas permintaan bersamaan |

Untuk mengganti model, jalankan `ollama pull nama-model`, ubah `OLLAMA_MODEL`, lalu restart bot. Endpoint dan model hanya dapat diubah dari konfigurasi lokal, bukan oleh anggota server. Integrasi memakai HTTP async `/api/chat` dengan `stream:false`, batas output 512 token, dan context window 4.096 token; konteks lama dipangkas bila terlalu panjang.

Dengan konfigurasi default, hanya pertanyaan yang secara eksplisit ditujukan ke bot dan konteks chat terkait yang dikirim ke Ollama di komputer ini. Bot tidak mengambil riwayat channel/tiket sebagai bahan AI dan tidak memberi model akses menjalankan perintah atau mengubah server. Jika bot dijalankan di VPS/container, `127.0.0.1` menunjuk mesin/container itu; sesuaikan URL ke Ollama yang dapat diakses secara privat bila layanannya terpisah. Memilih endpoint/model cloud akan mengubah tujuan pemrosesan data.

## Fitur dan command lainnya

Pengaturan berikut memerlukan **Manage Server**. Anggota biasa dapat memakai `/help`, `/ping`, `/chat`, `/chat-reset`, serta tombol tiket. `/profile` juga dibatasi ke `OWNER_IDS`.

| Command | Fungsi |
| --- | --- |
| `/brand set` | Nama penulis embed, warna hex, URL banner, thumbnail/avatar, footer per server |
| `/brand preview` | Preview privat branding |
| `/brand reset` | Reset seluruh branding server |
| `/profile avatar:… banner:…` | Upload avatar/banner akun bot secara global |
| `/autoresponder add` | Tambah/ganti trigger, response, mode, channel, cooldown, opsi embed |
| `/autoresponder remove` | Hapus trigger |
| `/autoresponder list` | Unduh daftar trigger sebagai teks |
| `/autorole add target:… role:…` | Role otomatis `human`, `bot`, atau `all` |
| `/autorole remove` | Hapus aturan role otomatis |
| `/autorole list` | Lihat aturan role |
| `/embed` | Kirim embed custom ke channel |
| `/ticket setup` | Pilih kategori tiket dan role staf |
| `/ticket panel` | Kirim tombol Buka Tiket |

Contoh (pilih opsi dengan antarmuka slash command Discord):

```text
/brand set name:Sucrose color:#F5A9D0 banner:https://example.com/banner.png avatar:https://example.com/avatar.png footer:Sucrose Community
/autoresponder add trigger:halo response:Halo {user}, selamat datang di {server}! mode:exact embed:true cooldown:5
/autorole add target:human role:@Member
/autorole add target:bot role:@Bots
/embed title:Selamat Datang description:Baca aturan server dulu ya!\nSemoga betah.
/ticket setup category:Tiket staff:@Support
/ticket panel channel:#bantuan title:Pusat Bantuan
```

Ganti URL contoh dengan tautan langsung gambar HTTPS yang stabil. URL attachment Discord bisa kedaluwarsa sehingga kurang cocok sebagai branding permanen. `/profile` menerima upload PNG/JPG/GIF/WebP maksimal 8 MB; Discord membatasi frekuensi perubahan profil. Nama akun bot dapat diubah melalui Developer Portal; `/brand name` hanya mengatur nama penulis embed.

Autoresponder tidak membedakan huruf besar/kecil. `exact` mencocokkan seluruh pesan, `contains` mencari bagian pesan, `startswith` mencocokkan awalan. Maksimal 100 trigger; jika beberapa cocok, aturan pertama digunakan. Menambah trigger yang sama menggantikan respons lama. Variabel: `{user}`, `{username}`, `{server}`, `{membercount}`. Teks `\n` menjadi baris baru. Mention notifikasi dinonaktifkan. Cooldown berlaku per pengguna/trigger dalam satu server dan direset ketika bot restart.

Autorole berlaku untuk anggota **baru bergabung**, bukan seluruh anggota lama. Role `all` digabungkan dengan `human` atau `bot`. Role integrasi, `@everyone`, dan role di atas bot tidak diberikan. Admin selain pemilik server hanya dapat menambahkan role di bawah role tertingginya.

## Tiket privat

1. Buat kategori tiket dan role staf khusus. Jangan pilih role anggota umum sebagai staf.
2. Jalankan `/ticket setup`, kemudian `/ticket panel` di channel yang dapat dilihat anggota.
3. **Buka Tiket** membuat channel dengan overwrite eksplisit untuk pembuka, staf, dan bot. `@everyone` ditolak; overwrite kategori tidak disalin. **Pemilik server dan pemegang Administrator tetap dapat melihatnya**, mengikuti model izin Discord.
4. Satu anggota hanya dapat mempunyai satu tiket aktif per server. Identitas tiket disimpan di topic `sucrose-ticket:…`; jangan ubah topic secara manual.
5. Pembuka, staf, atau pemegang Manage Server yang dapat mengakses tiket dapat menutupnya. Bot menyembunyikan channel dari pembuka, menandai `closed-…`, dan menyimpan riwayat untuk staf. Pemegang Administrator tetap mengikuti izin Discord.
6. Anggota bisa membuka tiket baru setelah tiket lama ditutup. Staf menghapus channel lama secara manual setelah riwayat tidak diperlukan; belum ada ekspor transkrip otomatis.

Perubahan setup hanya berlaku untuk tiket baru. Tombol tiket persisten dan tetap bekerja setelah restart; format topic dan ID tombol kompatibel dengan versi JavaScript sebelumnya.

## Migrasi dari versi Node.js

- Hentikan proses Node.js lama dan jalankan bot Python ini dengan token yang sama.
- `.env` lama tetap dapat dipakai; tambahkan variabel Ollama dari `.env.example` jika ingin menyesuaikan default.
- File `data/config.json` lama **langsung dibaca**, termasuk branding, autoresponder, autorole, kategori dan role staf. Pengaturan AI default ditambahkan saat dibutuhkan.
- Jalankan `python bot.py --sync` untuk memperbarui slash command pada server/global yang sama. Nama fitur lama tetap sama; `/chat`, `/chat-reset`, dan `/ai` ditambahkan.
- Kode, package manifest, dan tes Node.js telah diganti oleh Python. Tidak perlu `npm install` atau `npm start`.

## Penyimpanan dan pengujian

Konfigurasi disimpan atomik di `data/config.json`. Backup direktori `data/` dan gunakan volume persisten di hosting. Jalankan **satu instance bot per token/file data** agar respons dan tiket tidak terduplikasi. Riwayat chat AI hanya di memori; isi percakapan tiket tetap berada di Discord.

```sh
python -m compileall -q bot.py sucrose tests
python -m unittest discover -s tests -v
python -m pip check
python bot.py --smoke-chat
```

Tes unit tidak menggunakan token atau menghubungi Discord/Ollama. Tes mencakup migrasi data, penyimpanan atomik, command/izin admin, autoresponder, autorole, branding, tiket privat, tombol persisten, cooldown AI, isolasi konteks publik/privat, reset/expiry, concurrency, timeout, kesalahan model, dan pemecahan pesan panjang. Smoke test memakai Ollama sungguhan.

Validasi migrasi: **48 tes unit lulus**, model Ollama lokal berhasil menjawab, login REST Discord berhasil, dan **11 command global sudah terdaftar**. Server Members Intent dan Message Content Intent telah diaktifkan dengan persetujuan pemilik; koneksi gateway Discord berhasil. Bot perlu diundang ke server sebelum command dapat digunakan di sana.

Setelah bot terhubung, lakukan uji server dengan akun anggota dan staf: kirim trigger, uji mention dan `/chat privat:true`, coba `/chat-reset`, periksa autorole saat anggota bergabung, kirim embed, buka tiket dan pastikan anggota lain tidak dapat melihatnya, tutup, lalu restart untuk mengecek persistensi. Pengujian interaksi langsung di server belum dilakukan. Isi `OWNER_IDS` untuk memakai `/profile`.

Jika AI gagal terhubung, jalankan `ollama serve`, `ollama list`, dan `python bot.py --check-ollama`. Jika model belum ada, unduh model yang sama dengan `OLLAMA_MODEL`. Jika timeout, gunakan model lebih ringan atau sesuaikan `OLLAMA_TIMEOUT`. Jika command tidak muncul, cek GUILD_ID/scopes dan jalankan `--sync`. Jika role/tiket gagal, periksa hierarki role serta izin channel/kategori. Jika privileged intent ditolak saat login, periksa halaman Bot di Developer Portal.

Referensi resmi: [discord.py](https://discordpy.readthedocs.io/en/stable/), [Ollama Chat API](https://docs.ollama.com/api/chat), [Discord Gateway Intents](https://docs.discord.com/developers/events/gateway).
