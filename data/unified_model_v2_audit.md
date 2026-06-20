# 統一モデルv2 監査レポート

生成: 2026-06-19T11:48:18.484597+00:00

## 概要

- observations: 48 rows / 28 series / issues=30
- RDB: data/bon_odori.sqlite / issues=2

## 観測JSONの論点

- medium / observation_id_mismatch: a7c94f5754b5fbd3 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: ac5d792eca0e5754 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: e58714c9d972f33f - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: d86346e5c130b51a - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: c7d8559b7af0eb8a - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 42d6c748cdb4477e - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 5e38ae740179c50f - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: bf1e399806cc72ad - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 903be26b351a9911 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 05279db2439d1689 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: ebfad4c75b399d5a - Observation id is not derived from series_key, year, and observed_dates.
- review / event_name_year_mismatch: 郡上おどり in 青山 2025 - Event name contains a year that differs from the observed occurrence year.
- medium / observation_id_mismatch: a63083159e4ff236 - Observation id is not derived from series_key, year, and observed_dates.
- review / event_name_year_mismatch: 郡上おどり in 青山 2026 - Event name contains a year that differs from the observed occurrence year.
- medium / observation_id_mismatch: 0b16b4543c1d85be - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 093f293c00e81050 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 60c7771d12b422d8 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: d769da7140780732 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 452c6a793fb3b445 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: b50c8b0ee4e7422c - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 3825abd528e2edc7 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: ca7e2062e653d832 - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: e50f081d8be1b6fb - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: e1558ac87a836c1c - Observation id is not derived from series_key, year, and observed_dates.
- medium / observation_id_mismatch: 37bfe429d1174d03 - Observation id is not derived from series_key, year, and observed_dates.

## RDBの論点

- high / event_venues_missing_event: RDB integrity check failed: event_venues_missing_event. {'count': 36}
- high / song_evidence_missing_evidence: RDB integrity check failed: song_evidence_missing_evidence. {'count': 3117}

## レビューキュー上位

- song_not_in_master: 26941
- ignore: 1020
- matched_existing_event: 559
- review_video_evidence: 348
- out_of_scope: 240
- already_reflected: 207
- needs_official_confirmation: 155
- promote: 15
- watch: 13
- reject: 2

## 次アクション案

- event_name_year_mismatch は名称正規化か開催年解釈のどちらかを手動レビューする。
- RDBの外部キー相当チェックが0なら、次は event_series / event_occurrences のJSON契約案へ進める。
- review_queue は件数が大きいため、status別に人間レビュー対象と自動保留を分離する。
