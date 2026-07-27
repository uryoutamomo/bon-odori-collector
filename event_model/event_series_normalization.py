"""Normalize yearly occurrence names that belong to one event series."""

import re


FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
WESTERN_YEAR_RE = re.compile(r"(?<!第)\b20\d{2}\s*(?:年(?:度)?)?\b")
REIWA_YEAR_RE = re.compile(r"令和\s*\d+\s*年(?:度)?")
EMPTY_BRACKETS_RE = re.compile(r"[（(]\s*[）)]")
EDITION_RE = re.compile(r"第\s*[0-9]+\s*回\s*")


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


def strip_occurrence_edition(name):
    """Drop the 第N回 edition counter, which belongs to one occurrence, not the series."""
    text = compact_spaces(name).translate(FULLWIDTH_DIGITS)
    stripped = EDITION_RE.sub("", text)
    stripped = EMPTY_BRACKETS_RE.sub("", stripped)
    stripped = re.sub(r"\s+([）)」])", r"\1", stripped)
    stripped = re.sub(r"([（(「])\s+", r"\1", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    stripped = re.sub(r"[\s・／/｜|:：,、-]+$", "", stripped).strip()
    return stripped or text


def public_series_name(name):
    """Public-facing event name: no occurrence year and no 第N回 edition counter.

    Series identity (event_series.series_key) still uses series_event_name, so
    renaming what readers see does not renumber RDB series ids.
    """
    return strip_occurrence_edition(series_event_name(name))
