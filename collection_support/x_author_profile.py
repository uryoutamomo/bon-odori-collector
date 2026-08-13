"""Read an X author's self-introduction, and record where it was found.

``collect.py`` used to read ``author["description"]`` only.  Every account in
the 2026-08-12 snapshot came out with an empty bio, including 313 accounts
whose newest post was created *during* that run — so "the stored posts predate
the feature" cannot explain it.  The provider therefore either omits the bio
from tweet author objects or carries it under a different key: the same
payload is already read from two different places elsewhere in this repo
(``discover_x_social_graph.profile_text`` reads ``description`` *and*
``profile_bio.description``).

So this module reads every location the bio has been seen at, and keeps a
counter of which one supplied it.  The counter exists because a silent empty
string is what let this go unnoticed for a day: the daily log now has to say
how many authors were inspected and how many produced a bio.

The probe deliberately records key *names* only.  This repository is public,
so its CI logs are public, and a bio is a person's own writing.
"""

from __future__ import annotations

from typing import Any


# Ordered by how much we trust the location; the first non-empty one wins.
BIO_PATHS: tuple[tuple[str, ...], ...] = (
    ("description",),
    ("profile_bio", "description"),
    ("rawDescription",),
    ("legacy", "description"),
    ("bio",),
    ("profile_description",),
)


def _dig(author: dict, path: tuple[str, ...]) -> str:
    node: Any = author
    for key in path:
        if not isinstance(node, dict):
            return ""
        node = node.get(key)
    return node.strip() if isinstance(node, str) else ""


class ProfileBioProbe:
    """Counts where bios came from so an all-empty run cannot pass silently."""

    def __init__(self) -> None:
        self.authors = 0
        self.found_by_path: dict[str, int] = {}
        self.author_keys: set[str] = set()

    def record(self, author: dict, path: tuple[str, ...] | None) -> None:
        self.authors += 1
        if isinstance(author, dict):
            self.author_keys.update(str(key) for key in author)
        if path:
            name = ".".join(path)
            self.found_by_path[name] = self.found_by_path.get(name, 0) + 1

    @property
    def found(self) -> int:
        return sum(self.found_by_path.values())

    def report(self) -> str:
        """One log line: counts plus the author key names the provider sent."""
        if not self.authors:
            return "[x/profile] 著者情報を1件も見ていません"
        by_path = ", ".join(
            f"{name}={count}" for name, count in sorted(self.found_by_path.items())
        ) or "なし"
        keys = ",".join(sorted(self.author_keys)) or "なし"
        return (
            f"[x/profile] 著者 {self.authors}件中 自己紹介文あり {self.found}件"
            f"（取得元: {by_path}） / 著者オブジェクトのキー: {keys}"
        )

    def reset(self) -> None:
        self.authors = 0
        self.found_by_path = {}
        self.author_keys = set()


PROBE = ProfileBioProbe()


def author_profile_description(author: Any, probe: ProfileBioProbe | None = PROBE) -> str:
    """Return the author's bio from whichever key the provider used."""
    if not isinstance(author, dict):
        if probe is not None:
            probe.record({}, None)
        return ""
    for path in BIO_PATHS:
        text = _dig(author, path)
        if text:
            if probe is not None:
                probe.record(author, path)
            return text
    if probe is not None:
        probe.record(author, None)
    return ""
