import json
import re
from pathlib import Path

from triage_blog_venue_candidates import normalize


TRIAGE_FILE = Path("data/venue_candidate_triage.json")
ROWS_FILE = Path("data/blog_venue_rows.json")
OUT_FILE = Path("data/blog_registration_candidates.json")


MONTH_RE = re.compile(r"(\d{1,2})/")


VENUE_ALIASES = {
    "京王線芦花公園": "京王線芦花公園駅前ロータリー",
    "芦花公園": "京王線芦花公園駅前ロータリー",
    "希望ヶ丘団地": "希望ヶ丘団地 テニスコート",
    "二子玉川西地区ふれあい広場": "二子玉川西地区ふれあい広場(246高架下)",
    "祖師谷商店街": "小田急線祖師ヶ谷大蔵駅前広場",
    "祖師谷昇進会商店街": "祖師谷昇進会商店街",
    "あずま通り商店街": "あずま通り商店街",
    "下北沢あずま通り商店街": "あずま通り商店街",
    "蒲田西口商店街": "JR蒲田駅西口駅前広場",
    "喜多見商店街": "小田急線喜多見駅前 南口広場",
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def month_from_date_text(text):
    match = MONTH_RE.search(text or "")
    if not match:
        return ""
    return f"{int(match.group(1))}月"


def scale_for(name):
    if any(k in name for k in ("商店街", "駅前", "代々木公園", "水元公園")):
        return "大"
    if any(k in name for k in ("小学校", "中学校", "団地", "公園", "広場")):
        return "中"
    return "小"


def access_for(address, name):
    if "駅前" in name or "ロータリー" in name:
        return "最寄駅前"
    if not address:
        return ""
    ward = address.split("区", 1)[0] + "区" if "区" in address else ""
    return f"{ward}内。詳細アクセスは出典URLを参照"


def find_row(rows, candidate):
    target = VENUE_ALIASES.get(candidate["venue"], candidate["venue"])
    target_norm = normalize(target)
    best = None
    for row in rows:
        if row.get("region_hint") != candidate.get("region_hint"):
            continue
        row_norm = normalize(row.get("venue"))
        desc_norm = normalize(row.get("description"))
        if (
            target_norm == row_norm
            or target_norm in row_norm
            or row_norm in target_norm
            or target_norm in desc_norm
        ):
            best = row
            break
    return best


def main():
    triage = load_json(TRIAGE_FILE)["items"]
    rows = [r for r in load_json(ROWS_FILE) if r.get("venue") not in ("詳細", "会場")]
    out = []
    missing = []
    seen = set()
    for candidate in triage:
        if candidate.get("priority") != "high" or candidate.get("status") != "research":
            continue
        row = find_row(rows, candidate)
        if not row:
            missing.append(candidate)
            continue
        venue = row["venue"]
        key = normalize(venue)
        if key in seen:
            continue
        seen.add(key)
        month = month_from_date_text(row.get("date_text"))
        detail_url = row.get("detail_url") or row.get("source_url") or candidate.get("source_url")
        out.append(
            {
                "venue_name": venue,
                "region": row.get("region_hint") or candidate.get("region_hint"),
                "address": row.get("address") or "",
                "access": access_for(row.get("address"), venue),
                "source_url": detail_url,
                "memo": (
                    f"{row.get('description') or venue} "
                    f"出典: 東京盆踊りマップ {row.get('source_url')}"
                ),
                "scale": scale_for(venue),
                "in_tsukiji": False,
                "event": {
                    "name": row.get("description", "").split("\n", 1)[0][:80] or f"{venue} 盆踊り",
                    "month": month,
                    "date_text": row.get("date_text"),
                    "source_url": detail_url,
                },
            }
        )
    OUT_FILE.write_text(
        json.dumps({"items": out, "missing": missing}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"matched: {len(out)} / missing: {len(missing)} -> {OUT_FILE}")
    if missing:
        for item in missing:
            print(f"missing: {item['region_hint']} {item['venue']}")


if __name__ == "__main__":
    main()
