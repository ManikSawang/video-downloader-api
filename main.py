"""
Production-Ready Video Downloader API using FastAPI and yt-dlp.
Supports YouTube, Instagram, TikTok, and Pinterest direct MP4 extraction.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="StreamFetch Video Downloader API",
    description=(
        "Custom FastAPI + yt-dlp service to extract direct MP4 URLs, "
        "titles, thumbnails, and durations."
    ),
    version="1.0.0",
)

# Enable CORS so your frontend website can call /api/fetch directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

SUPPORTED_DOMAINS = {
    "youtube": ("youtube.com", "youtu.be", "m.youtube.com", "youtube-nocookie.com"),
    "instagram": ("instagram.com", "www.instagram.com", "instagr.am"),
    "tiktok": ("tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"),
    "pinterest": ("pinterest.com", "www.pinterest.com", "pin.it"),
}


class VideoFetchResponse(BaseModel):
    success: bool = Field(..., description="Whether metadata extraction succeeded")
    platform: Optional[str] = Field(None, description="Detected source platform")
    title: Optional[str] = Field(None, description="Video title or caption")
    thumbnail: Optional[str] = Field(None, description="High-resolution thumbnail URL")
    duration: Optional[int] = Field(None, description="Video duration in seconds")
    duration_string: Optional[str] = Field(None, description="Formatted duration (MM:SS)")
    download_url: Optional[str] = Field(None, description="Direct MP4 video stream URL")
    error: Optional[str] = Field(None, description="Error details when success is False")


def detect_platform(raw_url: str) -> Optional[str]:
    """Validate URL structure and match against supported video platforms."""
    try:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        host = parsed.netloc.lower().split(":")[0]
        for platform, domains in SUPPORTED_DOMAINS.items():
            if any(host == d or host.endswith(f".{d}") for d in domains):
                return platform
        return None
    except Exception:
        return None


def build_ydl_opts() -> Dict[str, Any]:
    """
    Configure yt-dlp to bypass common rate/geo blocks, suppress stdout noise,
    prevent full playlist scraping, and prioritize direct progressive MP4 streams.
    """
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "socket_timeout": 20,
        "retries": 3,
        "format": "best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best[vcodec!=none][acodec!=none]/best",
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Mode": "navigate",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["hls", "dash"],
            },
            "tiktok": {
                "app_name": ["musical_ly"],
            },
        },
    }


def select_best_mp4_url(info: Dict[str, Any]) -> Optional[str]:
    """
    Extract the most reliable direct MP4 URL from yt-dlp's info dictionary.
    Handles single-stream responses as well as multi-format lists.
    """
    direct_url = info.get("url")
    if direct_url and ".m3u8" not in direct_url and ".mpd" not in direct_url:
        return direct_url

    requested_formats: List[Dict[str, Any]] = info.get("requested_formats") or []
    for fmt in requested_formats:
        fmt_url = fmt.get("url")
        if fmt_url and fmt.get("ext") == "mp4" and ".m3u8" not in fmt_url:
            return fmt_url

    formats: List[Dict[str, Any]] = info.get("formats") or []
    progressive_mp4s = [
        f for f in formats
        if f.get("url")
        and f.get("ext") == "mp4"
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and ".m3u8" not in f.get("url", "")
        and f.get("protocol") in ("https", "http", None)
    ]
    if progressive_mp4s:
        progressive_mp4s.sort(
            key=lambda x: (x.get("height") or 0, x.get("tbr") or 0),
            reverse=True,
        )
        return progressive_mp4s[0]["url"]

    any_mp4 = [
        f for f in formats
        if f.get("url")
        and f.get("ext") == "mp4"
        and ".m3u8" not in f.get("url", "")
    ]
    if any_mp4:
        any_mp4.sort(
            key=lambda x: (x.get("height") or 0, x.get("tbr") or 0),
            reverse=True,
        )
        return any_mp4[0]["url"]

    return direct_url


def extract_video_metadata(target_url: str) -> Dict[str, Any]:
    """Synchronous worker executed in a threadpool so FastAPI's event loop stays non-blocking."""
    ydl_opts = build_ydl_opts()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target_url, download=False)
        if not info:
            raise ValueError("Unable to extract video information from the provided URL.")

        if "entries" in info and isinstance(info["entries"], list) and info["entries"]:
            info = info["entries"][0]

        download_url = select_best_mp4_url(info)
        if not download_url:
            raise ValueError("No direct MP4 stream could be resolved for this video.")

        duration_raw = info.get("duration")
        duration_sec = int(round(duration_raw)) if isinstance(duration_raw, (int, float)) else None

        thumbnail = info.get("thumbnail")
        if not thumbnail and isinstance(info.get("thumbnails"), list) and info["thumbnails"]:
            thumbnail = info["thumbnails"][-1].get("url")

        return {
            "title": info.get("title") or info.get("description") or "Untitled Video",
            "thumbnail": thumbnail,
            "duration": duration_sec,
            "duration_string": info.get("duration_string"),
            "download_url": download_url,
        }


@app.get("/api/fetch", response_model=VideoFetchResponse)
async def fetch_video_metadata(
    url: str = Query(..., min_length=8, description="Public video URL from YouTube, Instagram, TikTok, or Pinterest")
):
    """
    GET /api/fetch?url=<video_url>
    Extracts direct MP4 download URL, title, thumbnail, and duration without downloading the file to disk.
    """
    cleaned_url = url.strip()
    platform = detect_platform(cleaned_url)
    if not platform:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "platform": None,
                "title": None,
                "thumbnail": None,
                "duration": None,
                "duration_string": None,
                "download_url": None,
                "error": "Unsupported or invalid URL. Please provide a valid YouTube, Instagram, TikTok, or Pinterest video link.",
            },
        )

    try:
        metadata = await asyncio.to_thread(extract_video_metadata, cleaned_url)
        return {
            "success": True,
            "platform": platform,
            "title": metadata["title"],
            "thumbnail": metadata["thumbnail"],
            "duration": metadata["duration"],
            "duration_string": metadata["duration_string"],
            "download_url": metadata["download_url"],
            "error": None,
        }
    except yt_dlp.utils.DownloadError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "platform": platform,
                "title": None,
                "thumbnail": None,
                "duration": None,
                "duration_string": None,
                "download_url": None,
                "error": f"Extraction blocked or video unavailable: {str(exc).splitlines()[-1]}",
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": f"Internal extraction error: {str(exc)}",
            },
        ) from exc