"""Reclassify X member account type and operational tags.

Inputs:
- Notion X member list: display name, bio, existing status.
- data/x_account_scores.json: tweet-derived role tags, rank, confidence.
- data/voices.json: recent tweet text for weak profile cases.

Outputs:
- data/x_member_classification_proposal.json
- optionally updates Notion with --apply
"""

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


OUTPUT_FILE = Path("data/x_member_classification_proposal.json")
VOICES_FILE = Path("data/voices.json")

ACCOUNT_TYPES = (
    "盆踊りダンサー",
    "情報発信者",
    "盆踊り主催者",
    "盆踊り関連メディア",
    "地域コミュニティ",
    "その他",
)
OPERATION_TAGS = ("VIP", "定期巡回", "要確認")

MEDIA_RE = re.compile(r"(新聞|ニュース|メディア|ラジオ|テレビ|TV|編集|記者|ライター|ブログ|YouTube|配信|番組|取材)")
ORGANIZER_RE = re.compile(r"(公式|主催|運営|実行委員|町会|自治会|青年部|商店街|商店会|保存会|神社|寺|寺院|本願寺|祭礼|例大祭)")
COMMUNITY_RE = re.compile(r"(区議|市議|都議|県議|議員|自治体|観光協会|地域|まちづくり|町おこし|町興し|コミュニティ|商工会)")
DANCER_RE = re.compile(r"(盆踊|盆おどり|盆オドリ|盆踊ラー|踊り|踊る|民謡|音頭|太鼓|浴衣|郡上|阿波おどり|阿波踊り)")
INFO_RE = re.compile(r"(イベント|祭り|まつり|開催|告知|予定|日程|会場|地域情報|お知らせ|カレンダー)")


def load_env():
    try:
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass


load_env()
import collect  # noqa: E402


def prop_multi(prop):
    return [x.get("name", "") for x in (prop or {}).get("multi_select", []) if x.get("name")]


