import pathlib
import tempfile
import shutil
import asyncio
import subprocess
import uuid
import logging

from datetime import datetime
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import yt_dlp

# --- Paths ---
BASE_DIR       = pathlib.Path(__file__).parent.resolve()
ORIG_COOKIES   = BASE_DIR / "yt.txt"                              # read-only in /app
TMP_DIR        = pathlib.Path(tempfile.gettempdir())
TMP_COOKIES    = TMP_DIR / "yt_cookies.txt"                      # writable copy
HLS_ROOT       = TMP_DIR / "hls_segments"

# copy cookies into /tmp so yt-dlp can write updates
if not TMP_COOKIES.exists():
    shutil.copy(ORIG_COOKIES, TMP_COOKIES)

# ensure HLS output dir exists
HLS_ROOT.mkdir(parents=True, exist_ok=True)

# --- Concurrency & Logging ---
download_semaphore = asyncio.Semaphore(30)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- FastAPI setup ---
app = FastAPI(title="YouTube Downloader with HLS", version="2.0.4")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/hls", StaticFiles(directory=str(HLS_ROOT)), name="hls")

def load_cookies_header() -> str:
    cookies = []
    with open(ORIG_COOKIES, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 7:
                cookies.append(f"{parts[5]}={parts[6]}")
    return "; ".join(cookies)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.now()
    resp = await call_next(request)
    dt = (datetime.now() - start).microseconds / 1000
    logger.info(f"{request.client.host} {request.method} {request.url} -> {resp.status_code} [{dt:.1f}ms]")
    return resp

@app.get("/", summary="Root")
async def root():
    return JSONResponse({"status": "ok"})

@app.get("/stream/", summary="HLS stream")
async def stream_video(request: Request, url: str = Query(...), resolution: int = Query(1080)):
    try:
        # extract info with cookiefile in /tmp (writable)
        ydl_opts = {
            "quiet": True,
            "cookiefile": str(TMP_COOKIES),
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        vid_fmt = next(
            f for f in info["formats"]
            if f.get("vcodec") != "none"
               and f.get("height") == resolution
               and f.get("ext") == "mp4"
        )
        aud_fmt = max(
            (f for f in info["formats"] if f.get("vcodec") == "none" and f.get("acodec") != "none"),
            key=lambda x: x.get("abr", 0)
        )

        session_id = uuid.uuid4().hex
        sess_dir = HLS_ROOT / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)

        cookie_header = load_cookies_header()
        hdr = ["-headers", f"Cookie: {cookie_header}\r\n"]
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            *hdr, "-i", vid_fmt["url"],
            *hdr, "-i", aud_fmt["url"],
            "-c:v", "copy", "-c:a", "copy",
            "-f", "hls",
            "-hls_time", "4",
            "-hls_list_size", "0",
            "-hls_flags", "delete_segments+append_list",
            "-hls_segment_filename", str(sess_dir / "seg_%03d.ts"),
            str(sess_dir / "index.m3u8")
        ]
        proc = subprocess.Popen(cmd, cwd=str(sess_dir))

        playlist = sess_dir / "index.m3u8"
        for _ in range(20):
            if playlist.exists():
                break
            await asyncio.sleep(0.5)
        else:
            proc.kill()
            raise HTTPException(status_code=500, detail="HLS playlist generation failed")

        playlist_url = request.url_for("hls", path=f"{session_id}/index.m3u8")
        return RedirectResponse(playlist_url)

    except StopIteration:
        raise HTTPException(status_code=404, detail=f"No {resolution}p video stream available")
    except Exception as exc:
        logger.error("stream_video error", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
