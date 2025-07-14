
# YTDownloader by Nauval Sains Data

Website downloader video dan audio dari YouTube yang mendukung fitur pencarian video, informasi video (termasuk resolusi dan bitrate), serta unduhan video dan audio. Aplikasi ini dikembangkan dengan FastAPI untuk backend dan HTML/CSS/Python untuk frontend.

## Fitur Utama
- **Pencarian Video**: Cari video YouTube berdasarkan kata kunci.
- **Informasi Video**: Dapatkan detail tentang judul, durasi, resolusi yang tersedia, bitrate audio, dan lainnya.
- **Unduh Video**: Unduh video dengan resolusi tertentu (misalnya 720p, 1080p).
- **Unduh Audio**: Ekstrak dan unduh audio dari video YouTube dengan bitrate tertentu.

---

## Persyaratan
Untuk menjalankan proyek ini, Anda membutuhkan:
- **Python 3.8+**: Untuk menjalankan backend menggunakan FastAPI.
- **Node.js (opsional)**: Jika ingin menambahkan fitur lebih lanjut di frontend.
- **FFmpeg**: Untuk penggabungan video dan audio.
- **Browser modern**: Untuk menjalankan antarmuka berbasis HTML.

### Dependensi Python (Backend)
- **FastAPI**: Framework web untuk API backend.
- **uvicorn**: Server ASGI untuk menjalankan FastAPI.
- **yt-dlp**: Untuk pengunduhan video/audio YouTube.

---

## Instalasi dan Konfigurasi

### 1. Instal Dependensi Backend
Instal pustaka Python yang diperlukan:
```bash
pip install -r requirements.txt
```

### 2. Instal FFmpeg
Pastikan FFmpeg terinstal di sistem:

#### - Linux:
```bash
sudo apt update && sudo apt install ffmpeg
```
#### - Windows:
Unduh FFmpeg dari [situs resmi](https://ffmpeg.org) dan tambahkan ke PATH sistem.

### 3. Jalankan Backend
Jalankan backend menggunakan `uvicorn`:
```bash
uvicorn backend.main:app --reload
```
Bisa juga menggunakan PM2 untuk manajemen proses:
```bash
pm2 start "python3 -m uvicorn main:app --host 0.0.0.0 --port 8000" --name fastapi
```

### 4. Buka Frontend
Buka file `index.html` di folder `static` menggunakan browser atau akses URL berikut:
```
http://127.0.0.1:8000/static/index.html
```

---

## Informasi Endpoint Backend
Backend FastAPI menyediakan beberapa endpoint API:
- `GET /search/` : Cari video YouTube berdasarkan kata kunci.
- `GET /info/` : Ambil detail video, termasuk resolusi dan bitrate.
- `GET /download/` : Unduh video dengan resolusi tertentu.
- `GET /download/audio/` : Unduh audio dengan bitrate tertentu.

---

## Catatan Penting
- Aplikasi ini memerlukan file **cookies (yt.txt)** untuk mengakses video yang membutuhkan autentikasi (misalnya video berusia 18+ atau dibatasi lokasi).
- Pastikan koneksi internet Anda stabil untuk unduhan yang lebih cepat.
- Dokumentasi telah disertakan dalam proyek ini.

---

## Penulis
**M. Nauval Sayyid Abdillah**  
Sains Data UNESA 2024F  
NIM 24013554092
