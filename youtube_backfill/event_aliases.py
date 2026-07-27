"""Public-event and venue aliases used by YouTube matching paths.

The public event JSON intentionally keeps one canonical Japanese display name.
YouTube titles and descriptions often use shorter Japanese names or romanized
English names, so matchers need a shared lookup layer instead of route-local
special cases.

These records used to be a code-owned seed because the master RDB had no
event-series alias store.  They now live in the RDB (``event_series_aliases``
and ``venue_aliases``) and reach this module through the runtime file written
by ``build_event_alias_runtime.py``.  Adding an alias is therefore a data
change: insert the row, rebuild the runtime file, and every matching path picks
it up without a code edit.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


OCCURRENCE_EDITION_PREFIX_RE = re.compile(r"^第\s*[0-9０-９]+\s*回\s*")

DEFAULT_ALIAS_RUNTIME_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "event_alias_runtime.json"
)
# Set BON_ODORI_EVENT_ALIAS_RUNTIME to compare matching behaviour against an
# alternative alias table without editing the committed runtime file.
RUNTIME_PATH_ENV = "BON_ODORI_EVENT_ALIAS_RUNTIME"

_RUNTIME_CACHE: dict[str, Mapping[str, Sequence[str]]] | None = None


def alias_runtime_path() -> Path:
    override = os.environ.get(RUNTIME_PATH_ENV, "").strip()
    return Path(override) if override else DEFAULT_ALIAS_RUNTIME_PATH


def _read_runtime(path: Path) -> dict[str, Mapping[str, Sequence[str]]]:
    empty: dict[str, Mapping[str, Sequence[str]]] = {"event_aliases": {}, "venue_aliases": {}}
    if not path.exists():
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(payload, dict):
        return empty
    tables = {}
    for key in ("event_aliases", "venue_aliases"):
        table = payload.get(key)
        tables[key] = table if isinstance(table, dict) else {}
    return tables


def load_alias_runtime(path: Path | str | None = None, *, refresh: bool = False):
    """Return the alias tables, reading the runtime file at most once."""

    global _RUNTIME_CACHE
    if path is not None or refresh or _RUNTIME_CACHE is None:
        _RUNTIME_CACHE = _read_runtime(Path(path) if path is not None else alias_runtime_path())
    return _RUNTIME_CACHE


def public_event_aliases() -> Mapping[str, Sequence[str]]:
    return load_alias_runtime()["event_aliases"]


def public_venue_aliases() -> Mapping[str, Sequence[str]]:
    return load_alias_runtime()["venue_aliases"]


def find_alias_in_text(
    canonical: object,
    text: object,
    normalize: Callable[[object], str],
    aliases: Mapping[str, Sequence[str]],
) -> str:
    """Return the first curated alias contained in normalized text."""

    text_key = normalize(text)
    if not text_key:
        return ""
    for alias in aliases.get(str(canonical or ""), ()):
        alias_key = normalize(alias)
        if alias_key and alias_key in text_key:
            return alias
    return ""


def event_alias_key(canonical: object) -> str:
    """Return a series-level alias key without an occurrence edition prefix.

    Public display names are moving from values such as ``第7回 渋谷盆踊り``
    to ``渋谷盆踊り``.  Normalizing only the lookup key keeps aliases working
    before and after that export change without changing series identifiers.
    """

    return OCCURRENCE_EDITION_PREFIX_RE.sub("", str(canonical or "")).strip()


def find_event_alias(canonical: object, text: object, normalize: Callable[[object], str]) -> str:
    return find_alias_in_text(event_alias_key(canonical), text, normalize, public_event_aliases())


def find_venue_alias(canonical: object, text: object, normalize: Callable[[object], str]) -> str:
    return find_alias_in_text(canonical, text, normalize, public_venue_aliases())
