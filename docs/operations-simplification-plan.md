# 業務フロー簡素化計画（正本1・受信箱1・反映口1・公開口1）

作成日: 2026-07-16 JST
署名: こと（Claude Code）
ステータス: **内田さんGO済み（2026-07-16）。着手順 A→E→C→B→D で即時着手。**

## 目的

「X/YouTube/公式HPから集める → 過去実績から今年を予測する → 公式情報で確定に昇格する → 公開・配信する」という骨格は変えない。
骨格の周りに増殖した **経路・窓口・語彙の多重化** を畳み、業務の流れを一本道にする。

## 現状診断（2026-07-16 実測）

1. **反映口がイベントごとの使い捨てスクリプト**
   collector 直下に Python 340本、うち `apply_*` 64本。`apply_kyobashi5_nouryou_map_2026.py` /
   `apply_tokyofesta_2026_public_events_batch.py`（+batch2）/ `apply_satake_geba_bon_odori.py` のように、
   イベント確定1件ごとに専用スクリプト新造 → dry-run → ことレビュー → apply → こと再検証 → 内田さんGO
   のフルサイクルが回っている。移行期の安全策としては正しかったが、定常運用の単位としては過剰。

2. **レビュー窓口の乱立**
   ローカルレビューコンソール（decisions.json）／日次生成キーボードレビューUI×2（用語・曲候補HTML）／
   DynamoDB イベント候補キュー／x_news_digest_for_oto → rare_signal → backcheck → staged の多段リレー／
   YouTube backfill decision ファイル群。「今日どこを見ればレビューが溜まっているか」が一目で分からない。

3. **公開JSONが後付けパッチの連鎖で作られる**
   `export_public_events.py` 出力後に `apply_public_date_predictions.py` →
   `apply_public_historical_references.py` → `apply_public_season_hints.py` が順に上書き。
   順序依存で由来追跡が困難。freeze ガード空振り・collector↔site 乖離・巻き戻り事故の温床。

4. **状態語彙の重複**
   `date_status` / `display_tier`（5段確度）/ `public_category`（旧4カテゴリ）/ `lifecycle_status` /
   `recurrence_score` が併存し、正と派生の区別が属人化している。

5. **移行の名残が現役の思考コスト**
   collect.yml の freeze 分岐、legacy Notion 書き戻しスクリプト群、notion_snapshot、
   `BON_ODORI_PUBLIC_SOURCE=notion` フォールバック。data/ は670ファイルで正本・中間生成物・
   レビュー残骸・レポートが同居。用語集・曲マスタ・Xメンバーリストは Notion 残置で脱Notion未完遂。

## 目指す形（一本道の業務フロー）

```
【集める】  毎日15:13 collect.yml（現状維持）
   X・RSS・YouTube・公式HP監視 → 証拠として Master RDB へ
      ↓
【予測する】同じ日次runの中で一括計算
   存在・日付・曲の予測 → RDB の predicted レコードに書く
   （公開JSONへの後付けパッチは廃止。export は RDB の読み出し専用投影に）
      ↓
【確認する】受信箱ひとつ
   全種類の判断待ちを RDB の inbox テーブル（kind列で種類分け）に集約
   → レビューコンソール1画面で裁く
      ↓
【反映する】汎用applyひとつ
   「変更リクエスト」（対象イベント・変更内容・根拠URLの小さなJSON）を1本の汎用ツールへ。
   dry-run既定・確認文字列・バックアップ・監査の三重ゲートは現行を流用。
   イベントごとの新スクリプトは作らない
      ↓
【公開する】publish_public_data_flow.py が唯一の経路（1日1回まとめ反映）
      ↓
【配信する】pending_mail.json → send_mail.yml（現状維持）
```

内田さんの関与は3定型に絞る：(a) 受信箱を裁く、(b) 現地・掲示板レポート投入（既存2ツール）、(c) 公開GO（1日1回）。

## 設計原則：過去イベント情報と未来イベント情報の区別は維持する（2026-07-16 内田さん確認）

過去のイベント情報と、これからのイベント情報は**価値も扱い方も違う**。メインコンテンツは「これからのイベント」であり、過去情報は予測の根拠・参考情報（AGENTS.md「年次イベント設計方針」のとおり：過去年から日付を直接コピーしない／YouTubeは過去実績の証拠／公式HP・主催発表が未来の直接証拠）。**本計画の一本化はこの原則に一切触らない。** 各項目での具体的な守り方：

