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

R2実装と2026-09-09固定入力の比較結果は
[検証記録](r2-public-projection-verification-20260909.md)を参照する。
8ケースの4出力は一致したが、対象年2027への切替は旧版・新版とも既存曲目監査で
拒否されるため、全体の差分ゼロゲートはblockedである。

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

## R2開始前の入力取得と曲目修正（2026-09-09）

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

PR #263の開催回限定撤回23件は、[本番適用run 34326696223](https://github.com/uryoutamomo/bon-odori-collector/actions/runs/34326696223)
でdry-run、監査、CAS publish、再取得検証まで完了した。
[修正後の取得run 34326836379](https://github.com/uryoutamomo/bon-odori-collector/actions/runs/34326836379)
はcommit `c0718033ad7bd736bda561a102247ea54e523fb2`、判定日2026-09-09、対象年2026の
DB・manifest・固定7補助入力を取得した。DB SHA-256は
`14d0b6f08cb46cdbd9ba4c8086d9f51d1a1cb94d173c95f81aadd29ded5faf0e`。
受信artifactのdigest、復号後の各hash、SQLite integrity/FK、23件の撤回状態を検証済み。
同じ入力の4出力は事前検証とbyte一致し、387イベントを維持したまま11イベントの22項目だけを除く。

既存apply workflowのhistorical promotion後処理は、候補19行の時刻と予測17行の
`source_payload_json`・時刻も再生成する。予測の日付・確度・公開投影は不変だが、
payloadの `actual_observations` / `candidate_rules` / `evidence_count` が落ちる既存の
provenance上の制限がある。曲目以外のDB全列が不変だったとは扱わない。
元の観測・根拠テーブルと修正前bundleは保持し、R2では修正後bundleを固定基準にする。
この完了はR2本体の整理前後比較・期限境界検証の合格を意味しない。

R2本体は入力読込の `load_public_projection_inputs()`、意味計算の
`project_public_events()`、出力書込の `write_public_projection()` に分離する。
本番export、review inboxの公開digest、状態軸移行の呼出元を同じ明示入力へ移す。
表示規則は `public_export_support/` へ移し、旧3 CLIは `legacy/public_projection/` に
比較用としてのみ隔離する。同期ガードは入力の過去実績・季節ヒントを補正しない。
同じ入力で通常日、終了前日・当日・翌日、過去実績期限切れ、年越しを比較する。
既存の重ね掛け検査は、整理前後のコードを固定した比較の代わりにはしない。
baselineはbundle metadataのcollector commitと完全一致させる。
独立したコード修正を前提にする再比較では、`--shared-code-fix <40桁commit>` で
単親・Pythonファイルのみのcommitを両隔離snapshotへ同一適用する。仕様変更は同じPRの別commitに置く。
適用不能・既適用は拒否し、commit/parent/patch SHA・両source適用前後hashを記録する。
この `shared_code_fix_parity` は修正後の整理前後比較であり、修正なしの `original_parity`
を合格へ読み替える証拠ではない。元bundleと元比較結果は変更しない。

比較の実行例（入力は復号・検証済みbundle directoryを指定）:

```sh
python3 scripts/compare_public_projection_revisions.py \
  --input-bundle /path/to/verified \
  --baseline-revision c0718033ad7bd736bda561a102247ea54e523fb2 \
  --today 2026-09-09 --target-year 2026 \
  --out-json /path/to/private-evidence/r2-comparison.json --quiet
```

日付境界の既存契約では、当年開催の終了判定は終了日の翌日、過去実績スライドの
期限切れは予測開始日の翌日である。後者は複数日開催でも開始日基準であり、
R2で終了日基準へ意味変更しない。また保存済みの正規状態軸を優先する経路は維持する。
固定DBに別の判定日を渡した比較は、日次の状態軸更新そのものの検証とは区別する。

曲名への進行ラベル混入は別のデータ修正として扱う。元DBの曲行・evidence・同名の
全影響範囲を確認する。曲名単位の `retract_song_identity` は別開催回の同名実曲も
撤回するため、出典文脈に依存する修正には使わない。開催回の曲行と全出典・観測の
レビュー時点を固定する `retract_occurrence_song` のreviewed change requestと
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
2. 日付予測の計算を `public_export_support/date_predictions.py` へ移す。RDB優先・JSON fallback禁止は維持する。
3. historical reference / slide 計算を `public_export_support/historical_references.py` へ移す。
4. season hint 計算を `public_export_support/season_hints.py` へ移す。
5. 各段階で、現行経路と新経路のJSONを同一master DBで比較し、差分ゼロを確認する。
6. 差分ゼロを確認し、旧3本はlegacyの比較fixtureとして隔離する。現役の呼出元からは使わない。

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
- 表示計算の `target_year` は呼出元から明示する。
