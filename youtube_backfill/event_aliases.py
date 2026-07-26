"""Curated public-event and venue aliases used by YouTube matching paths.

The public event JSON intentionally keeps one canonical Japanese display name.
YouTube titles and descriptions often use shorter Japanese names or romanized
English names, so matchers need a shared lookup layer instead of route-local
special cases.

This is deliberately a small code-owned seed.  Once the master data model has
a canonical event-alias store, move these records there so adding an alias no
longer requires a code change.  The matching API in this module is the seam for
that migration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence


PUBLIC_EVENT_ALIASES: Mapping[str, Sequence[str]] = {
    "奥浅草盆踊り": (
        "Oku Asakusa Bon Odori",
        "Oku Asakusa Bon Dance",
        "Oku Asakusa Bon Odori Dance Festival",
    ),
    "自由が丘納涼盆踊り大会": (
        "Jiyugaoka Bon Odori",
        "Jiyugaoka Bon Odori Festival",
        "Jiyugaoka Bon Odori Dance Festival",
        "自由が丘盆踊り",
    ),
    "丸の内de盆踊り": (
        "Marunouchi Bon Odori",
        "Marunouchi Bon Odori Festival",
        "Marunouchi Bon Odori Dance Festival",
        "丸の内盆踊り",
        "東京丸の内盆踊り",
    ),
    "第7回 渋谷盆踊り": (
        "Shibuya Bon Odori",
        "Shibuya Bon Odori Festival",
        "Shibuya Bon Odori Dance Festival",
        "渋谷盆踊り",
    ),
    "神田明神納涼祭り": (
        "Kanda Myojin Noryo Matsuri",
        "Kanda Myojin Summer Festival",
        "Kanda Myojin Shrine Bon Dance",
        "Kanda Myojin Bon Odori",
        "神田明神納涼祭り アニソン盆踊り",
    ),
}


PUBLIC_VENUE_ALIASES: Mapping[str, Sequence[str]] = {
    "自由が丘駅前ロータリー 特設会場": (
        "Jiyugaoka Station",
        "Jiyugaoka Station Rotary",
        "in front of Jiyugaoka Station",
        "自由が丘駅前",
    ),
    "行幸通り": (
        "Gyoko Dori",
        "Gyoko Avenue",
        "in front of Tokyo Station",
    ),
    "渋谷109前": (
        "Shibuya 109",
        "in front of Shibuya 109",
        "SHIBUYA109前",
    ),
    "神田明神境内": (
        "Kanda Myojin Shrine",
        "Kanda Myojin",
        "神田明神",
    ),
}


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


def find_event_alias(canonical: object, text: object, normalize: Callable[[object], str]) -> str:
    return find_alias_in_text(canonical, text, normalize, PUBLIC_EVENT_ALIASES)


def find_venue_alias(canonical: object, text: object, normalize: Callable[[object], str]) -> str:
    return find_alias_in_text(canonical, text, normalize, PUBLIC_VENUE_ALIASES)
