# 盆助 システム改善記録（2026-10-03）

担当: おと（Codex）

内田さんの依頼: 「この課題を記録して、１から順に解決していってください」

この文書を7件の改善の進捗と完了証拠の正本にする。番号順に実装・検証・反映を進める。
コード変更、テスト成功、公開成功、公開データ照合は別の到達点として記録する。
プロジェクトのAGENTS.mdにある継続許可と既存の安全手順に従う。

## 一覧

| 番号 | 課題 | 状態 | 完了条件 |
| --- | --- | --- | --- |
| 1 | 過去年の時間が今年の公式確認済み情報として表示される | 完了 | 時間の年・開催回・根拠を検証し、過去/不明の時間へ公式確認を付けない。実例3件と当年の正例を検証し、公開面を照合する |
| 2 | 収集が成功しても公開データが更新されない | 完了 | 最新collector→site→snapshot→liveの内容一致を確認し、同期停止の検出・復旧手順を整える |
| 3 | 収集失敗が情報なし・確認済み探索へ置き換わる | 完了 | success / empty / skipped / failedを区別し、失敗入力で下流の候補・探索履歴を更新しない。障害注入で確認する |
| 4 | 日次監視の誤警報と会場データの監視漏れ | 完了 | 日付跨ぎの遅延を誤判定せず、events・venues・geoのsource/snapshot/liveを監視する |
| 5 | 開催回の識別がイベント名＋会場名に依存する | 完了 | 安定した開催回IDを公開と差分検査まで通し、複数年/年内複数回の行を上書きしない。既存承認との互換を安全に移行する |
| 6 | 最新の公式告知へ辿れる導線が少ない | 実装・検証中 | 主催者・自治体の公式根拠を検証可能な形で公開へ通す。非公式リンクの公開方針を守り、根拠不足を可視化する |
| 7 | 巨大な収集処理と重複する共通規則 | 未着手 | 収集レーンと結果契約を分離し、YouTube URL解釈を統一。固定入力の挙動比較と失敗境界テストを通す |

## 調査時の根拠

調査対象: collector `786d183f`、site `7682d0d`、2026-10-03取得の公開JSON（394件）。
数値はこの調査時点の値であり、改善後の現在値ではない。

1. 荏原第四地区は開催日 `2026-10-11` に対し公開 `time_text` が
   `11月2日(日) 10時-12時、16時-19:30`。説明は2025年実績。
   荏原第三地区・荏原第一地区も同じ年混在。JSの時間ラベルを実行すると
   荏原第四/第三に「公式確認」が付いた。
   `bon-odori-site/scripts/build_public_snapshot.py::extract_time_text` と
   `app.js::officialTimeBadgeHtml` が原因。
