"""TİD video bağlantılarını gömülebilir biçime çevirir."""
import re
from urllib.parse import parse_qs, urlparse

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_embed(url: str) -> dict | None:
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    video_id = None
    if host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/")[0]
    elif host in {"youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            video_id = parsed.path.split("/")[2]
    if video_id and _YT_ID.match(video_id):
        return {"kind": "youtube", "src": f"https://www.youtube-nocookie.com/embed/{video_id}"}
    if parsed.scheme in {"http", "https"}:
        return {"kind": "file", "src": url}
    return None
