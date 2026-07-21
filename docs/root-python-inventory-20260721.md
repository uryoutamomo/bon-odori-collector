# Root Python inventory

基準日: 2026-07-21 JST

この台帳は参照シグナルの棚卸しであり、`review_candidate` を自動削除・自動移動しない。
移動前に用途・生成物・git履歴を個別確認する。

## Summary

| metric | count |
| --- | ---: |
| root `*.py` | 231 |
| `legacy/**/*.py` | 147 |
| `documented_manual` | 10 |
| `retained_legacy_dependency` | 6 |
| `review_candidate` | 20 |
| `source_dependency` | 87 |
| `test_supported_manual` | 66 |
| `workflow_entrypoint` | 42 |

## Review candidates

workflow・現役Python・tests・docsから参照されない候補。名前だけで退役判断しない。

- `advance_event_evidence_window.py`
- `audit_hidden_historical_public_candidates.py`
- `audit_youtube_song_clip_fragments.py`
- `extract_blog_venue_rows.py`
- `extract_venues_blog.py`
- `fill_glossary_readings.py`
- `find_notion_pages.py`
- `geocode_venues.py`
- `inspect_notion_page.py`
- `map_blog_source_urls.py`
- `rank_x_bonodori_accounts.py`
- `render_song_calibration_report.py`
- `render_youtube_candidate_report.py`
- `review_current_date_batch.py`
- `review_public_event_override_absorption.py`
- `review_source_url_batch.py`
- `review_venue_batch.py`
- `review_x_rank_validation.py`
- `triage_blog_venue_candidates.py`
- `venue_research_batch.py`

## Regenerate

```bash
python3 scripts/build_root_python_inventory.py --as-of 2026-07-21
```

署名: おと（Codex）
