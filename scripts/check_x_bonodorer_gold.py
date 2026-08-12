#!/usr/bin/env python3
"""Check the small human-labelled X account set against S1b scores."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect


def rank(accounts, field):
    return {handle: index + 1 for index, (handle, _row) in enumerate(sorted(
        accounts.items(),
        key=lambda item: (-item[1].get(field, 0), item[0])
    ))}


def check(voices, gold, cfg=None):
    accounts = collect._build_x_account_scores(voices, cfg or {}).get("accounts", {})
    announce, record = rank(accounts, "announce_score"), rank(accounts, "record_score")
    positive_limit = gold["check"]["positive_must_rank_within"]
    negative_limit = gold["check"]["negative_must_not_rank_within"]
    result = {"positive": {}, "negative": {}, "passed": True}
    for row in gold["positive"]:
        handle = row["handle"].lstrip("@").lower()
        ranks = {"announce": announce.get(handle), "record": record.get(handle)}
        result["positive"][handle] = ranks
        result["passed"] &= any(value is not None and value <= positive_limit for value in ranks.values())
    for row in gold["negative"]:
        handle = row["handle"].lstrip("@").lower()
        ranks = {"announce": announce.get(handle), "record": record.get(handle)}
        result["negative"][handle] = ranks
        result["passed"] &= all(value is None or value > negative_limit for value in ranks.values())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, default=ROOT / "data/voices.json")
    parser.add_argument("--gold", type=Path, default=ROOT / "data/x_bonodorer_gold.json")
    args = parser.parse_args()
    result = check(json.loads(args.voices.read_text(encoding="utf-8")), json.loads(args.gold.read_text(encoding="utf-8")), collect._load_x_config() or {})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
