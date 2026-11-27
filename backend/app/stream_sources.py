"""Resolve public Twitch/YouTube watch-page URLs to authorized media URLs.
Uses yt-dlp's public extraction only; it does not bypass DRM, logins, paywalls,
private streams, or platform access controls.
"""
import re, subprocess
from urllib.parse import urlparse

def classify_page(value: str):
    u=urlparse(value)
    host=(u.hostname or "").lower()
    if host.endswith("twitch.tv"):
        m=re.search(r"/([A-Za-z0-9_]{2,25})(?:/|$)",u.path)
        return ("twitch",m.group(1).lower()) if m else ("twitch","")
    if host in ("youtube.com","www.youtube.com","m.youtube.com","youtu.be"):
        vid=(re.search(r"(?:v=|youtu\.be/|live/)([A-Za-z0-9_-]{6,})",value) or [None,None])[1]
        return ("youtube",vid or "")
    return ("","")

def resolve_media_url(value: str) -> str:
    u=urlparse(value)
    host=(u.hostname or "").lower()
    if not (host.endswith("twitch.tv") or host.endswith("youtube.com") or host=="youtu.be"):
        return value
    p=subprocess.run(["yt-dlp","--no-warnings","--no-playlist","-f","best","-g",value],
                     capture_output=True,text=True,timeout=35)
    if p.returncode or not p.stdout.strip():
        raise RuntimeError("Could not resolve this public live page. Confirm it is live and publicly accessible; authenticated/DRM streams are not supported. "+(p.stderr or "")[-500:])
    # yt-dlp can emit audio and video URLs on separate lines; FFmpeg accepts the first
    # best combined format where available.
    return p.stdout.strip().splitlines()[0].strip()