- **B 受信箱**: 統合するのは「置き場と画面」だけ。kind 列で未来系（公式発表検知・日付確定候補・開催直前情報）と過去系（YouTube曲実績・historical backfill・アーカイブ整理）を明確に分け、**未来系を優先表示**（鮮度が命・イベント当日を過ぎると価値が消える）。過去系は急がないバッチ処理のまま。乱立キューに未来情報が埋もれるのを防ぐのが目的で、扱いの均質化はしない。
- **A 汎用apply**: 「historical追加（過去実績の記録）」と「今年の日付確定昇格」は**別の変更種別**として扱う。未来の確定昇格には公式ソースURL必須のバリデーションを入れ、過去実績からの自動昇格は引き続き許さない。
- **D 状態語彙の2軸化**: 開催状態軸（predicted→announced→confirmed→ended/cancelled）は、むしろ過去/未来の区別を**明示的に強める**変更。「これから（predicted/announced/confirmed）」と「終わった・過去の参考（ended/historical）」がデータ上で混ざらなくなる。

## 統合項目

| # | 統合 | 内容 | 消えるもの |
|---|---|---|---|
| A | 反映口の一本化 | `apply_official_notice_report.py`（複数イベント・部分適用・曖昧はスキップ）の設計を汎用化し、イベント確定・日付昇格・historical追加を「変更リクエストJSON」入力で処理する汎用applyを1本つくる | 今後の one-off apply 新造 |
| E | 名残の撤去（第1段=アーカイブのみ） | one-off済みスクリプトを legacy/ ディレクトリへ移動（削除しない）。data/ の完了済みレビュー残骸・レポートをアーカイブ整理 | ルート340本の視認性問題 |
| C | 公開JSONパッチ連鎖の解体 | 日付予測3種（規則・スライド・旬）を RDB 側（predicted_occurrence_dates 系）へ統合し、export_public_events.py を読み出し専用投影に。切替は新旧出力の全件突合で差分ゼロ確認後 | 後付けパッチ3本・順序依存事故 |
| B | 受信箱の一本化 | 判断待ちを RDB の inbox テーブルへ集約、レビューコンソールを唯一の画面に昇格 | キーボードレビューUI×2 の日次生成、rare_signal 多段リレー、decision ファイル乱立 |
| D | 状態語彙の2軸化 | 「今年の開催状態」（predicted→announced→confirmed→ended/cancelled）×「日付確度」（5段tier）の2軸だけを RDB に持ち、他は派生表示に | public_category・lifecycle_status の独立管理 |

DynamoDB キュー（裏取り・イベント候補v2）の RDB 統合は候補だが、稼働中でコストほぼゼロのため優先度最後（B の後に判断）。

## 着手タイミングと安全条件（重要）

**内田さん判断（2026-07-16）＝即時着手。** 根拠：盆助サイトは1日1ユーザー程度で、公開面の事故影響が最小の今が好機
（6月末の RDB 移行前倒しと同じ理屈・成功前例あり）。

ただし **7月に守るべきは「サイト利用者」ではなく「日次の収集ループ」**。
シーズン中の証拠（Xの声・公式発表・現地レポート）は取りこぼすと来年まで取り返せない。よって：

- collect.yml・send_mail.yml・現地レポート2ツールは、各項目の切替が検証完了するまで現行経路を維持
- RDB・スキーマ・collect.yml に触る変更（B/D）は従来の安全手順をフルで踏む：
  dry-run → ことレビュー → apply → こと再検証 → 内田さんGO、バックアップ、audit、guard
- 収集ループに関わるマージは日次cron（15:13 JST）の**成功直後**に入れ、次のcronまで丸1日の修正猶予を確保
- 切替はすべて「新旧並行 → 差分ゼロ確認 → 切替 → 旧経路は当面ロールバック保険として温存」

**着手順 A→E→C→B→D**：リスクの低いものから。前半3つ（A/E/C）が終わると汎用applyとクリーンな
公開経路ができ、後半（B/D）の工事自体が楽になる。
E は A と並行ではなく **A の設計固定後**（上記 E の時期の項参照・2026-07-16 修正）。
C 以降の切替は**新旧出力の全件突合差分ゼロを絶対条件**とする。

## 各項目の受け入れ基準（概要）