2. site同期は9/14〜10/2に連続失敗。10/3のPR267で期限切れスライドに対する古い承認の扱いを修正し、
   siteデプロイは成功した。しかし調査時はcollectorとsiteの22行が異なり、14行が終了済みへ未更新。
   [同期失敗run](https://github.com/uryoutamomo/bon-odori-site/actions/runs/37010615905)
   / [復旧修正PR267](https://github.com/uryoutamomo/bon-odori-collector/pull/267)。
3. `collect.py` のvoices例外後に `deduped_voices=[]` のまま下流へ進む。
   `collection_support/proactive_search.py` は公式取得例外を結果から除外し、未確認の探索履歴を進める。
4. health workflowは実行時JST日付を期待日とし、翌日へ遅れた処理で前日の成功を失敗判定する。
   同期対象3JSONのうちhealthが比較するのはeventsのみ。
5. `classify_public_events_diff.py::index_events` に同名同会場の2025/2026行を渡すと2行が1行になる。
   exporterの内部開催回IDは別source mapへ残すが公開eventsから除かれる。
6. 公開394行中、根拠URLあり60行、ラベルのみ284行、出典なし50行。
   今日以降の開催日がある14行中URLあり4行。siteはofficial以外のリンクを表示しない。
7. `collect.py` 4,510行。動画URL解釈がactive reviewとdescription backfillで異なり、
   Shorts/モバイルURLが後者で取得対象から漏れる。

## 1. 時間情報の対象年と根拠

状態: 完了。[site PR18](https://github.com/uryoutamomo/bon-odori-site/pull/18)、collector契約記録[PR269](https://github.com/uryoutamomo/bon-odori-collector/pull/269)。

当年の開催日・終了日・official URL・時間の範囲を個別に検査する構造化根拠を導入。
旧time_text単独は使わず、当年の開催日まで明記された安全な詳細だけを参考・未確認として残す。
別年・別日・練習・未掲載・内部メモを拒否し、複数時間と最終日例外を保持する。
現在の正本には構造化時刻根拠が無いため、公式確認済みへ推測昇格させない。

独立レビュー、全unittest59件（focused14件）、実データ394件のPython→snapshot→JS一致、
公式URL・開催日ゲートの変異検知、snapshot hygiene/SEOを通過した。安全な参考時間64件、
公式構造化時間0件。荏原第四の実ブラウザは時間未確認、SUMIBONは参考・未確認、390×844でも表示確認。
荏原第四・第三・第一の負例と、丸の内の2種類の時間・築地の最終日例外の正例を固定入力で検査する。

2026-10-03 12:43 JST、[deploy run37093988493](https://github.com/uryoutamomo/bon-odori-site/actions/runs/37093988493)成功。
cache-busted liveのevents394件、geo160件は生成snapshotとcanonical SHA-256一致。
app.js・index.html・venues.htmlもbyte一致。eventsのhashは
`0891352685930a076f4be6d36f7dcaf2652225840bd46833e5204c21f171bb4f`。
この時点のcollector/site差分22行は2番の復旧対象として残り、時間表示修正の公開照合とは区別する。
証跡: `bonsuke-system-improvements-evidence-20261003/step1-live/verification.json`。

## 2. 公開同期の復旧

状態: 完了。ガードを緩めず、PR267の限定された期限切れ承認修正を用いて正規Sync workflowを実行した。
venue source JSONは公開では会場HTMLへ変換され、同名JSONそのものを配信しない。
events・geoのJSONに加え、venues.htmlの公開投影を照合する。

2026-10-03 12:47 JST、[Sync run37094231477](https://github.com/uryoutamomo/bon-odori-site/actions/runs/37094231477)成功。
入力collector SHA `a3d95d92aa0dd62f07494ef49b16949038c14784`、出力site SHA
`829c646e1992a9722f688b9311e7b38c00f55f84`。14終了遷移・5期限切れスライドを限定許可した。
events394・venues176・geo160のcollector/site元JSON完全一致。
eventsとgeoは生成snapshot/liveのcanonical hash一致、app・index・venues.htmlはbyte一致。
公開終了済み258→272、開催予定28→14。他に過去実績73、日程不明35。
公開events hash `9d8d0a6a4e9c926bf475256381f12e576a351a0de42701c144a6ed015c6e4681`。
証跡: `bonsuke-system-improvements-evidence-20261003/step2-live/verification.json`、`step2-sync.log`。
siteの `docs/public-sync-deploy-runbook.md` へ、Syncの停止理由確認、入力固定、公開投影照合と記録を追加した。
手動復旧の成功であり、翌日の自然schedule成功を確認したとは扱わない。
公開会場詳細176ページも生成snapshot/liveのbyte一致を全件確認した。
証跡: `bonsuke-system-improvements-evidence-20261003/step2-venues-live/verification.json`。

## 3. 取得失敗と正常な0件の分離

状態: 完了（[PR271](https://github.com/uryoutamomo/bon-odori-collector/pull/271)のmain反映時点）。RSSと各Xレーンの結果を `success` / `empty` / `skipped` / `failed`
で記録し、内部で捕捉したXエラーや未完了もmainの下流gateへ通す。失敗時は候補・score・公式台帳・速報・
探索履歴・Notion素材を更新しない。正常に取得したXデータはRSS失敗時にも保存し、未完了snapshotとして下流を閉じる。

意図的なX無効化・任意設定不存在はskip、設定破損はfailed。失敗があれば全体healthもunhealthyとなる。
公式トップ・関連ページ取得失敗と巡回skipでは確認日時・回数を進めない。
voices/seenと探索state/reportは、二本目の置換失敗時に旧bytesまたは元の不存在へ復元する。

独立レビュー合格、focused51件、全pytest1,941件・subtests246件、仕様check、diff checkを通過。
正常emptyが下流へ到達する正例と、X障害・設定破損・score保存障害で停止する実mainの負例を検査した。
failed-lane gateを外す変異が統合検査に検知されることも独立確認した。
証跡: `bonsuke-system-improvements-evidence-20261003/step3-tests.log`。
実APIを追加実行する検査ではなく、隔離した故障注入による検証。次の自然scheduleの結果は別途観測する。

## 4. 日次監視のcycleと公開投影

状態: 完了。[site PR20](https://github.com/uryoutamomo/bon-odori-site/pull/20)、main `dc93577`。
17:47 JSTをcycleの締切とし、深夜・翌日へ遅れたscheduleは締切前なら前日cycleで検査する。
開始と完了は独立のtimestampから確認し、欠落・未来・逆順・対象窓外を拒否する。
collector/siteのevents・venues・geo元入力、生成snapshot/liveのevents・geo、会場一覧と全詳細HTMLを検査する。
manifestのschema/version、全unique path、HTTP 200、空error、保存したlive bytesのSHA-256も必須とし、空の会場/geo投影を拒否する。

独立レビュー、全unittest70件・focused20件を通過。manifest hash・venue nonempty gateを外す変異を負例が検知。
2026-10-03 13:46 JST、[手動health run37097601332](https://github.com/uryoutamomo/bon-odori-site/actions/runs/37097601332)成功。
対象cycle `2026-10-02`、events394・venues176・geo160、公開probe179pathを全件照合し、異常0件。
既存アラートはworkflowが復旧close。翌日の自然scheduleの成功とは区別する。
証跡: `bonsuke-system-improvements-evidence-20261003/step4-tests.log`、`step4-health/`、`step4-health.log`。

## 5. 開催回IDの移行

状態: 完了。[collector PR272](https://github.com/uryoutamomo/bon-odori-collector/pull/272)、[site PR21](https://github.com/uryoutamomo/bon-odori-site/pull/21)。
全RDB公開行に安定した`occurrence_id`と実開催回の`event_year`を保持する。日程予測・recurrence・差分ガード・直接同期writerもIDで結び、同名別年・年内複数回を上書きしない。
一意なlegacy aliasだけ移行互換とし、既存IDへ衝突するbridge、異ID、曖昧alias、不正metadataを拒否する。
旧461件の承認は保持。追加2metadataだけを外すv1 hash互換と、IDと全payload hashを固定する新承認を区別する。
曲だけの警告・終了・期限切れ・承認鎖もidentity scopeを広げない。誤IDや年変更を旧承認で流す負例を検査した。

独立レビュー合格、collector全pytest1,991件・subtests246件、site全unittest79件を通過。
正本取得[run37098657888](https://github.com/uryoutamomo/bon-odori-collector/actions/runs/37098657888)でDBと7補助入力のhash不変を確認。manifestの変更は取得時刻のみ。
同じverified bundleの9日付境界・4出力を比較し、既存全項目不変、ID/年は全source-map行と一致、songs/source-mapはbyte不変。
実394件の旧形式siteとの移行guardはpass、承認不一致0件。ID付きsiteの79検査・snapshot hygiene・SEOも合格。
siteの既存一意event URLを維持し、衝突だけIDから分離。正規Sync/Deploy/HealthではID必須として全metadata消失も拒否する。
証跡: `step5-migration.json`、`step5-guard.json`、`step5-collector-tests.log`、`step5-site-ids-tests.log`、`step5-snapshot/`。
2026-10-03 14:16 JST、正規[Sync run37099179223](https://github.com/uryoutamomo/bon-odori-site/actions/runs/37099179223)が成功し、collector/siteの394行完全一致、snapshot/liveのevents/geoとapp/index/venues.html一致を確認。公開394行すべてID一意、実開催年は2023/2025/2026。公開events hash `12fc2cab2dd8a7d4040c2dfa9ca382b2bc6d17fc8537fd3d5398e473e2e011d9`。続く[health run37099283011](https://github.com/uryoutamomo/bon-odori-site/actions/runs/37099283011)も成功し、179path・全176会場詳細の一致と異常0を確認。証跡: `step5-live/verification.json`、`step5-health/`。

## 6. 当年の公式リンク

状態: 実装・検証中。typed `official_current_year` の公開Web URLを公式出典へ通し、RDBの当年primaryを古い長いURLより優先する。Notion由来、Web一般、X、YouTube、除外URLは推測昇格しない。公式リンクの追加だけでは時間確認済みにならない。

実ページ照合で、未来の江戸川4件が誤って東部地区ページを共用していた。開催日・会場は正しい葛西/小岩の令和8年公式一覧と一致し、URLだけを訂正する。canonical `confirm_current_year_date` と `expected_source_url` を用い、競合時は停止する。

- [葛西の2026年一覧](https://www.city.edogawa.tokyo.jp/e034/kurashi/chiikicommunity/johokyoku/kasai/event/index.html): LP26まつり10/3、公社東葛西第一住宅自治会住宅祭10/4、ハイラーク船堀自治会秋まつり10/11。
- [小岩の令和8年一覧](https://www.city.edogawa.tokyo.jp/e035/kurashi/chiikicommunity/johokyoku/koiwa/omatsuri/bonodori26.html): 小岩田自治会盆踊り10/3〜4。

依頼JSON: `data/change_requests/official_source_links_20261003.json`。PR #273をmergeし、remote dry-run `37100075788`、正本適用 `37100172205` を完了した。backup/CAS/再取得検証で4適用・未解決0・監査異常0。取得し直した固定入力 `37100270399` のDB checksumは `ff7c0e8ffa5606a8ea0867c4dbf9eb64b4af38757c930ea8c73fabba08ff85ea`。詳細・時刻・日付・会場を変えず、根拠行と参照を記録した。

12開催回の公式ページを当年の日付・会場と照合し、ID・年・日付・URLをregistryへ固定した。既存公開リンク52組の保持は新規確認済みと区別する。旧Xリンク11組を匿名化し、hostname部分一致で誤分類された一般Web2組を訂正する。公開差分は394件中21件の `source_urls` だけで、曲目/source_mapはbyte一致、その他の全項目は同値。直近14件の公式導線は4件から12件へ増える。時刻の公式確認済み件数は0のまま。

年越し・期限切れを含む9境界で4出力を固定入力比較し、すべて通過した。full suiteは2016 passed/246 subtests、guard関連は108 passed/62 subtests。旧461承認を保持し、新21承認はIDと全payload hashを固定した。実guardはpre/post-syncともpass。旧v1の残存mismatch5件は、今回適用された同ID v2と最終全payload一致を条件に再評価する限定修正で解消した。別ID・不正hash・曖昧aliasはblockを維持する。公開・live照合へ進む。

## 7. 次工程

6の公開照合完了後に着手する。収集レーンの結果契約とYouTube URL解釈を共通化し、挙動比較と故障境界を検査する。
