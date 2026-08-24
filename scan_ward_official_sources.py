#!/usr/bin/env python3
"""Scan ward-owned source pages into official-source review candidates."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from collection_support.proactive_search import BON_KEYWORDS, scan_official_sources


ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "data/ward_official_source_registry.json"
DEFAULT_OUTPUT = ROOT / "data/ward_official_source_candidates.json"
DEFAULT_MARKDOWN = ROOT / "data/ward_official_source_candidates.md"
SAFETY_BOUNDARY = "official-source review candidates only; no canonical or public event write"


def load_registry(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    priority_wards = set(payload.get("priority_wards") or [])
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("ward official-source registry requires sources list")
    identifiers = [str(row.get("id") or "") for row in sources]
    if not all(identifiers) or len(identifiers) != len(set(identifiers)):
        raise ValueError("ward official-source registry ids must be non-empty and unique")
    for row in sources:
        if row.get("ward") not in priority_wards:
            raise ValueError(f"source ward is not registered as priority: {row.get('ward')}")
        host = urlparse(str(row.get("url") or "")).hostname or ""
        if not (host.endswith(".lg.jp") or host.endswith(".tokyo.jp")):
            raise ValueError(f"source is not on an official ward domain: {row.get('url')}")
    return [row for row in sources if row.get("enabled", True)]


def target_for(source: dict) -> dict:
    return {
        "venue": source["ward"],
        "event_name": source["title"],
        "aliases": [source["ward"]],
        "confirmation_terms": list(BON_KEYWORDS),
        "official_sources": [source["url"]],
        "official_source_type": "official",
    }


def stable_id(source_id: str, url: str, row_key: str = "") -> str:
    raw = f"{source_id}|{url}" + (f"|{row_key}" if row_key else "")
    return "ward-official-" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _clean_cell(value: str) -> str:
    return re.sub(r"\s*/\s*", " / ", re.sub(r"\s+", " ", html.unescape(value))).strip(" /\t\r\n")


class _StructuredHTMLParser(HTMLParser):
    """Collect table cells and list items without adding a parser dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict]]] = []
        self.list_items: list[str] = []
        self._table_depth = 0
        self._table: list[list[dict]] | None = None
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._li_depth = 0
        self._li_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table = []
        elif tag == "tr" and self._table_depth == 1:
            self._row = []
        elif tag in {"th", "td"} and self._table_depth == 1 and self._row is not None:
            self._cell = {"header": tag == "th", "parts": []}
        elif tag in {"br", "p", "div"} and self._cell is not None and self._cell["parts"]:
            self._cell["parts"].append(" / ")
        if tag == "li":
            self._li_depth += 1
            if self._li_depth == 1:
                self._li_parts = []
        elif tag in {"br", "p"} and self._li_parts:
            self._li_parts.append(" / ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append({"header": self._cell["header"], "text": _clean_cell("".join(self._cell["parts"]))})
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(cell["text"] for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table_depth:
            if self._table_depth == 1 and self._table is not None:
                self.tables.append(self._table)
                self._table = None
            self._table_depth -= 1
        if tag == "li" and self._li_depth:
            if self._li_depth == 1 and self._li_parts is not None:
                value = _clean_cell("".join(self._li_parts))
                if value:
                    self.list_items.append(value)
                self._li_parts = None
            self._li_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["parts"].append(data)
        if self._li_parts is not None:
            self._li_parts.append(data)


HEADER_PATTERNS = {
    "date": ("開催日", "日程", "開催日時", "日時", "期日"),
    "time": ("開始時間", "開催時間", "時間"),
    "name": ("町会・自治会名", "自治会名", "町会名", "祭名称", "行事名", "催事名", "イベント名", "名称", "主催"),
    "venue": ("会場", "場所"),
    "address": ("住所", "所在地"),
}


def _header_mapping(row: list[dict]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(row):
        label = re.sub(r"\s+", "", cell["text"])
        for role, patterns in HEADER_PATTERNS.items():
            if role not in mapping and any(pattern in label for pattern in patterns):
                mapping[role] = index
    return mapping


def _field(cells: list[str], mapping: dict[str, int], role: str) -> str:
    index = mapping.get(role)
    return cells[index] if index is not None and index < len(cells) else ""


def _structured_candidate(source: dict, url: str, year: int, *, parse_mode: str, row_index: int,
                          event_name: str, date_text: str, time_text: str = "", venue: str = "",
                          address: str = "", raw_text: str = "") -> dict:
    combined_date = " / ".join(value for value in (date_text, time_text) if value)
    row_key = "|".join((event_name, combined_date, venue, address))
    status_hint = "cancelled" if "中止" in raw_text else ""
    name_parts = [part.strip() for part in event_name.split(" / ") if part.strip()]
    festival_parts = [part.strip("()（） ") for part in name_parts if part.startswith(("(", "（"))]
    organizer_parts = [part for part in name_parts if not part.startswith(("(", "（"))]
    return {
        "id": stable_id(source["id"], url, row_key),
        "decision": "pending",
        "suggested_source_type": "official",
        "suggested_score": 92 if source.get("priority") == "high" else 87,
        "reason": "区公式イベント一覧から行単位で抽出",
        "source_origin": "ward_official_source_registry",
        "source_registry_id": source["id"],
        "source_url": url,
        "source_domain": urlparse(url).netloc.lower(),
        "venue": venue,
        "event_name": event_name,
        "organizer": " / ".join(organizer_parts),
        "festival_name": " / ".join(festival_parts),
        "region": source["ward"],
        "event_year": year,
        "event_date_text": combined_date,
        "address": address,
        "status_hint": status_hint,
        "memo": f"ward registry: {source['id']} / {raw_text[:1000]}",
        "registry_source_type": source.get("source_type") or "",
        "registry_format": source.get("format") or "",
        "parse_mode": parse_mode,
        "source_row_index": row_index,
    }


def extract_structured_event_rows(raw_html: str, source: dict, url: str, year: int) -> list[dict]:
    parser = _StructuredHTMLParser()
    parser.feed(raw_html)
    candidates: list[dict] = []
    trust_listing_context = source.get("structured_extraction") == "html_event_table"

    for table_index, table in enumerate(parser.tables):
        header_index, mapping = -1, {}
        for index, row in enumerate(table):
            candidate_mapping = _header_mapping(row)
            if "date" in candidate_mapping and "name" in candidate_mapping and (
                "venue" in candidate_mapping or "address" in candidate_mapping
            ):
                header_index, mapping = index, candidate_mapping
                break
        if header_index < 0:
            continue
        for row_index, row in enumerate(table[header_index + 1:], start=header_index + 1):
            cells = [cell["text"] for cell in row]
            raw_text = " / ".join(value for value in cells if value)
            date_text = _field(cells, mapping, "date")
            event_name = _field(cells, mapping, "name")
            if not date_text or not event_name or not re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*日", date_text):
                continue
            if not trust_listing_context and not any(keyword in raw_text for keyword in BON_KEYWORDS):
                continue
            candidates.append(_structured_candidate(
                source, url, year,
                parse_mode="html_table_row",
                row_index=table_index * 10000 + row_index,
                event_name=event_name,
                date_text=date_text,
                time_text=_field(cells, mapping, "time"),
                venue=_field(cells, mapping, "venue"),
                address=_field(cells, mapping, "address"),
                raw_text=raw_text,
            ))

    for row_index, value in enumerate(parser.list_items):
        if not any(keyword in value for keyword in BON_KEYWORDS):
            continue
        date_match = re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*日", value)
        if not date_match:
            continue
        candidates.append(_structured_candidate(
            source, url, year,
            parse_mode="html_list_item",
            row_index=row_index,
            event_name=value,
            date_text=date_match.group(0),
            raw_text=value,
        ))
    return list({row["id"]: row for row in candidates}.values())


def fetch_html_source(url: str, timeout: int = 20) -> str | None:
    request = Request(url, headers={"User-Agent": "bon-odori-collector/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if "text/html" not in response.headers.get("Content-Type", ""):
            return None
        return response.read(1_500_000).decode("utf-8", errors="ignore")


def candidate_row(source: dict, scan: dict, year: int) -> dict:
    url = str(scan.get("source_url") or source["url"])
    title = str(scan.get("title") or source["title"])
    evidence = scan.get("evidence") if isinstance(scan.get("evidence"), dict) else {}
    memo = " / ".join(
        value for value in (
            f"ward registry: {source['id']}",
            str(evidence.get("text") or "")[:500],
            str(source.get("crawl_notes") or ""),
        ) if value
    )
    return {
        "id": stable_id(source["id"], url),
        "decision": "pending",
        "suggested_source_type": "official",
        "suggested_score": 90 if source.get("priority") == "high" else 85,
        "reason": "区公式source registryから盆踊り文脈を発見",
        "source_origin": "ward_official_source_registry",
        "source_registry_id": source["id"],
        "source_url": url,
        "source_domain": urlparse(url).netloc.lower(),
        "venue": "",
        "event_name": title,
        "region": source["ward"],
        "event_year": year,
        "event_date_text": ", ".join(scan.get("detected_dates") or []),
        "memo": memo,
        "registry_source_type": source.get("source_type") or "",
        "registry_format": source.get("format") or "",
    }


def scan_registry(sources: list[dict], year: int, *, timeout: int = 20, scan_fn=scan_official_sources,
                  html_fetch_fn=fetch_html_source) -> tuple[list[dict], list[dict]]:
    rows, source_reports = [], []
    for source in sources:
        link_limit = int(source.get("scan_link_limit", 12))
        scanned = scan_fn(target_for(source), year, timeout=timeout, max_links_per_source=link_limit)
        confirmed = [row for row in scanned if row.get("status") == "confirmed"]
        structured_count = 0
        fallback_count = 0
        for row in confirmed:
            url = str(row.get("source_url") or source["url"])
            structured_rows = []
            try:
                raw_html = html_fetch_fn(url, timeout=timeout)
                if raw_html:
                    structured_rows = extract_structured_event_rows(raw_html, source, url, year)
            except Exception as exc:
                print(f"[ward-official] 行単位抽出失敗（{url}）: {exc}")
            if structured_rows:
                rows.extend(structured_rows)
                structured_count += len(structured_rows)
            else:
                rows.append(candidate_row(source, row, year))
                fallback_count += 1
        source_reports.append(
            {
                "source_registry_id": source["id"],
                "ward": source["ward"],
                "url": source["url"],
                "checked_count": len(scanned),
                "confirmed_count": len(confirmed),
                "structured_candidate_count": structured_count,
                "page_fallback_count": fallback_count,
                "status": "confirmed" if confirmed else "no_bon_context_found",
            }
        )
    deduped = {row["id"]: row for row in rows}
    return sorted(deduped.values(), key=lambda row: (row["region"], row["source_url"])), source_reports


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# 区公式ソース発見候補",
        "",
        f"- safety: {payload['safety_boundary']}",
        f"- registry sources: {payload['registry_source_count']}",
        f"- candidates: {payload['candidate_count']}",
        "",
        "| 区 | ページ | URL | 日付候補 |",
        "|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(f"| {row['region']} | {row['event_name'].replace('|', '｜')} | [link]({row['source_url']}) | {row['event_date_text']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    sources = load_registry(args.registry)
    rows, source_reports = scan_registry(sources, args.year, timeout=args.timeout)
    payload = {
        "schema_version": 1,
        "generated_by": "scan_ward_official_sources.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_year": args.year,
        "safety_boundary": SAFETY_BOUNDARY,
        "canonical_write_count": 0,
        "registry_source_count": len(sources),
        "candidate_count": len(rows),
        "ward_counts": dict(Counter(row["region"] for row in rows)),
        "source_reports": source_reports,
        "rows": rows,
    }
    write_json(args.out_json, payload)
    write_markdown(args.out_md, payload)
    print(f"ward official sources: sources={len(sources)} candidates={len(rows)} -> {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
