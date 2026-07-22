"""Helpers for yearly occurrence names that belong to the same event series."""

import re


FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
WESTERN_YEAR_RE = re.compile(r"(?<!第)\b20\d{2}\s*(?:年(?:度)?)?\b")
REIWA_YEAR_RE = re.compile(r"令和\s*\d+\s*年(?:度)?")
EMPTY_BRACKETS_RE = re.compile(r"[（(]\s*[）)]")


def compact_spaces(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def series_event_name(name):
    """Return the event-series display name without occurrence-year tokens."""
    text = compact_spaces(name).translate(FULLWIDTH_DIGITS)
    text = WESTERN_YEAR_RE.sub("", text)
    text = REIWA_YEAR_RE.sub("", text)
    text = EMPTY_BRACKETS_RE.sub("", text)
    text = re.sub(r"\s+([）)])", r"\1", text)
    text = re.sub(r"([（(])\s+", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\s・／/｜|:：,、-]+$", "", text)
    return text.strip()
