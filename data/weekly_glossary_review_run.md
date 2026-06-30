# 日次X収穫レビュー生成（手動fallback）

- generated_at: 2026-06-19T11:42:58.319957+00:00
- status: ok
- days: 7

## outputs

- `data/weekly_harvest_candidates.json`
- `data/weekly_song_triage_result.json`
- `data/weekly_song_candidates_review.json`
- `data/weekly_harvest_review_candidates.json`
- `data/weekly_harvest_summary.json`
- `data/weekly_harvest_summary.md`
- `data/weekly_harvest_review_ui.html`
- `data/weekly_song_candidates_review_ui.html`

## commands

- `python3 build_weekly_harvest_candidates.py --days 7` -> ok

```text
日次X収穫候補生成: voices 841 / candidates 85 -> data/weekly_harvest_candidates.json
```

- `python3 triage_weekly_song_candidates.py --dry-run` -> ok

```text
done: songs=67 direct=55 created=38 updated=17 noise=10 review=2 dry_run=True
wrote data/weekly_song_triage_result.json
wrote data/weekly_song_candidates_review.json
```

- `python3 prepare_weekly_harvest_review.py` -> ok

```text
daily X harvest summary: candidates=85 non_song_review=18 song_review=2 song_direct_dry_run=55
wrote data/weekly_harvest_review_candidates.json
wrote data/weekly_harvest_summary.json
wrote data/weekly_harvest_summary.md
```

- `python3 build_keyboard_review_ui.py --input data/weekly_harvest_review_candidates.json --rows-key rows --out data/weekly_harvest_review_ui.html --title 日次X収穫レビュー（用語・共起） --summary-fields interpretation,type,confidence,evidence_count --detail-fields reason,evidence_text,evidence_url --source-field evidence --key-fields term,category,type,evidence_url --download-name weekly_harvest_review_decisions.json --storage-key weekly-harvest-review-v1` -> ok

```text
wrote data/weekly_harvest_review_ui.html (18 rows)
```

- `python3 build_keyboard_review_ui.py --input data/weekly_song_candidates_review.json --rows-key rows --out data/weekly_song_candidates_review_ui.html --title 日次X収穫レビュー（曲候補） --summary-fields canonical_song_name,triage_reason,evidence_count --detail-fields reason,evidence_text,evidence_url --source-field evidence --key-fields term,category,type,evidence_url --decisions-labels 採用,不採用,曲マスタ外,保留 --download-name weekly_song_review_decisions.json --storage-key weekly-song-review-v1` -> ok

```text
wrote data/weekly_song_candidates_review_ui.html (2 rows)
```
