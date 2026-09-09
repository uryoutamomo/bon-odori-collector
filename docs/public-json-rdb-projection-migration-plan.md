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

この比較は一時ディレクトリだけに公開成果物を出力し、`data/public/events_public.json` は更新しない。
DBには `database_checksum` が一致するmanifestが必須。正規fetchした組を明示する。

```sh
python3 scripts/compare_public_export_postprocessors.py \
  --today 2026-07-16 \
  --master-db /path/to/fetched/bon_odori_master.sqlite \
  --master-manifest /path/to/fetched/bon_odori_master_manifest.json
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

events JSONだけでなく、`events_public.js`、`event_songs_public.json`、内部用
`public_event_source_map.json` も比較する。`event_song_occurrences_public.json` は
legacy曲目fallbackの入力であり、このexporterの生成物ではない。各実行に隔離した
入力コピーを渡し、出力先変更による暗黙の空fallbackを許さない。

補助入力は `event_date_predictions.json`、`event_date_update_candidates.json`、
`public_event_overrides.json`、`public_fixed_date_rules.json`、
`song_master_initial_registration.json`、`rdb_song_review_source.json` と上記fallback。
各hash・DB/manifestのhash・判定日・対象年・ソースcommitを比較レポートに残す。
`BON_ODORI_PUBLIC_SOURCE=master_rdb` を強制し、環境のNotion設定で比較元を変えない。

## R2開始前の残件（2026-09-09）

手元の古いDBとmanifestの組はchecksum不一致だった。これを修復して一致と見せたり、
合成DBのテストを本番相当の差分ゼロ判定に代用したりしない。
既存Actions artifactには正本DBが含まれないため、既存のS3 fetch経路で同世代の
DBとmanifestを取得する必要がある。

正規取得は手動専用の `.github/workflows/capture-public-projection-inputs.yml` を使う。
`recipient_certificate`（公開鍵を含むPEM証明書）、`today`、`target_year` を指定する。
取得処理はS3正本を書き換えず、公開repositoryの
artifactには受取人宛に暗号化したbundleだけを渡す。DB、manifest、補助入力、hashは
bundle内部に保持する。秘密鍵は取得側だけで保管し、workflowへ渡さない。
保持期間は3日。復号後は入力hashを照合し、同じcollector commitで比較する。

R2本体では `project_public_events()` の入力読込・意味計算・出力書込を分け、現役の
後処理呼出元を移す。同じ入力で通常日、終了前日・当日・翌日、過去実績期限切れ、
年越しを比較してから、同期ガードが入力を補正して救済する経路と旧CLIを撤去する。
既存の「export後に旧処理を再適用する比較」は重ね掛けの検査であり、整理前後の
コードを固定して比較する検査の代わりにはしない。

曲名への進行ラベル混入は別のデータ修正として扱う。元DBの曲行・evidence・同名の
全影響範囲を確認し、既存 `retract_song_identity` へのreviewed change requestと
dry-runで修正する。修正前後の入力組を別々に保存し、意図した曲目変更をR2の
純粋な構造整理の差分ゼロ条件へ混ぜない。

## Internal ID Sidecar

`export_public_events.py` writes `data/public_event_source_map.json` for internal collector use.
It is intentionally outside `data/public/`, so it is not part of the web-delivered public data.

The sidecar maps the final public event identity (`name`, `venue`, `date`, `date_end`) to Master RDB identifiers:

- `occurrence_id`
- `series_id`
- `venue_id`
- `event_year`

`compare_public_projection_sources.py` and `public_export_support/build_public_historical_reference_change_requests.py` use this sidecar first.
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