def fetch_member_rows():
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = collect._notion_query_database(collect.X_MEMBER_LIST_DB_ID, payload)
        for page in data.get("results", []):
            props = page.get("properties", {})
            handle = collect._x_member_handle_from_props(props)
            if not handle:
                continue
            rows.append({
                "page_id": page.get("id", ""),
                "handle": handle,
                "display_name": collect._prop_plain(props.get("表示名", {})),
                "bio": collect._prop_plain(props.get("自己紹介", {})),
                "manual_status": collect._prop_select(props.get("収集ステータス", {})),
                "current_account_type": collect._prop_select(props.get("アカウント種別", {})),
                "current_operation_tags": prop_multi(props.get("運用タグ", {})),
                "current_specialty_types": prop_multi(props.get("得意タイプ", {})),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_voice_texts():
    by_handle = defaultdict(list)
    for voice in load_json(VOICES_FILE, []):
        handle = collect._norm_handle(voice.get("account"))
        if not handle:
            continue
        text = " ".join((voice.get("text") or "").split())
        if text:
            by_handle[handle].append(text[:240])
    return by_handle


def account_type(row, score_row, texts):
    profile = " ".join([
        row.get("display_name", ""),
        row.get("bio", ""),
    ])
    tweet_blob = " ".join(texts[:8])
    reasons = score_row.get("top_reasons", {})
    role_tags = set(score_row.get("role_tags", []))

    if MEDIA_RE.search(profile):
        return "盆踊り関連メディア", "profile_media"
    if ORGANIZER_RE.search(profile):
        return "盆踊り主催者", "profile_organizer"
    if COMMUNITY_RE.search(profile):
        return "地域コミュニティ", "profile_community"
    if DANCER_RE.search(profile):
        return "盆踊りダンサー", "profile_dancer"
    if "参加レポ型" in role_tags and DANCER_RE.search(tweet_blob):
        return "盆踊りダンサー", "tweet_experience"
    if "地域/会場型" in role_tags and reasons.get("venue", 0) >= 2:
        return "地域コミュニティ", "tweet_venue"
    if "発見型" in role_tags or "裏取り型" in role_tags or INFO_RE.search(profile):
        return "情報発信者", "tweet_info"
    if score_row.get("valuable_posts", 0) > 0:
        return "情報発信者", "valuable_posts"
    return "その他", "weak_signal"


def specialty_types(score_row):
    tags = [tag for tag in score_row.get("role_tags", []) if tag]
    return tags or ["文脈確認型"]


def operation_tags(row, score_row, acct_type):
    rank = score_row.get("usefulness_rank", "Probation")
    usefulness = score_row.get("usefulness_score", 0)
    confidence = score_row.get("confidence", "low")
    valuable = score_row.get("valuable_posts", 0)
    posts = score_row.get("posts_seen", 0)
    tags = []

    if rank == "S" or usefulness >= 88 or (row.get("manual_status") == "優先" and rank in ("S", "A", "B")):
        tags.append("VIP")
    if rank in ("S", "A", "B") or usefulness >= 55 or valuable >= 2 or acct_type in ("盆踊り主催者", "盆踊り関連メディア"):
        tags.append("定期巡回")
    if rank in ("Candidate", "Probation") or confidence == "low" or posts < 3 or usefulness < 55:
        tags.append("要確認")

    if not tags:
        tags.append("要確認")
    return [tag for tag in OPERATION_TAGS if tag in tags]


def build_proposal(rows, scores, voices_by_handle):
    proposals = []
    for row in rows:
        key = collect._norm_handle(row.get("handle"))
        score_row = scores.get(key, {})
        texts = voices_by_handle.get(key, [])
        acct_type, reason = account_type(row, score_row, texts)
        op_tags = operation_tags(row, score_row, acct_type)
        spec_tags = specialty_types(score_row)
        proposals.append({
            "page_id": row["page_id"],
            "handle": f"@{key}",
            "display_name": row.get("display_name", ""),
            "account_type": acct_type,
            "operation_tags": op_tags,
            "specialty_types": spec_tags,
            "reason": reason,
            "rank": score_row.get("usefulness_rank", ""),
            "usefulness_score": score_row.get("usefulness_score", 0),
            "confidence": score_row.get("confidence", ""),
            "valuable_posts": score_row.get("valuable_posts", 0),
            "current": {
                "account_type": row.get("current_account_type"),
                "operation_tags": row.get("current_operation_tags", []),
                "specialty_types": row.get("current_specialty_types", []),
            },
        })
    return proposals


def write_proposal(proposals):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": proposals,
        "summary": {
            "account_type": dict(Counter(row["account_type"] for row in proposals)),
            "operation_tags": dict(Counter(tag for row in proposals for tag in row["operation_tags"])),
            "specialty_types": dict(Counter(tag for row in proposals for tag in row["specialty_types"])),
        },
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def apply_to_notion(proposals):
    updated = 0
    for row in proposals:
        props = {
            "アカウント種別": {"select": {"name": row["account_type"]}},
            "運用タグ": {"multi_select": [{"name": tag} for tag in row["operation_tags"]]},
            "得意タイプ": {"multi_select": [{"name": tag} for tag in row["specialty_types"]]},
        }
        collect._update_page_props_best_effort(row["page_id"], props)
        updated += 1
    return updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_env()
    rows = fetch_member_rows()
    scores = load_json(Path(collect.X_ACCOUNT_SCORES_FILE), {}).get("accounts", {})
    proposals = build_proposal(rows, scores, build_voice_texts())
    payload = write_proposal(proposals)
    print(f"[classify] proposal: {len(proposals)} accounts -> {OUTPUT_FILE}")
    print(f"[classify] account_type: {payload['summary']['account_type']}")
    print(f"[classify] operation_tags: {payload['summary']['operation_tags']}")
    print(f"[classify] specialty_types: {payload['summary']['specialty_types']}")
    if args.apply:
        updated = apply_to_notion(proposals)
        print(f"[classify] Notion updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
