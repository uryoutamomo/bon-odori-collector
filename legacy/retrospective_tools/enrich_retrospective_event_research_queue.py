#!/usr/bin/env python3
"""Enrich retrospective event research rows with venue/date hints from evidence text."""

import argparse
import json
import re
from pathlib import Path


QUEUE = Path("data/retrospective_event_research_queue.json")
DRY_RUN = Path("data/retrospective_occurrence_dry_run.json")
OUT = Path("data/retrospective_event_research_enriched.json")
OUT_MD = Path("data/retrospective_event_research_enriched.md")

VENUE_HINT_RE = re.compile(
    r"(?:会場|場所|＠|@|at|AT)[：:\s]*([一-龥ぁ-んァ-ヶーA-Za-z0-9・（）() ]{2,40})"
)
VENUE_SUFFIX_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・（）() ]{2,32}(?:公園|広場|小学校|中学校|学校|会館|ホール|神社|寺|センター|ターミナル|なかいち|マロニエ))"
)
MD_RE = re.compile(r"(?:(\d{1,2})月(\d{1,2})日|(\d{1,2})/(\d{1,2}))")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def clean_hint(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = re.sub(r"^(?:\d{1,2}月\d{1,2}日は?|本日|ぜひ|へ|で)", "", value).strip()
    value = re.sub(r"^(?:場所|会場|於|at)\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.split(r"(?:日時|時間|日程|https?://|#|、|。|\n)", value)[0].strip()
    value = value.strip(" 　:：,，.。()（）")
    return value[:80]


def candidate_map(dry_run):
    return {row.get("candidate_key"): row for row in dry_run.get("new_event_candidates") or []}


def evidence_text(candidate):
    return "\n".join(ev.get("text") or "" for ev in candidate.get("evidence") or [])


def evidence_observed_year(candidate, fallback=""):
    for ev in candidate.get("evidence") or []:
        for value in (ev.get("observed_at"), ev.get("spoken_at")):
            match = re.search(r"20\d{2}", str(value or ""))
            if match:
                return int(match.group(0))
    match = re.search(r"20\d{2}", str(fallback or ""))
    return int(match.group(0)) if match else None


def evidence_observed_date(candidate):
    for ev in candidate.get("evidence") or []:
        for value in (ev.get("observed_at"), ev.get("spoken_at")):
            match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", str(value or ""))
            if match:
                return "-".join(match.groups())
    return ""


def date_hint(row, candidate, text):
    explicit = list(MD_RE.finditer(text or ""))
    year = evidence_observed_year(candidate, row.get("estimated_date"))
    if explicit and year:
        month = int(explicit[0].group(1) or explicit[0].group(3))
        day = int(explicit[0].group(2) or explicit[0].group(4))
        return f"{year:04d}-{month:02d}-{day:02d}"
    if "笠間納涼盆踊り花火大会2026" in text or "8/8(土) 笠間納涼盆踊り花火大会2026" in text:
        return "2026-08-08"
    if "本日" in text:
        observed_date = evidence_observed_date(candidate)
        if observed_date:
            return observed_date
    return row.get("estimated_date") or ""


def venue_hints(text):
    values = []
    for regex in (VENUE_HINT_RE, VENUE_SUFFIX_RE):
        for match in regex.finditer(text or ""):
            value = clean_hint(match.group(1))
            if not value:
                continue
            if value.startswith(("だと思います", "へお越し", "お越し", "開催されます")):
                continue
            if len(value) > 28 and any(word in value for word in ("開催", "当日は", "踊り")):
                continue
            if value not in values:
                values.append(value)
    return values[:6]


def local_overrides(row, text):
    name = row.get("event_name") or ""
    overrides = {
        "suggested_event_name": "",
        "venue_hints": [],
        "suggested_date": "",
        "research_status": "needs_human_confirmation",
        "registration_recommendation": "要調査",
        "research_note": "",
    }
    if "藤沢七夕まつり" in name:
        overrides.update({
            "suggested_event_name": "藤沢七夕まつり",
            "venue_hints": ["辻堂駅北口神台公園", "辻堂神台公園"],
            "research_status": "registered_with_local_evidence",
            "registration_recommendation": "Notion登録済み",
            "research_note": "複数のX本文で7月4日・辻堂神台公園/辻堂駅北口神台公園・大盆踊り大会が一致。",
        })
    elif "マロニエまつり" in name:
        overrides.update({
            "suggested_event_name": "浅草橋マロニエまつり盆踊り",
            "venue_hints": ["ヒューリック浅草橋ビル前", "浅草橋マロニエ"],
            "research_status": "registered_after_external_confirmation",
            "registration_recommendation": "Notion登録済み（過去実績として保持）",
            "research_note": "こと裏取りで第二部会場はヒューリック浅草橋ビル前、2026-05-09開催済みと確認。来年の名寄せ用に過去実績登録。",
        })
    elif "西馬音内盆踊り" in name and "ヘリテージ・アドベンチャラー" in text:
        overrides.update({
            "suggested_event_name": "ヘリテージ・アドベンチャラー寄港 西馬音内盆踊り",
            "venue_hints": ["秋田港フェリーターミナル", "道の駅あきた港 セリオン"],
            "research_status": "registered_with_local_evidence",
            "registration_recommendation": "Notion登録済み",
            "research_note": "セリオン公式投稿。ターミナルでのイベントとして17:30西馬音内盆踊り、18:00出港と記載。",
        })
    elif "西馬音内盆踊り" in name and "エリアなかいち" in text:
        overrides.update({
            "suggested_event_name": "まるっと秋田博 西馬音内盆踊り",
            "venue_hints": ["エリアなかいち"],
            "research_status": "registered_with_local_evidence",
            "registration_recommendation": "Notion登録済み",
            "research_note": "まるっと秋田博公式投稿。エリアなかいち会場で19:45から演舞と記載。",
        })
    elif "足寄ふるさと盆踊り" in name:
        overrides.update({
            "suggested_event_name": "第44回 足寄ふるさと盆踊り・両国花火大会",
            "venue_hints": ["足寄町民センター前グラウンド・駐車場", "利別川河川敷両国橋下流", "足寄郡足寄町"],
            "research_status": "registered_after_external_confirmation",
            "registration_recommendation": "Notion登録済み（会場は要レビュー）",
            "research_note": "こと裏取りで盆踊り・露店・ステージは足寄町民センター前グラウンド＋駐車場、花火打ち上げは利別川両国橋下流と確認。既存Notion会場を盆踊り本体会場へ修正済み。",
        })
    elif "笠間納涼盆踊り" in name:
        overrides.update({
            "suggested_event_name": "笠間納涼盆踊り花火大会2026",
            "suggested_date": "2026-08-08",
            "venue_hints": ["笠間大池公園（笠間ポレポレシティ前）"],
            "research_status": "registered_after_external_confirmation",
            "registration_recommendation": "Notion登録済み（会場は要レビュー）",
            "research_note": "こと裏取りで会場は笠間大池公園（笠間ポレポレシティ前）と確認。23区外のため公開JSONからは除外対象。",
        })
    return overrides


def suggested_event_name(row, text):
    name = row.get("event_name") or ""
    name = re.sub(r"^\d{1,2}月\d{1,2}日", "", name).strip()
    if "マロニエまつり" in name:
        return "浅草橋マロニエまつり盆踊り"
    if "エリアなかいち" in text and "西馬音内盆踊り" in name:
        return "まるっと秋田博 西馬音内盆踊り"
    return name


def build_enriched(queue, dry_run):
    candidates = candidate_map(dry_run)
    rows = []
    for row in queue.get("rows") or []:
        candidate = candidates.get(row.get("candidate_key"), {})
        text = evidence_text(candidate)
        hints = []
        if row.get("venue"):
            hints.append(row["venue"])
        for hint in venue_hints(text):
            if hint in {"演舞となります"}:
                continue
            if hint not in hints:
                hints.append(hint)
        overrides = local_overrides(row, text)
        for hint in overrides["venue_hints"]:
            if hint not in hints:
                hints.append(hint)
        rows.append({
            **row,
            "suggested_event_name": overrides["suggested_event_name"] or suggested_event_name(row, text),
            "suggested_date": overrides["suggested_date"] or date_hint(row, candidate, text),
            "venue_hints": hints,
            "evidence_text_sample": text[:600],
            "research_status": overrides["research_status"],
            "registration_recommendation": overrides["registration_recommendation"],
            "research_note": overrides["research_note"],
        })
    return {
        "generated_by": "enrich_retrospective_event_research_queue.py",
        "source": str(QUEUE),
        "count": len(rows),
        "rows": rows,
    }


def markdown(data):
    lines = [
        "# Retrospective event research enriched",
        "",
        f"- count: {data['count']}",
        "",
        "| event | suggested event | suggested date | venue hints | status | recommendation | source |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in data.get("rows") or []:
        lines.append(
            "| {event} | {suggested} | {date} | {hints} | {status} | {recommendation} | {url} |".format(
                event=(row.get("event_name") or "").replace("|", " "),
                suggested=(row.get("suggested_event_name") or "").replace("|", " "),
                date=row.get("suggested_date") or row.get("estimated_date") or "",
                hints=", ".join(row.get("venue_hints") or []).replace("|", " "),
                status=row.get("research_status") or "",
                recommendation=(row.get("registration_recommendation") or "").replace("|", " "),
                url=row.get("source_url") or "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=QUEUE)
    parser.add_argument("--dry-run", type=Path, default=DRY_RUN)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--md-out", type=Path, default=OUT_MD)
    args = parser.parse_args()

    data = build_enriched(load_json(args.queue, {}), load_json(args.dry_run, {}))
    write_json(args.out, data)
    write_text(args.md_out, markdown(data))
    print(f"research enrichment: count={data['count']} -> {args.out}")


if __name__ == "__main__":
    main()
