from fastapi import FastAPI, Request, Query, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import os
import asyncio
from datetime import datetime
from urllib.parse import quote
import logging
import subprocess
import base64
import requests
import pathlib

# --- Paths ---
BASE_DIR = pathlib.Path(__file__).parent.resolve()
COOKIES_FILE = str(BASE_DIR / "yt.txt")
OUTPUT_DIR = str(BASE_DIR / "output")
SPOTIFY_OUTPUT_DIR = str(BASE_DIR / "spotify_output")
HLS_ROOT = os.path.join(OUTPUT_DIR, "hls_segments")  # moved under OUTPUT_DIR for write permissions

# --- Ensure dirs exist ---
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SPOTIFY_OUTPUT_DIR, exist_ok=True)
os.makedirs(HLS_ROOT, exist_ok=True)

# --- Spotify credentials ---
SPOTIFY_CLIENT_ID = "spotify_client_id kalian "
SPOTIFY_CLIENT_SECRET = "Spotify_client_secret kalian "
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"

# --- Concurrency control ---
MAX_CONCURRENT_DOWNLOADS = 30
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI app ---
app = FastAPI(
    title="YouTube dan Spotify Downloader API",
    description="API untuk mengunduh atau stream video/audio dari YouTube dan Spotify.",
    version="2.0.2"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helpers ---
async def delete_file_after_delay(file_path: str, delay: int = 600):
    await asyncio.sleep(delay)
    try:
        os.remove(file_path)
        logger.info(f"File {file_path} deleted after {delay}s.")
    except Exception as e:
        logger.warning(f"Could not delete {file_path}: {e}")

def load_cookies_header() -> str:
    """
    Parse Netscape cookies from yt.txt and return 'name1=val1; name2=val2; ...'
    """
    cookies = []
    with open(COOKIES_FILE, 'r') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.strip().split('\t')
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                cookies.append(f"{name}={value}")
    return '; '.join(cookies)

def get_spotify_access_token():
    auth_str = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {b64_auth}"}
    data = {"grant_type": "client_credentials"}
    resp = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=data)
    if resp.status_code != 200:
        raise Exception(f"Token error: {resp.text}")
    return resp.json()["access_token"]

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.now()
    response = await call_next(request)
    ms = (datetime.now() - start).microseconds / 1000
    logger.info(f"{request.client.host} {request.method} {request.url} -> {response.status_code} [{ms:.1f}ms]")
    return response

@app.get("/", summary="Root")
async def root():
    index = str(BASE_DIR / "index.html")
    return FileResponse(index) if os.path.exists(index) else JSONResponse(status_code=404, content={"error": "index.html not found"})

# --- Download video to file ---
@app.get("/download/", summary="Preuzmi video")
async def download_video(background_tasks: BackgroundTasks, url: str = Query(...), resolution: int = Query(720)):
    await download_semaphore.acquire()
    try:
        ydl_opts = {
            'format': f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s_%(resolution)sp.%(ext)s'),
            'cookiefile': COOKIES_FILE,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        background_tasks.add_task(delete_file_after_delay, path)
        return FileResponse(path, media_type="video/mp4", filename=os.path.basename(path))
    except Exception as e:
        logger.error(f"download_video error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        download_semaphore.release()

# --- Streaming endpoint (fragmented MP4 in 1080p) ---
@app.get("/stream/", summary="Streamuj video odmah bez čekanja čitavog download-a")
async def stream_video(url: str = Query(...), resolution: int = Query(1080)):
    try:
        # 1) Extract formats with cookies file
        ydl_opts = {
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # 2) Find explicit 1080p mp4 video-only
        vid_fmt = next(
            f for f in info['formats']
            if f.get('vcodec') != 'none'
               and f.get('height') == resolution
               and f.get('ext') == 'mp4'
        )

        # 3) Pick highest‐bitrate audio-only track
        aud_fmt = max(
            (f for f in info['formats'] if f.get('vcodec') == 'none' and f.get('acodec') != 'none'),
            key=lambda x: x.get('abr', 0)
        )

        vid_url = vid_fmt['url']
        aud_url = aud_fmt['url']

        # 4) Build Cookie header
        cookie_header = load_cookies_header()
        headers_arg = ['-headers', f"Cookie: {cookie_header}\r\n"]

        # 5) FRAGMENTED MP4 streaming via FFMPEG
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            *headers_arg, '-i', vid_url,
            *headers_arg, '-i', aud_url,
            '-c:v', 'copy', '-c:a', 'copy',
            '-movflags', 'frag_keyframe+empty_moov',
            '-f', 'mp4', 'pipe:1'
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**6)
        return StreamingResponse(proc.stdout, media_type="video/mp4")

    except StopIteration:
        raise HTTPException(status_code=404, detail=f"Nema dostupnog {resolution}p video toka.")
    except Exception as e:
        logger.error(f"stream_video error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# --- Download audio ---
@app.get("/download/audio/", summary="Preuzmi audio")
async def download_audio(background_tasks: BackgroundTasks, url: str = Query(...)):
    await download_semaphore.acquire()
    try:
        ydl_opts = {
            'outtmpl': os.path.join(OUTPUT_DIR, '%(title)s_audio.mp3'),
            'format': 'bestaudio/best',
            'cookiefile': COOKIES_FILE,
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '128'}],
            'prefer_ffmpeg': True,
            'quiet': True,
            'no_warnings': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        fname = f"{info['title']}_audio.mp3"
        path = os.path.join(OUTPUT_DIR, fname)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        background_tasks.add_task(delete_file_after_delay, path)
        return FileResponse(path, media_type="audio/mpeg", filename=fname)
    except Exception as e:
        logger.error(f"download_audio error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        download_semaphore.release()

# --- Serve downloaded file ---
@app.get("/download/file/{filename}", summary="Poslužuje fajl")
async def serve_file(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File nije pronađen"})
    return FileResponse(path, filename=filename)
