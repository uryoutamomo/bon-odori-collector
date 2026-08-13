#!/usr/bin/env python3
"""公式・準公式ソース台帳の確認待ちを見て、人の判断を台帳へ書き戻す。

日次は、行事へ紐付いたけれど確からしさが足りないアカウントを `pending_review`
として置く。その判断は人にしかできないが、判断した結果を残す場所が無いと、
同じアカウントが翌日もまた確認待ちに現れる。ゐの市のときと同じで、人が決めた
ことを機械が毎日巻き戻してしまう。

このコマンドは、その判断を台帳の行そのものへ `decided_by: user` つきで書く。
`tier: rejected` にした行は日次の更新対象から外れ、直読みの対象にもならない。

    python3 review_x_official_sources.py list
    python3 review_x_official_sources.py reject @handle --reason "全国まとめbotで一次情報ではない"
    python3 review_x_official_sources.py accept @handle --reason "会場の写真つきで毎年告知している"
    python3 review_x_official_sources.py reopen @handle

X API は呼ばない。触るのは `data/x_official_source_accounts.json` だけ。
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timezone, datetime
from pathlib import Path

from collection_support.x_official_source_accounts import norm_handle
from collection_support.x_source_registry import REJECTED

REGISTRY = Path("data/x_official_source_accounts.json")


def load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"accounts": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), list):
        raise SystemExit(f"{path} の形式が想定と違います（accounts の配列がありません）")
    return payload


def save(path: Path, payload: dict) -> None:
    payload["accounts"] = sorted(
        payload["accounts"], key=lambda row: norm_handle(row.get("handle"))
    )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def find(payload: dict, handle: str) -> dict:
    key = norm_handle(handle)
    for row in payload["accounts"]:
        if norm_handle(row.get("handle")) == key:
            return row
    raise SystemExit(f"@{key} は台帳にありません。`list` で確認待ちの一覧を見てください")


def describe(row: dict) -> str:
    linked = row.get("linked_events") or []
    events = "、".join(
        f"{event.get('series_name') or event.get('series_id')}"
        f"（{event.get('ward') or '区不明'}・{event.get('confidence') or '確からしさ不明'}）"
        for event in linked
    ) or "紐付いた行事なし"
    since = row.get("pending_since")
    age = ""
    if since:
        try:
            days = (date.today() - date.fromisoformat(since)).days
            age = f" / 確認待ち {days}日目（{since}〜）"
        except ValueError:
            age = f" / 確認待ち {since}〜"
    return f"{row.get('handle')}  {row.get('name') or '(表示名なし)'}{age}\n    {events}"


def cmd_list(args, payload: dict) -> int:
    rows = [
        row for row in payload["accounts"]
        if args.tier == "all" or row.get("tier") == args.tier
    ]
    if not rows:
        print(f"{args.tier} の行はありません")
        return 0
    print(f"{args.tier}: {len(rows)}件")
    for row in sorted(rows, key=lambda r: str(r.get("pending_since") or "")):
        print(describe(row))
        if row.get("decision_reason"):
            print(f"    判断: {row.get('tier')} — {row['decision_reason']}")
    return 0


def _decide(row: dict, tier: str, reason: str) -> None:
    row["tier"] = tier
    row["decided_by"] = "user"
    row["decided_at"] = datetime.now(timezone.utc).date().isoformat()
    if reason:
        row["decision_reason"] = reason
    row.pop("pending_since", None)


def cmd_reject(args, payload: dict) -> int:
    row = find(payload, args.handle)
    _decide(row, REJECTED, args.reason)
    save(args.registry, payload)
    print(f"{row['handle']} を対象外として記録しました。以後この行は再提示されず、直読みにも入りません。")
    return 0


def cmd_accept(args, payload: dict) -> int:
    row = find(payload, args.handle)
    _decide(row, "active", args.reason)
    save(args.registry, payload)
    print(f"{row['handle']} を active にしました。次の日次から直読みの対象に入ります。")
    return 0


def cmd_reopen(args, payload: dict) -> int:
    """判断を取り消し、翌日から機械の判定へ戻す。"""
    row = find(payload, args.handle)
    for field in ("decided_by", "decided_at", "decision_reason"):
        row.pop(field, None)
    row["tier"] = "pending_review"
    save(args.registry, payload)
    print(f"{row['handle']} の判断を取り消しました。次の日次で機械が判定し直します。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="台帳の行を見る（既定は確認待ちだけ）")
    listing.add_argument("--tier", default="pending_review",
                         choices=["pending_review", "unlinked", "dormant", "active", REJECTED, "all"])
    listing.set_defaults(func=cmd_list)

    reject = sub.add_parser("reject", help="このアカウントは公式ソースとして対象外だと記録する")
    reject.add_argument("handle")
    reject.add_argument("--reason", required=True, help="なぜ対象外なのか。あとで読み返すために必須")
    reject.set_defaults(func=cmd_reject)

    accept = sub.add_parser("accept", help="公式ソースとして採用し、毎日読む")
    accept.add_argument("handle")
    accept.add_argument("--reason", default="")
    accept.set_defaults(func=cmd_accept)

    reopen = sub.add_parser("reopen", help="いちど下した判断を取り消して機械の判定へ戻す")
    reopen.add_argument("handle")
    reopen.set_defaults(func=cmd_reopen)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, load(args.registry))


if __name__ == "__main__":
    raise SystemExit(main())