- **A**: 汎用apply 1本で「日付確定昇格／historical追加／会場変更／曲実績追加」の直近実例4種を再現できる。
  dry-run 既定・確認文字列・バックアップ・冪等性・部分適用（曖昧はスキップ）を備える。
  AGENTS.md に「イベント個別の apply スクリプトを新造しない」を明文化。
  **仕様の縛り（2026-07-16 おと提案・こと合意）＝「自由に何でも書けるJSON」にはしない。ただの別形態 one-off になるため：**
  - 変更種別は**有限列挙**。初期4種＝ `confirm_current_year_date` / `add_historical_reference` /
    `update_venue` / `add_song_evidence`。種別追加は本ドキュメントと schema の更新をセットで行う
  - **種別ごとに必須根拠を分ける**：`confirm_current_year_date` は公式ソースURL必須。
    `add_historical_reference` は予測根拠・過去実績としての保存（確定昇格に使わない）
  - 入力は **JSON Schema 相当の検証**を通ったものだけ受け付ける
  - 位置づけは「業務判断の一本化」ではなく**「反映経路の一本化」**。判断の中身は種別ごとの
    バリデーションとレビューに残る
- **E**: ルート直下の現役スクリプトが一覧で把握できる本数（目安50本以下）になる。legacy/ 移動のみで削除なし。
  日次・手動の全 workflow が移動後も green。
  **時期（2026-07-16 おと提案・こと合意）＝Aの設計固定＋受け入れテスト実例4種の確定後に着手。**
  理由＝現作業ツリーは未コミット変更・未追跡ファイルが多く、先に大掃除すると A の検証材料
  （one-off の実例）まで埋もれるリスク。分類してから移動する。
- **C**: 新経路（RDB内予測→読み出し専用export）と旧経路（export+パッチ3本）の公開JSON全件突合で差分ゼロ。
  guard_public_events_sync 通過。本番反映後にことが独立検証。
- **B**: 判断待ちの新規発生分が inbox テーブルだけに入る。レビューコンソールから全 kind を裁ける。
  旧キューは読み取り専用で残し、残件消化後に閉鎖。
- **D**: 公開JSON・サイト表示・メール配信の出力が2軸からの派生だけで再現でき、切替前後で表示差分ゼロ。

## 役割分担

- **おと**: 実装（汎用apply・RDBスキーマ・workflow変更・移行スクリプト）
- **こと**: 設計レビュー・dry-run検証・本番独立検証・この計画書の保守
- **内田さん**: 各項目の切替GO・受信箱レビュー

## 段取り

各項目とも: おと plan/dry-run → ことレビュー → apply → こと再検証 → 内田さんGO で切替。
細かい修正の本番デプロイは1日1回まとめ（AGENTS.md 既存ルール）を維持。

## A 詳細設計（2026-07-16 おと plan/dry-run）

`apply_change_requests.py` を新設し、イベントごとの one-off apply 新造を止める入口にする。入力は `request_type=rdb_change_requests` のJSONで、自由記述パッチではなく、以下の有限な `change_type` だけを許可する。

| change_type | 用途 | 主な必須根拠・制約 |
|---|---|---|
| `confirm_current_year_date` | 今年の開催日確定・昇格 | `event_year`、`date_start`、公式・主催者・信頼できる当年ソースURL必須。YouTube過去実績は不可 |
| `add_historical_reference` | 過去実績の参考根拠追加 | 過去年ソースURL必須。`historical_year < event_year`。今年開催確定には昇格しない |
| `update_venue` | 会場ID・会場表記の修正 | 会場名と根拠URL必須。曖昧な会場候補は medium issue でスキップ |
| `add_song_evidence` | 曲実績・告知曲目の追加 | `evidence_mode` を `official_setlist` / `historical_youtube` / `firsthand_observed` から選ぶ |

安全条件：

- dry-run 既定。実DB反映は `--apply --confirm 'APPLY CHANGE REQUESTS'` が必要。
- 受け入れ確認用やダミーURLを含むJSONは `dry_run_only: true` を付ける。`--apply` は `dry_run_only` を含むpayloadを拒否する。
- 各リクエストは `occurrence_id` または `match_hint` で対象を解決する。曖昧・未解決は medium issue としてそのリクエストだけスキップし、解決済みリクエストは適用する。
- foreign key などの整合性エラーは high issue とし、トランザクション全体を rollback する。
- `add_historical_reference` の具体日付は、同一 `occurrence_id + date_start + date_end + date_type` の既存行があれば既存行を更新し、過去one-off由来の別ID行と重複させない。
- apply 時は preflight DB、backup、post-audit、manifest refresh を通す。公開JSON・サイト反映は別工程のまま。

