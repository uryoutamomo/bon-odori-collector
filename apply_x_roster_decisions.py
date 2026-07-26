#!/usr/bin/env python3
"""Apply review-console decisions about X accounts to the local collection roster.

Flow: レビューコンソールで「優先 / 通常 / 休止」を選ぶ
  -> python3 review_console_ops/apply_review_console_decisions.py --write
  -> このスクリプトで data/x_collection_roster.json の manual_status を更新
  -> 次回の collect.py から反映される

Notion「Xメンバーリスト」へは書き込まない。Notionへの追加・同期は内田さんが
承認した候補だけに限る運用（CLAUDE.md）のため、ここでは触らない。
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

DATA = Path("data")
STAGED = DATA / "review_console" / "staged" / "x_account_roster_decisions.json"
ROSTER = DATA / "x_collection_roster.json"

VALID_STATUSES = {"優先", "通常", "休止"}


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def norm_handle(value):
    return str(value or "").strip().lstrip("@").lower()


def collect_changes(rows, roster):
    """Return (changes, issues) without touching anything."""
    by_handle = {
        norm_handle(row.get("handle")): row for row in roster.get("accounts") or []
    }
    changes, issues = [], []
    for row in rows:
        handle = norm_handle(row.get("item_key") or row.get("handle"))
        status = (row.get("apply_value") or row.get("decision") or "").strip()
        if not handle:
            issues.append({"row": row.get("item_id", ""), "reason": "ハンドルが読めない"})
            continue
        if status not in VALID_STATUSES:
            issues.append({
                "handle": f"@{handle}",
                "reason": f"未知の収集ステータス: {status!r}（許可: {'/'.join(sorted(VALID_STATUSES))}）",
            })
            continue
        current = by_handle.get(handle)
        before = (current or {}).get("manual_status") or ""
        if current is None:
            changes.append({
                "handle": f"@{handle}",
                "before": "(名簿に無し)",
                "after": status,
                "action": "add",
                "note": row.get("note", ""),
            })
        elif before != status:
            changes.append({
                "handle": f"@{handle}",
                "before": before or "(未設定)",
                "after": status,
                "action": "update",
                "note": row.get("note", ""),
            })
    return changes, issues


def apply_changes(roster, changes):
    by_handle = {
        norm_handle(row.get("handle")): row for row in roster.get("accounts") or []
    }
    for change in changes:
        handle = norm_handle(change["handle"])
        if change["action"] == "add":
            roster.setdefault("accounts", []).append({
                "handle": change["handle"],
                "manual_status": change["after"],
                "origin": "review_console",
            })
        else:
            by_handle[handle]["manual_status"] = change["after"]
    roster["accounts"] = sorted(
        roster.get("accounts") or [], key=lambda row: str(row.get("handle", "")).lower()
    )
    roster["count"] = len(roster["accounts"])
    roster["updated_at"] = datetime.now(timezone.utc).isoformat()
    return roster


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", default=str(STAGED))
    parser.add_argument("--roster", default=str(ROSTER))
    parser.add_argument("--apply", action="store_true", help="実際に名簿を書き換える")
    args = parser.parse_args()

    staged = load_json(args.staged)
    if staged is None:
        raise SystemExit(
            f"{args.staged} がありません。先に "
            "python3 review_console_ops/apply_review_console_decisions.py --write を実行してください。"
        )
    roster = load_json(args.roster, {"accounts": []})
    changes, issues = collect_changes(staged.get("rows") or [], roster)

    print(f"X情報源の収集ステータス反映（{'apply' if args.apply else 'dry-run'}）")
    print(f"- 決定 {len(staged.get('rows') or [])}件 / 変更 {len(changes)}件 / 問題 {len(issues)}件")
    for change in changes:
        note = f"  memo: {change['note']}" if change.get("note") else ""
        print(f"  {change['handle']}: {change['before']} -> {change['after']}{note}")
    for issue in issues:
        print(f"  [!] {issue.get('handle', issue.get('row'))}: {issue['reason']}")

    if not args.apply:
        print("- dry-run のため書き込みませんでした。反映するには --apply を付けてください。")
        return
    if not changes:
        print("- 変更がないため書き込みません。")
        return

    apply_changes(roster, changes)
    Path(args.roster).write_text(
        json.dumps(roster, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"- 反映しました: {args.roster}")


if __name__ == "__main__":
    main()
