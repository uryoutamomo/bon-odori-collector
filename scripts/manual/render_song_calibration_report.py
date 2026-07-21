#!/usr/bin/env python3
"""Render song prediction calibration JSON into a compact markdown report."""

import argparse
import json
from pathlib import Path


DEFAULT_INPUT = Path("data/song_prediction_calibration.json")
DEFAULT_OUT = Path("data/song_prediction_calibration.md")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render(data):
    lines = [
        "# 曲予測較正レポート",
        "",
        f"- scored_count: {data.get('scored_count')}",
        f"- scored_event_count: {data.get('scored_event_count')}",
        f"- mean_brier: {data.get('mean_brier')}",
        "",
        "## イベント別",
        "",
        "| event | venue | scored | present | mean_probability | mean_soft_label | mean_brier |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in data.get("summary", {}).get("by_event", []):
        lines.append(
            "| {event} | {venue} | {scored} | {present} | {prob} | {label} | {brier} |".format(
                event=(row.get("event_name") or "").replace("|", " "),
                venue=(row.get("venue") or "").replace("|", " "),
                scored=row.get("scored_count"),
                present=row.get("actual_present_count"),
                prob=row.get("mean_probability"),
                label=row.get("mean_soft_label"),
                brier=row.get("mean_brier"),
            )
        )
    lines += [
        "",
        "## 信頼度キー別",
        "",
        "| reliability_key | scored | present | mean_probability | mean_soft_label | mean_brier | suggested_reliability | delta |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in data.get("summary", {}).get("by_reliability_key", []):
        lines.append(
            "| {key} | {scored} | {present} | {prob} | {label} | {brier} | {suggested} | {delta} |".format(
                key=row.get("reliability_key"),
                scored=row.get("scored_count"),
                present=row.get("actual_present_count"),
                prob=row.get("mean_probability"),
                label=row.get("mean_soft_label"),
                brier=row.get("mean_brier"),
                suggested=row.get("suggested_reliability"),
                delta=row.get("suggested_delta"),
            )
        )
    lines += [
        "",
        "## 山王メモ",
        "",
        "- 2026-06-13 現地確認で、落合弘民踊研究会の事前告知19曲が過不足なく全一致。",
        "- 山王19曲は probability=0.80 / soft_label=0.80 / Brier=0.0。",
        "- `semi_official_setlist` は suggested_reliability=0.80 / delta=0.0 で、今回の1件では更新不要。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.write_text(render(load_json(args.input)), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