受け入れ確認：

- サンプル: `data/change_requests/a_acceptance_examples_20260716.json`
- 実行: `python3 apply_change_requests.py --requests data/change_requests/a_acceptance_examples_20260716.json`
- 結果: dry-run で4件適用、未解決0、変更処理由来の issue なし。RDB監査は既存系の `source_snapshot_drift` medium 1件のみ。

## E 第1段 分類（2026-07-16 おと）

Aの設計固定後、one-off済み `apply_*.py` の分類リストを `docs/one-off-apply-classification-20260716.md` に作成した。
この時点では移動は未実施。まず現役入口・C/B/Dまで温存するもの・イベント個別one-off移動候補を分けた。

## E 第2段 分類（2026-07-16 おと）

E第1段の実移動後、append系・build系の分類dry-runを `docs/cleanup-script-classification-20260716.md` に作成した。
この時点では移動は未実施。第2段の推奨は、まずNotion単発メモ追記の `append_*.py` 52本を `legacy/notion-notes/` へ移動し、build系は現役workflow・RDB/レビュー基盤を避けて別コミットで小さく進める。

## E 第2段 append系 実移動（2026-07-16 おと）

Notion単発メモ追記の `append_*.py` 52本を `legacy/notion-notes/` へ移動した。`append_youtube_task_list_to_notion.py` はテスト・runbook参照を移動先へ更新済み。

## E 第2段 build系 低リスク群 実移動（2026-07-16 おと）

分類済みの `build_*.py` から、workflow/test/docsの実行参照がない4本だけを `legacy/build-reports/` へ移動した。root直下の `build_*.py` は50本になった。参照更新が必要な `build_low_confidence_backfill_review.py`、Ph2 plan 系、retrospective 系は温存し、別コミットで扱う。

## E 第2段 build系 低リスク群 第2回実移動（2026-07-16 おと）

workflow/docs/scriptsからの実行参照がなく、テストだけが import していた retrospective 補助2本を `legacy/build-reports/` へ追加移動した。テストは移動先ファイルを明示ロードする形へ更新済み。root直下の `build_*.py` は48本になった。

## E 第2段 build系 Ph2/pre-cutover 移行補助クラスタ 実移動（2026-07-16 おと）

workflowには入っていない Ph2/pre-cutover 移行補助5本を `legacy/build-reports/` へ追加移動した。runbookの直接実行コマンドは `PYTHONPATH=. python3 legacy/build-reports/...` に更新し、テストとレビュー補助内の参照パスも移動先へ更新済み。root直下の `build_*.py` は43本になった。`build_low_confidence_backfill_review.py` は `run_daily_youtube_backfill.py` から実行されるため温存する。

## C 第1段 重複postprocessorチェーン除去（2026-07-16 おと）

`export_public_events.py` はすでに `apply_public_date_predictions.py` / `apply_public_historical_references.py` /
`apply_public_season_hints.py` の3処理を内部で呼んでいるため、workflowとローカルYouTube backfill再生成から
同3本の後続実行を外し、公開JSON生成口を `export_public_events.py` に一本化する。外部実行時に渡していた
`--today` 相当は `export_public_events.py` 側でJST当日を使うようにし、検証用に
`BON_ODORI_PUBLIC_TODAY=YYYY-MM-DD` で固定できるようにした。

この段階では3本のpostprocessorスクリプト自体は削除・移動しない。単体テストとロールバック保険として残し、
次段でRDB側の予測/過去実績/旬ヒント投影へ寄せる。

## C 第2段 公開準備入口の足場（2026-07-16 おと）

Collector側の公開データ準備入口として `scripts/publish_public_data_flow.py` を追加した。
この入口は `export_public_events.py` → `build_publication_gap_review.py` →
`review_missing_occurrence_venues.py` → `run_review_console.py --inventory` を順に実行し、
site repo同期・デプロイは含めない。site差分ガードは `--with-guard` 明示時だけ
`guard_public_events_sync.py --report-only` として実行する。

## C 第3段 RDB投影元比較レポート（2026-07-16 おと）

