from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import yt_dlp
import os
import asyncio
import subprocess
import uuid
import logging
import pathlib
import tempfile
from datetime import datetime

# --- Paths ---
BASE_DIR      = pathlib.Path(__file__).parent.resolve()
COOKIES_FILE  = BASE_DIR / "yt.txt"
HLS_ROOT_BASE = pathlib.Path(tempfile.gettempdir())
HLS_ROOT      = HLS_ROOT_BASE / "hls_segments"

# --- Ensure dirs exist ---
HLS_ROOT.mkdir(parents=True, exist_ok=True)

# --- Concurrency & Logging ---
download_semaphore = asyncio.Semaphore(30)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI setup ---
app = FastAPI(title="YouTube Downloader with HLS", version="2.0.6")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/hls", StaticFiles(directory=str(HLS_ROOT)), name="hls")

def load_cookies_header() -> str:
    cookies = []
    with open(COOKIES_FILE, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.strip().split('\t')
            if len(parts) >= 7:
                cookies.append(f"{parts[5]}={parts[6]}")
    return '; '.join(cookies)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.now()
    response = await call_next(request)
    ms = (datetime.now() - start).microseconds / 1000
    logger.info(f"{request.client.host} {request.method} {request.url} -> {response.status_code} [{ms:.1f}ms]")
    return response

@app.get("/", summary="Root")
async def root():
    return JSONResponse({"status": "ok"})

@app.get("/stream/", summary="HLS stream")
async def stream_video(request: Request, url: str = Query(...), resolution: int = Query(1080)):
    try:
        # Očistimo URL od dodatnih parametara (npr. ?si=...)
        clean_url = url.split('?', 1)[0]

        # 1) Izvlačenje format‑meta uz kolačiće i UA
        ydl_opts = {
            'quiet': True,
            'cookiefile': str(COOKIES_FILE),
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)

        # 2) Nađemo 1080p video-only MP4
        vid_fmt = next(
            f for f in info['formats']
            if f.get('vcodec') != 'none'
               and f.get('height') == resolution
               and f.get('ext') == 'mp4'
        )

        # 3) Izaberemo najjači audio-only tok
        aud_fmt = max(
            (f for f in info['formats'] if f.get('vcodec') == 'none' and f.get('acodec') != 'none'),
            key=lambda x: x.get('abr', 0)
        )

        # 4) Priprema HLS direktorijuma za ovu sesiju
        session_id = uuid.uuid4().hex
        sess_dir = HLS_ROOT / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)

        # 5) ffmpeg generiše .m3u8 + .ts segmente (2s, zadnja 4)
        cookie_header = load_cookies_header()
        hdr = ['-headers', f"Cookie: {cookie_header}\r\n"]
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            *hdr, '-i', vid_fmt['url'],
            *hdr, '-i', aud_fmt['url'],
            '-c:v', 'copy', '-c:a', 'copy',
            '-f', 'hls',
            '-hls_time', '2',
            '-hls_list_size', '4',
            '-hls_flags', 'delete_segments+append_list',
            '-hls_segment_filename', str(sess_dir / 'seg_%03d.ts'),
            str(sess_dir / 'index.m3u8')
        ]
        proc = subprocess.Popen(cmd, cwd=str(sess_dir))

        # 6) Timeout od ~2s da .m3u8 izađe
        playlist_path = sess_dir / 'index.m3u8'
        for _ in range(10):
            if playlist_path.exists():
                break
            await asyncio.sleep(0.2)
        else:
            proc.kill()
            raise HTTPException(status_code=500, detail="HLS playlist generation failed")

        # 7) Preusmerimo klijenta na listu
        playlist_url = request.url_for('hls', path=f"{session_id}/index.m3u8")
        return RedirectResponse(playlist_url)

    except StopIteration:
        raise HTTPException(status_code=404, detail=f"No {resolution}p stream available")
    except Exception as e:
        logger.error("stream_video error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
