#!/usr/bin/env python3
"""Record review-console decisions about poster images into the OCR ledger.

Flow: レビューコンソールで読み取り結果（読んだ / イベント情報なし / 読めない）を選ぶ
  -> python3 review_console_ops/apply_review_console_decisions.py --write
  -> このスクリプトで data/poster_ocr_processed.json に記録
  -> 次回の build_event_poster_ocr_queue.py から未読キューに出なくなる

イベント情報そのものの反映は行わない。読み取った内容を master RDB へ入れる経路は
`docs/official-notice-field-report-operations.md`（掲示物レポート）を使う。
"""

import argparse
import json
from pathlib import Path

from collection_support.poster_ocr_ledger import (
    DONE_STATUSES,
    LEDGER_PATH,
    load_ledger,
    record,
    save_ledger,
)

STAGED = Path("data") / "review_console" / "staged" / "event_poster_ocr_decisions.json"


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def collect_changes(rows, ledger):
    processed = ledger.get("processed") or {}
    changes, issues = [], []
    for row in rows:
        queue_id = str(row.get("item_key") or row.get("id") or "").split("|")[0]
        status = (row.get("apply_value") or row.get("decision") or "").strip()
        if not queue_id:
            issues.append({"row": row.get("item_id", ""), "reason": "キューIDが読めない"})
            continue
        if status == "hold":
            continue
        if status not in DONE_STATUSES:
            issues.append({
                "id": queue_id,
                "reason": f"未知の読み取り結果: {status!r}（許可: {', '.join(DONE_STATUSES)}）",
            })
            continue
        before = (processed.get(queue_id) or {}).get("status") or "(未読)"
        if before == status:
            continue
        changes.append({
            "id": queue_id,
            "before": before,
            "after": status,
            "note": row.get("note", ""),
        })
    return changes, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", default=str(STAGED))
    parser.add_argument("--ledger", default=str(LEDGER_PATH))
    parser.add_argument("--apply", action="store_true", help="実際に台帳へ記録する")
    args = parser.parse_args()

    staged = load_json(args.staged)
    if staged is None:
        raise SystemExit(
            f"{args.staged} がありません。先に "
            "python3 review_console_ops/apply_review_console_decisions.py --write を実行してください。"
        )
    ledger = load_ledger(args.ledger)
    changes, issues = collect_changes(staged.get("rows") or [], ledger)

    print(f"ポスター読み取り結果の記録（{'apply' if args.apply else 'dry-run'}）")
    print(f"- 決定 {len(staged.get('rows') or [])}件 / 記録 {len(changes)}件 / 問題 {len(issues)}件")
    for change in changes:
        note = f"  memo: {change['note']}" if change.get("note") else ""
        print(f"  {change['id']}: {change['before']} -> {change['after']}{note}")
    for issue in issues:
        print(f"  [!] {issue.get('id', issue.get('row'))}: {issue['reason']}")

    if not args.apply:
        print("- dry-run のため書き込みませんでした。反映するには --apply を付けてください。")
        return
    if not changes:
        print("- 変更がないため書き込みません。")
        return

    for change in changes:
        record(
            change["id"],
            change["after"],
            note=change.get("note", ""),
            ledger=ledger,
            save=False,
        )
    save_ledger(ledger, args.ledger)
    print(f"- 記録しました: {args.ledger}")


if __name__ == "__main__":
    main()
