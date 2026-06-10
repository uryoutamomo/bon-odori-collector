import json
import re
from pathlib import Path


CANDIDATES_FILE = Path("data/venues_seed_blog.json")
VENUE_MASTER_FILE = Path("data/venue_master.json")
OUT_FILE = Path("data/venue_candidate_triage.json")
SOURCE_URLS_FILE = Path("data/blog_source_urls.json")


KNOWN_ALIASES = {
    "京橋エドグラン1階中央通り側広場": "京橋エドグラン 京橋中央ひろば",
    "上野公園": "上野恩賜公園",
    "噴水広場": "上野恩賜公園",
    "大噴水広場": "上野恩賜公園",
    "さかもと朝顔広場": "さかもと朝顔広場（旧坂本小学校跡地）",
    "旧坂本小学校": "さかもと朝顔広場（旧坂本小学校跡地）",
    "御徒町南口駅前広場": "おかちまちパンダ広場（御徒町駅南口駅前広場）",
    "祭典in上野公園": "上野恩賜公園",
    "東京本願寺": "東本願寺",
    "東本願寺": "東本願寺（浅草）",
    "しながわ中央公園": "しながわ中央公園",
    "ひらさん広場": "平塚中央公園",
    "大井駅前中央通り商店街": "大井銀座商店街",
    "大井駅前": "大井銀座商店街",
    "JR目黒駅西口前": "JR目黒駅西口前",
    "中目黒GT": "中目黒GT",
    "目黒銀座商店街": "目黒銀座商店街",
    "隅田公園": "隅田公園",
    "すみだ公園": "すみだ公園（隅田公園・墨田区側）",
    "アーク・カラヤン広場": "アーク・カラヤン広場（アークヒルズ）",
    "ハマサイト前広場": "ハマサイト前広場・汐留ビルディング外構",
    "サカス広場": "赤坂サカス広場",
    "増上寺": "増上寺（大殿前広場）",
    "報恩寺": "報恩寺境内",
    "祐天寺": "祐天寺境内",
    "麻布上笄町会・麻布氷川神社": "麻布氷川神社",
    "天祖神社": "六本木天祖神社",
    "江東亀戸天祖神社": "江東天祖神社（亀戸天祖神社）",
    "権現神社": "大井蔵王権現神社",
    "大井駅前中央通り商店街": "大井銀座商店街",
}

NOISE_NAMES = {
    "空の広場",
    "内ヘリポート広場",
    "前広場",
    "多目的広場",
    "通り商店街",
    "んき通り商店街",
    "・8月商店街",
    "お祭り広場",
    "水の広場",
    "イベント広場",
    "区民まつり芸能部会ステージ前広場",
    "南口広場",
    "商店街",
    "三角広場",
}

HIGH_PRIORITY_WARDS = {"世田谷区", "大田区", "中野区", "豊島区", "江戸川区", "葛飾区"}


def normalize(value):
    value = value or ""
    value = re.sub(r"[（）()・\s　]", "", value)
    value = value.replace("ヶ", "ケ").replace("ヵ", "カ")
    value = value.replace("旧", "")
    value = value.replace("跡地", "")
    value = value.replace("会場", "")
    value = value.replace("広場", "")
    value = value.replace("公園", "公園")
    return value


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    candidates = load_json(CANDIDATES_FILE)
    master = load_json(VENUE_MASTER_FILE)
    source_urls = load_json(SOURCE_URLS_FILE) if SOURCE_URLS_FILE.exists() else {}
    existing_by_norm = {normalize(row["venue"]): row for row in master}
    existing_names = {row["venue"] for row in master}

    rows = []
    counts = {}
    for item in candidates:
        name = item["venue"]
        reason = ""
        status = "research"
        mapped = None
        if name in NOISE_NAMES:
            status = "noise"
            reason = "generic_or_fragment"
        elif name in existing_names:
            status = "registered"
            mapped = name
            reason = "exact_match"
        elif name in KNOWN_ALIASES:
            status = "registered_alias"
            alias = KNOWN_ALIASES[name]
            mapped = alias if alias in existing_names else None
            if mapped is None:
                alias_norm = normalize(alias)
                for row in master:
                    if alias_norm and alias_norm in normalize(row["venue"]):
                        mapped = row["venue"]
                        break
            mapped = mapped or alias
            reason = "known_alias"
        elif normalize(name) in existing_by_norm:
            status = "registered_alias"
            mapped = existing_by_norm[normalize(name)]["venue"]
            reason = "normalized_match"
        region = item.get("region_hint")
        priority = "skip"
        if status == "research":
            priority = "high" if region in HIGH_PRIORITY_WARDS else "normal"
        source_title = item.get("source_title")
        rows.append(
            {
                "venue": name,
                "region_hint": region,
                "status": status,
                "mapped_to": mapped,
                "reason": reason,
                "priority": priority,
                "source_title": source_title,
                "source_url": source_urls.get(source_title),
                "in_tsukiji_30min_guess": item.get("in_tsukiji_30min_guess"),
            }
        )
        counts[status] = counts.get(status, 0) + 1

    priority_order = {"high": 0, "normal": 1, "skip": 2}
    rows.sort(key=lambda r: (priority_order.get(r["priority"], 9), r["status"], r["region_hint"] or "", r["venue"]))
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump({"counts": counts, "items": rows}, f, ensure_ascii=False, indent=2)
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print(f"wrote {OUT_FILE}")


if __name__ == "__main__":
    main()
