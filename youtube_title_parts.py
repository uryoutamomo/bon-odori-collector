"""Extract event and song hints from YouTube titles."""

from __future__ import annotations

import re
from typing import Any


NOISE_TOKEN_RE = re.compile(
    r"^(?:"
    r"[0-9０-９]+K|4K|8K|HD|HDR|60fps|full\s*version|part\s*[0-9０-９]+|pt\.?\s*[0-9０-９]+|"
    r"20[0-9]{2}|[0-9０-９]{1,2}/[0-9０-９]{1,2}|"
    r"#.*|"
    r"Yasukuni Shrine Mitama Festival.*|"
    r"Asakusa.*|Tokyo.*|Japanese Bon dance.*"
    r")$",
    re.I,
)


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("　", " ")).strip()


def clean_piece(value: Any) -> str:
    text = compact_text(value)
    text = re.sub(r"^[🇦-🇿]+", "", text)
    text = re.sub(r"^[【\[\(（]?[0-9０-９]K[】\]\)）]?", "", text, flags=re.I)
    text = re.sub(r"\s*20[0-9]{2}年?\s*[0-9０-９]{1,2}月\s*[0-9０-９]{1,2}日?.*$", "", text)
    text = re.sub(r"\s*20[0-9]{2}[./][0-9０-９]{1,2}[./][0-9０-９]{1,2}.*$", "", text)
    text = re.sub(r"^[|｜│/／\-–—\s]+|[|｜│/／\-–—\s]+$", "", text)
    text = re.sub(r"\s*#\S+.*$", "", text)
    text = compact_text(text)
    return "" if NOISE_TOKEN_RE.match(text) else text


def split_event_song_tail(value: str) -> tuple[str, str]:
    text = clean_piece(value)
    match = re.match(
        r"^(.*?(?:盆踊り|盆おどり|bon\s*(?:odori|dance)))\s+(.{2,60})$",
        text,
        re.I,
    )
    if not match:
        return text, ""
    event = clean_piece(match.group(1))
    song = clean_piece(match.group(2))
    if not event or not song:
        return text, ""
    if re.search(r"festival|shrine|開催|会場", song, re.I):
        return text, ""
    return event, song


def split_song_text(value: str) -> list[str]:
    songs: list[str] = []
    for part in re.split(r"[|｜│/／、,]+", value):
        song = clean_piece(part)
        if song and song not in songs:
            songs.append(song)
    return songs


def quoted_song_candidates(title: str) -> list[str]:
    songs: list[str] = []
    for quoted in re.findall(r"[「『\"“]([^」』\"”]{1,100})[」』\"”]", title):
        for song in split_song_text(quoted):
            if song and song not in songs:
                songs.append(song)
    return songs


def bracket_event_candidate(title: str) -> str:
    for bracket in re.findall(r"[【\[]([^】\]]{2,100})[】\]]", title):
        value = clean_piece(bracket)
        if not value:
            continue
        if re.search(r"盆踊り|盆おどり|bon\s*(?:odori|dance)|民踊", value, re.I):
            return value
    return ""


def prefix_event_candidate(title: str) -> str:
    text = re.sub(r"^[【\[]?[0-9０-９]K[】\]]?\s*", "", title, flags=re.I)
    text = re.split(r"[「『\"“]", text, maxsplit=1)[0]
    text = re.split(r"\s+[|｜/／]\s+|[|｜/／]", text, maxsplit=1)[0]
    text = re.split(r"\s+[-ー–—]\s+", text, maxsplit=1)[0]
    event, _song = split_event_song_tail(text)
    return event


def dash_song_candidates(title: str, event_candidate: str) -> list[str]:
    parts = [clean_piece(part) for part in re.split(r"\s+[-ー–—]\s+", title)]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return []
    songs: list[str] = []
    event_norm = compact_text(event_candidate).casefold()
    for part in parts[1:]:
        if compact_text(part).casefold() == event_norm:
            continue
        if re.search(r"盆踊り|盆おどり|bon\s*(?:odori|dance)|festival|shrine", part, re.I):
            continue
        for song in split_song_text(part):
            if song and song not in songs:
                songs.append(song)
    return songs


def delimiter_song_candidates(title: str, event_candidate: str) -> list[str]:
    text = re.sub(r"^[【\[]?[0-9０-９]K[】\]]?\s*", "", title, flags=re.I)
    text = re.split(r"[「『\"“]", text, maxsplit=1)[0]
    parts = [clean_piece(part) for part in re.split(r"[|｜│/／]+", text)]
    parts = [part for part in parts if part]
    if not parts:
        return []
    songs: list[str] = []
    _event, first_song = split_event_song_tail(parts[0])
    if first_song:
        songs.append(first_song)
    event_norm = compact_text(event_candidate).casefold()
    for part in parts[1:]:
        if compact_text(part).casefold() == event_norm:
            continue
        if re.search(r"盆踊り|盆おどり|bon\s*(?:odori|dance)|festival|shrine|japanese", part, re.I):
            continue
        for song in split_song_text(part):
            if song and song not in songs:
                songs.append(song)
    return songs


def split_youtube_title(title: Any) -> dict[str, Any]:
    title_text = compact_text(title)
    event_candidate = bracket_event_candidate(title_text) or prefix_event_candidate(title_text)
    songs = quoted_song_candidates(title_text)
    for song in dash_song_candidates(title_text, event_candidate):
        if song not in songs:
            songs.append(song)
    if not songs:
        for song in delimiter_song_candidates(title_text, event_candidate):
            if song not in songs:
                songs.append(song)
    return {
        "title_event_name_candidate": event_candidate,
        "title_song_candidates": songs[:12],
    }
