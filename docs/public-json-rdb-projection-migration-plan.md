# Public JSON RDB Projection Migration Plan

作成日: 2026-07-16 JST
署名: おと（Codex）

## Purpose

C本丸では、公開JSONだけに後付けしている以下の表示フィールドを、RDB由来の公開投影へ寄せる。

- reviewed date predictions
- historical reference / historical slide fields
- season hints

ただし公開表示の巻き戻りを避けるため、切替条件は「同一master DB入力で、現行exportと新経路の公開JSONが意味内容で差分ゼロ」。

## Diff-Zero Gate

まず現行の安全網として、次を通す。

```sh
python3 scripts/compare_public_export_postprocessors.py --today 2026-07-16
```

この比較は一時ディレクトリだけに出力し、`data/public/events_public.json` は更新しない。
一時worktreeなど `data/bon_odori_master.sqlite` がない場所では、ローカルのmaster DBを明示できる。

```sh
python3 scripts/compare_public_export_postprocessors.py \
  --today 2026-07-16 \
  --master-db /Users/ryotauchida/bon-odori-collector/data/bon_odori_master.sqlite
```

比較対象:

1. 現行経路: `export_public_events.py`
2. 旧重ねがけ相当: `export_public_events.py` の後に
   `apply_public_date_predictions.py`、`apply_public_historical_references.py`、
   `apply_public_season_hints.py` を再適用

期待値:

- `status == pass`
- `deep_equal == true`
- `event_count_current == event_count_legacy_overlay`
- `current_sha256 == legacy_overlay_sha256`

## Internal ID Sidecar

`export_public_events.py` writes `data/public_event_source_map.json` for internal collector use.
It is intentionally outside `data/public/`, so it is not part of the web-delivered public data.

The sidecar maps the final public event identity (`name`, `venue`, `date`, `date_end`) to Master RDB identifiers:

- `occurrence_id`
- `series_id`
- `venue_id`
- `event_year`

`compare_public_projection_sources.py` and `build_public_historical_reference_change_requests.py` use this sidecar first.
If the sidecar is missing, they fall back to the older `name + venue` matching. This keeps the migration tooling usable on older snapshots while reducing fuzzy-match false negatives on current exports.

## Migration Steps

1. 差分ゼロゲートを毎回通す。
2. `apply_public_date_predictions.py` の入力である `data/event_date_predictions.json` と同等の公開フィールドを、RDB投影側の関数に移す。
3. `apply_public_historical_references.py` の historical reference / slide 計算を、RDB投影側の関数に移す。
4. `apply_public_season_hints.py` の season hint 計算を、RDB投影側の関数に移す。
5. 各段階で、現行経路と新経路のJSONを同一master DBで比較し、差分ゼロを確認する。
6. 差分ゼロが維持できた段階で、旧3本は単体テストとロールバック保険として残すか、legacyへ移すかを別判断する。

## Readiness Dry-Run

Before applying historical-reference backfill candidates to the real Master RDB,
run the integrated dry-run harness:

```sh
python3 scripts/run_public_projection_readiness.py --today 2026-07-16
```

For a clean worktree without `data/bon_odori_master.sqlite`, pass the local DB explicitly:

```sh
python3 scripts/run_public_projection_readiness.py \
  --today 2026-07-16 \
  --master-db /Users/ryotauchida/bon-odori-collector/data/bon_odori_master.sqlite
```

The harness writes fresh public JSON, `public_event_source_map.json`, before/after
projection compare reports, generated `dry_run_only` historical-reference change
requests, and the dry-run apply report under `data/public_projection_readiness/`
by default. It does not deploy, does not edit `data/public/`, and does not apply
to the real Master RDB.

## Non-Goals

- site repo同期やWebデプロイはこの計画に含めない。
- `guard_public_events_sync.py` の判定を緩めない。
- YouTube過去実績だけで今年の開催確定へ昇格しない原則は変えない。

## Notes

- `BON_ODORI_PUBLIC_TODAY=YYYY-MM-DD` 相当の日付固定は比較ツールの `--today` で固定する。
- `apply_public_season_hints.py` の `target_year=2026` ハードコードは、C本丸またはDで外部化する候補。
