"""Pure parsing for the video URLs accepted by YouTube collection consumers."""

import re
from urllib.parse import parse_qs, urlsplit


YOUTUBE_VIDEO_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
})
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _valid_video_id(value):
    return isinstance(value, str) and bool(VIDEO_ID_RE.fullmatch(value))


def video_id_from_url(url):
    """Return a video ID from an accepted YouTube video URL, else ``""``.

    The collection pipeline has legacy short IDs, so IDs are intentionally not
    restricted to YouTube's current eleven-character convention.  Host and
    path recognition is strict: channel, handle, playlist, foreign, and
    lookalike URLs are not videos.
    """
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in YOUTUBE_VIDEO_HOSTS:
        return ""

    video_id = ""
    if parsed.hostname == "youtu.be":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 1:
            video_id = parts[0]
    elif parsed.path == "/watch":
        values = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        if len(values) == 1:
            video_id = values[0]
    elif parsed.path.startswith("/shorts/"):
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 2 and parts[0] == "shorts":
            video_id = parts[1]
    return video_id if _valid_video_id(video_id) else ""