`compare_public_projection_sources.py` を追加し、公開JSONの `date_prediction` / `historical_reference` /
`season_hint` が Master RDB 側の `predicted_occurrence_dates` / `occurrence_dates` /
`event_series.annual_months_json` などから再現可能かを読み取り専用で比較する。出力は
`data/public_projection_source_compare.json` と `.md`。この段階では公開JSON生成ロジックは切り替えない。

目的は、C本体の「RDB内予測→読み出し専用export」へ進む前に、欠けている投影元・フィールド差分・月ヒント差分を
機械的に洗い出すこと。`blocking_row_count = 0` が次段切替検討の前提になる。

## C 第4段 historical_reference のRDB戻し候補生成（2026-07-16 おと）

`build_public_historical_reference_change_requests.py` を追加し、公開JSONに残っている
`historical_reference` から A の `apply_change_requests.py` 用JSONを生成する。出力は
`data/change_requests/public_historical_references_20260716.json` と
`data/public_historical_reference_change_requests.md`。このスクリプト自体は Master RDB を変更しない。

生成されるリクエストは初期状態では `dry_run_only: true` とし、強い一意一致の `occurrence_id` が取れたものだけを
実行候補にする。補助的に、会場名が完全一致し、かつ候補が一意で一定スコア以上のものも実行候補に含める。
曖昧一致・ソースURL欠落・既に同じ `occurrence_id + date_start + date_end + historical_reference` が存在するものは
レポート側で分ける。

## C 第5段 RDB投影統合の差分ゼロゲート（2026-07-16 おと）

C本丸で公開JSON後処理をRDB由来の投影へ寄せる前に、現行経路の意味内容を固定する比較入口として
`scripts/compare_public_export_postprocessors.py` を追加した。同一master DB入力で、
`export_public_events.py` 単独出力と、旧3postprocessor重ねがけ相当の出力を一時ディレクトリ上で比較する。
このゲートを `status=pass` / `deep_equal=true` に保ったまま、date prediction / historical reference /
season hint の順にRDB投影側へ移す。詳細は `docs/public-json-rdb-projection-migration-plan.md`。

## A ステータス：内田さんGO済み・実運用開始（2026-07-16）

- ことレビュー2巡（初回=Finding 1 historical重複・Finding 4 ダミーURL → おと修正 → 再検証全項目合格）を経て、
  **内田さんGO（2026-07-16）＝Aは実運用へ**。
- 以後のイベント確定・日付昇格・historical追加・会場修正・曲実績追加は、one-off スクリプト新造ではなく
  変更リクエストJSON → `apply_change_requests.py` で行う（AGENTS.md 明文化済み）。
- 初の実 apply は次に来る実案件（公式発表・チラシ等）で実施。当面は従来どおり
  dry-run → ことレビュー → apply → こと再検証 を踏み、数件の実績が溜まったらレビュー粒度の緩和を検討する。
- 残作業: A成果物一式の main 反映（ブランチ足場整理と合わせ・おと）。次項目=E（one-off 分類→legacy/ 移動）。

## C 進捗と切替前の作業量（2026-07-16 ことレビュー・こと追記）

第1〜4段のことレビューはすべて合格。実データ差分ゼロ（第1段・209イベント全件一致）はこと側で実証済み。

**C切替（export を RDB 読み出し専用投影にする）の前提 backlog＝compare の blocking 約88件**（日付境界で日々変動）：

- `weak_candidate` 約38件：イベント名+会場名の fuzzy 突合が 0.92 未満。**根治策＝export がビルド時に
  「公開イベント→occurrence_id」の内部専用サイドカー（`data/` 直下・`data/public/` には置かない＝非配信）を
  出力し、compare/builder を ID join 化する**（C本丸設計に組み込む・ことレビュー時提案）
- `no_candidate` 約12件：RDB に 2026 occurrence 自体が無い。occurrence 新設が必要＝A の v2 変更種別
  `create_occurrence` 候補、または B 受信箱の案件
- 残り：ソースURL欠落・historical日付欠落など＝個別レビュー

**builder 出力の昇格手順（確定）**：builder は常に `dry_run_only: true` を吐く純粋生成器のまま固定
（--allow-apply-output は足さない）。実 apply へは「ことレビュー → 承認分だけ `*_reviewed.json` に複製し
フラグ除去（request_id 維持＝A 側 dedupe が冪等性を担保）→ 内田さんGO → apply」の人手ステップを挟む。
件数が増えたら承認 request_id リストを受ける promote スクリプトを別途検討。
