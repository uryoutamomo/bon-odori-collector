# R2 public projection implementation and comparison

2026-09-09 / おと（Codex）

R2の実装は完了した。固定入力による9ケースの検証では8ケース・4出力がbyte一致した。
対象年を2027へ進める1ケースは旧版・新版とも同じ曲目監査で拒否されたため、
全ケースの差分ゼロゲートは **blocked** のままである。merge・本番切替の完了証拠にしない。

## 変更内容

- `load_public_projection_inputs()`、`project_public_events()`、`write_public_projection()`
  に読込・意味計算・書込を分離。計算はDB/ファイル/環境を読まず、入力を変更しない。
- 予測・過去実績・季節の表示規則を `public_export_support/` へ移し、旧3 CLIは
  `legacy/public_projection/` の比較fixtureに限定した。export、review inbox digest、
  状態軸移行の呼出元を明示入力へ更新した。
- 同期ガードからhistorical/season/display-tierの再生成を除いた。
  元のcollector JSONを比較し、欠落した表示を補ってpassにはしない。
- `scripts/compare_public_projection_revisions.py` は保存済みbundleと旧commitを結び、
  新旧のコードを隔離コピーして比較する。各実行の前後で入力hash、DB/manifest、
  SQLite integrity/FK、sidecar不在、Python source不変を確認する。
  同一の安全拒否でも、4出力未生成なら `blocked` として差分ゼロ合格から除く。

## 固定基準

比較基準は[取得run 34326836379](https://github.com/uryoutamomo/bon-odori-collector/actions/runs/34326836379)
の修正後bundle。旧コードはbundleのcollector commitと同じ
`c0718033ad7bd736bda561a102247ea54e523fb2`、新コードの作業baseは `e762549`。
DB SHA-256は `14d0b6f08cb46cdbd9ba4c8086d9f51d1a1cb94d173c95f81aadd29ded5faf0e`。
判定日は2026-09-09、対象年は2026。7補助入力・metadataのhashも比較前後に照合した。
新コードは作業中snapshotの全path hashとPython source digestを記録して特定する。

## 実データの比較

比較する4出力は `events_public.json`、`events_public.js`、
`event_songs_public.json`、内部用 `public_event_source_map.json`。

| ケース | 判定日 | 対象年 | 結果 |
| --- | --- | --- | --- |
| 通常日 | 2026-09-09 | 2026 | 4出力byte一致・387件 |
| 終了前日 | 2026-02-07 | 2026 | 4出力byte一致・387件 |
| 終了当日 | 2026-02-08 | 2026 | 4出力byte一致・387件 |
| 終了翌日 | 2026-02-09 | 2026 | 4出力byte一致・387件 |
| 過去実績スライド当日 | 2026-01-10 | 2026 | 4出力byte一致・387件 |
| 過去実績スライド翌日 | 2026-01-11 | 2026 | 4出力byte一致・387件 |
| 年末 | 2026-12-31 | 2026 | 4出力byte一致・387件 |
| 年明け・対象年固定 | 2027-01-01 | 2026 | 4出力byte一致・387件 |
| 年明け・対象年を進める | 2027-01-01 | 2027 | 両版とも同じ曲目監査で拒否・4出力なし |

終了境界は倉雀会（北葛西コミュニティ会館）、過去実績スライド境界は
すみだ輪おどり区民感謝デー（すみだ産業会館サンライズホール）から採った代表ケース。
全イベント・全境界日を網羅した比較ではない。seedには同曜日スライド64件があり、
固定日ルールのスライドは0件だったため、後者はfixtureとmutationで検証した。
保存済み正規状態軸を優先する既存挙動は維持しており、この比較は日次の状態軸更新自体を
代替しない。派生軸の終了日包含と過去実績の開始日基準の失効は別の行動テストで確認した。

通常日の公開events SHA-256は
`305a7f6d334c332c0d061cd6515ab2f0cf5690d1eb933e59ee4bb28f7f24ec94`。
site main `770a061` の387件と意味内容が一致し、補正を除いた同期ガードは
`pass / failures=[] / warnings=[]` だった。サイトへの同期や公開は行っていない。

## 年切替で残る問題

2027ケースでは、2025年の「四谷納涼踊り大会」にある「四谷納涼踊り」の
`predicted / probability=95 / inherited_from_year=null / basis=current_hint` が
公開候補に残る。2026投影では同系列の2026開催回に置換されるが、2027投影では
その置換が働かず、間接根拠で90%を超える曲目として監査に止められる。

旧版・新版のexit code、監査エラー、4出力が未生成であることは一致した。
これは安全停止の一致であって、4出力の一致ではない。監査閾値の緩和、DBの手修正、
開催回の年窓変更をR2の構造整理に混ぜていない。

残りは、古い開催回の公開候補選択と曲目の年次扱いを別の意味変更として設計・検証し、
その結果を固定基準にして2027切替を含む4出力比較を再実行すること。

## 検査と証跡

- 全体pytest: **1,888 passed / 238 subtests passed**。
- 9 mutationを別コピーへ適用し、すべて狙った行動テストがred。
  暗黙の判定日、上書き/固定日ルール無視、予測入力の共有参照、終了日の包含、
  スライド期限、曲目出力欠落、historical/seasonの旧guard補正復活を検査した。
- 比較ツールの負例は4出力それぞれの差分、入力書換え、DB/manifest不一致、
  入力欠落、sidecar、重複metadata、旧commit不一致、dirty source特定、1とtrueの差、
  同一拒否のblockedと片側の監査bypassのfailを確認した。
- 独立レビューでcore、現役呼出元、guard、比較器を確認した。
  bundleのcommit照合不足を修正し、拒否比較を含む再レビューを通した。
- 比較に使ったPythonソース629ファイルと最終作業内容のhash差分は0。
  完全な比較JSONのSHA-256は
  `55ef6bd7a92429f7eddefe32908998aeecb87f0f853135f68b6b1cc54fb00e1c`。

DBや生の根拠を公開repositoryへ置かないため、完全な比較JSON・入力/ソースhash一覧・
テストログ・mutationログはローカル証跡 `bonsuke-r2-20260909/` に保持する。
再現コマンドと入力取得手順は
[移行計画](public-json-rdb-projection-migration-plan.md)を参照する。
