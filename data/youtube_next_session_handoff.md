# YouTube次セッション引き継ぎメモ

更新: 2026-06-16 / 署名: おと（Codex）

## 今回の完了状態

- ブランチ: `main`
- YouTube用Notionページ:
  - https://app.notion.com/p/YouTube-37f8be04e762814ca63fdff18fe6cf35
  - page id: `37f8be04-e762-814c-a63f-dff18fe6cf35`
- Notion末尾へ、今回の完了状態を `YouTube次課題整理` として追記済み。
- `out_of_scope 18件` は東京23区公開DBへ入れず、全国展開候補として保持済み。
- YouTube証拠の置き場所は、短期はイベント詳細欄の `[youtube_evidence]`、中期は証拠DB/occurrence分離を推奨する方針で文書化済み。
- 内田さん確認により、YouTube保留案件はおとの推奨セットで確定済み。
- Notion課題リストのチェックボックスは全て完了済み。実装しない方が安全な項目は、代替方針をチェックボックス本文に記載して完了扱いにした。

## 今回追加・更新した成果物

- `build_youtube_nationwide_hold.py`
  - `data/youtube_active_video_review.json` の `action=out_of_scope` を集約。
  - 現在は `横浜開港祭 BON ODORI` 1候補、18動画として保持。
- `data/youtube_nationwide_hold_candidates.json`
- `data/youtube_nationwide_hold_candidates.md`
- `tests/test_build_youtube_nationwide_hold.py`
- `docs/youtube-evidence-architecture.md`
- `docs/youtube-channel-db.md`
  - 全国展開候補と証拠設計メモへの参照を追加。
- `append_youtube_next_tasks_note.py`
  - Notion追記内容を今回の完了状態に更新。
- `data/youtube_user_confirmation_queue.json`
- `data/youtube_user_confirmation_queue.md`
  - 内田さん確認済みの掲載基準判断を保存。
- `append_youtube_user_confirmation_note.py`
  - Notionへ保留案件の確認結果を追記。
- `close_youtube_notion_task_checkboxes.py`
  - Notion課題リストの未チェック項目を、完了または代替方針確定としてチェック済みに更新。

## 内田さん確認済みの保留案件判断

- 渋谷・鹿児島おはら祭: 盆踊り本DBには入れず、周辺の踊り/祭りイベントとして別扱いで保留。
- Pokémon GO Fest TOKYO 2026 ピカチュウ音頭: 開催情報DBには入れず、曲目・現象メモだけ保持。
- 渋谷盆踊り2025: 公式確認まで本登録保留。YouTube証拠は未公式実績候補として別保持。
- 横浜開港祭 BON ODORI: 現行の東京23区公開DBには入れず、全国展開候補として保持のみ。

## 渋谷盆踊り2025の状態

- 結論: 本登録しない。YouTube証拠も既存イベント追記しない。
- 理由:
  - 公式URL候補 `https://shibuyadogenzaka.com/?p=6827` はHTTP 200。
  - レスポンスヘッダにWordPress RESTリンクは出る。
  - 通常本文は空。
  - REST候補 `https://shibuyadogenzaka.com/index.php?rest_route=/wp/v2/posts/6827` は `Content-Type: application/json` だが、本文はWordPressの重大エラーHTML。
  - YouTube説明欄には日付・曜日矛盾がある。2025-08-03は日曜日。
- 方針:
  - 公式ページ本文、公式SNS、主催者ページ、複数信頼ソースのいずれかで日付・会場・名称が確認できるまで保留。
  - YouTube単独では本DB登録しない。

## 全国展開候補の状態

- `data/youtube_nationwide_hold_candidates.md` で確認できる。
- 現在の候補:
  - `横浜開港祭 BON ODORI`
  - date: `2026-06-01`
  - venue: `パシフィコ横浜プラザ広場`
  - videos: 18
  - channels: `Tokyo Lonely Walker`, `祭のきせき 盆踊り`
- 東京23区公開DBには入れない。

## 検証済み

- `python3 build_youtube_nationwide_hold.py`
  - `1 candidates, 18 videos`
- `python3 -m py_compile build_youtube_nationwide_hold.py append_youtube_next_tasks_note.py`
- `python3 -m pytest tests/test_build_youtube_nationwide_hold.py tests/test_build_youtube_active_video_review.py tests/test_append_youtube_task_list_to_notion.py`
  - 6 passed
- Notion追記:
  - `python3 append_youtube_next_tasks_note.py`
  - 成功
- Notion課題リスト完了整理:
  - `python3 close_youtube_notion_task_checkboxes.py`
  - 9件をチェック済みに更新
  - `inspect_notion_blocks.py ... | rg '"type": "to_do".*"checked": false'` は0件

## 次にやるなら

YouTube単体としては一旦止まってよい。

再開する場合の候補:

1. 渋谷盆踊り2025の公式確認を、公式SNSや主催者告知まで広げて再調査。
2. `docs/youtube-evidence-architecture.md` をもとに、YouTube証拠DB/occurrence分離を実装。
3. 全国展開を始める場合、`data/youtube_nationwide_hold_candidates.json` から横浜開港祭を候補として扱う。

## 注意

- YouTube関連作業では、常に上記Notionページを入口として読む。
- Notionやレポートの署名は `おと（Codex）`。
- YouTubeは強い実績証拠だが、公式開催情報とは分ける。
- 動画単独で新規イベントを即登録しない。
- サムネイルは動画証拠として扱い、会場写真として誤用しない。

---

# 追記: 年次開催回・曜日寄せ予測の再開メモ

更新: 2026-06-18 / 署名: おと（Codex）

## 現在地

- 目的は、公式URLがないイベントにも「過去実績に基づく2026年日程予測」を出せるようにすること。
- 内田さんの前提:
  - 盆踊りイベントは「日にち寄せ」より「曜日寄せ」が多い。
  - 比率感は日付寄せ3:曜日寄せ7くらい。
  - したがって、予測ロジックは曜日寄せ優先で設計する。
- 実装済み:
  - `data/event_occurrence_observations.json`
    - 年次開催回観測データ。
    - 現在: 36 observations / 22 series / 2023-2026。
    - 3年窓あり系列: 3。
  - `data/youtube_year_backfill_queue.json`
    - 2024/2023を取りに行くYouTube探索キュー。
  - `data/youtube_year_backfill_candidates.json`
    - YouTube Data APIで取得した過去年候補。
    - 高優先36件まで検索済み。
    - candidates 204 / strong 82 / review 15。
  - `data/event_occurrence_backfill_plan.json`
    - strong候補を開催回単位へ集約。
    - medium/high昇格済み: 12 observations / 67 videos。
    - excluded low: 8 observations。
  - `data/low_confidence_backfill_review.md`
    - lowだが人間確認で使えそうな候補のレビュー表。
  - `build_event_date_predictions.py`
    - 曜日寄せ優先の2026日程予測。
  - `data/event_date_predictions.json`
    - 予測8件。
    - 固定日1件、曜日/週末寄せ7件。
  - `apply_public_date_predictions.py`
    - 公開JSONへ `date_prediction` を付与。
    - 確定済み2026日付は上書きしない。

## Git状況

collectorは以下までpush済み。

- `47f389c Expand YouTube backfill candidate review`
- `27716cd Publish date predictions in public data`
- `d241456 Predict event dates with weekday rules`

siteは以下までpush済み。

- `996fffc Sync public date predictions`

site側の注意:

- `bon-odori-site` には作業前から `app.js` / `index.html` / `style.css` の未コミット変更が残っている。
- `data/events_public.json` への `date_prediction` 同期はpush済み。
- `app.js` に日程予測表示の最小追加をローカルで試したが、既存未コミット変更と混ざるためコミットしていない。
- 次にUIを触る場合は、既存変更の所有者/目的を確認してから分離する。

## API制限

- 2026-06-18時点で YouTube Data API はまだ `HTTP Error 429: Too Many Requests`。
- 確認コマンド:
  - `python3 harvest_youtube_year_backfill.py --priority medium --limit 1 --offset 0 --max-results 1 --out /tmp/youtube_limit_check.json --md-out /tmp/youtube_limit_check.md`
- 結果:
  - 429。
- したがって、中優先キュー以降のAPI追加収集は一旦停止。

## 予測の現状

`data/event_date_predictions.md` の2026予測:

- 丸の内de盆踊り
  - 2026-07-31（金）
  - 7月の最終金曜
- 山王音頭と民踊大会
  - 2026-06-13〜2026-06-15（土〜月）
  - 毎年6/13開始
  - 2026公式確認済みなので公開JSONでは `date_prediction` を付けずスキップ
- シタマチ.ふるさと盆踊り大会
  - 2026-08-15（土）
  - 8月第3土曜
- 東本願寺盆踊り
  - 2026-08-19（水）
  - 8月第3水曜
- 第28回新橋こいち祭 盆踊り
  - 2026-07-23（木）
  - 7月第4木曜
- 自由が丘納涼盆踊り大会
  - 2026-07-18〜2026-07-20（土〜月）
  - 7月16日前後の土曜
- 郡上おどり in 青山 2025
  - 2026-06-19（金）
  - 6月17日前後の金曜
- 西久保八幡神社 盆踊り
  - 2026-08-08（土）
  - 8月9日前後の週末

## なぜ予測件数が少ないか

- 自動昇格をかなり安全側にしているため。
- 2年以上の観測がある系列だけを予測対象にしているため。
- 高優先36件まで検索したが、medium/highで開催回観測に昇格できたものは12件に留まった。
- 中優先以降はYouTube API 429で未収集。
- low候補には使えそうなものもあるが、誤検出も混じる。

## 低信頼候補で使えそうなもの

`data/low_confidence_backfill_review.md` を見る。

有望:

- 自由が丘納涼盆踊り大会 2023-07-17
  - videos 2 / songs 10
  - review_promote候補
- 歌舞伎町BON ODORI 2024-08-17
  - videos 2 / songs 2
  - review_promote候補
- 飛鳥山盆踊り 2023-03-12
  - videos 2 / songs 10
  - ただし sample の1本目が「しながわ中央公園」なので要注意。2本目は飛鳥山公園。

保留/危険:

- 丸の内de盆踊り候補の一部は、東京ガーデンテラス紀尾井町、銀座、日比谷シネマフェスティバルなど別会場。
- 自動昇格すると予測品質を落とす。

## 次にやるなら

1. YouTube API制限が解除されたか確認。
   - 解除されていれば `--priority medium` を小さく再開。
2. 解除されていなければ、`data/low_confidence_backfill_review.md` を人間レビュー。
   - 自由が丘2023、歌舞伎町2024、飛鳥山2023から確認。
3. review_promoteを手動決定ファイルにして、`event_occurrence_backfill_plan` へ昇格する仕組みを作る。
   - 自動昇格ではなく、明示的なaccept/reject方式がよい。
4. 予測UI表示をsiteに入れる。
   - ただし `bon-odori-site` の `app.js/index.html/style.css` に既存未コミット変更あり。
   - 巻き込まないように差分分離する。
5. 公式URLなしイベントの公開表示では、確定日ではなく「日程予測」と明示する。
   - `date_prediction` は確定日ではない。
   - 文言例: `予測: 2026/7/31（金）・7月の最終金曜（公式未確認）`

## 再開時の推奨コマンド

API確認:

```bash
python3 harvest_youtube_year_backfill.py --priority medium --limit 1 --offset 0 --max-results 1 --out /tmp/youtube_limit_check.json --md-out /tmp/youtube_limit_check.md
```

中優先の収集再開:

```bash
python3 harvest_youtube_year_backfill.py --priority medium --limit 8 --offset 0 --max-results 5 --append-existing
python3 build_event_occurrence_backfill_plan.py
python3 apply_event_occurrence_backfill_plan.py
python3 build_event_date_predictions.py --target-year 2026
python3 apply_public_date_predictions.py
python3 -m unittest discover -s tests
```

低信頼レビュー表再生成:

```bash
python3 build_low_confidence_backfill_review.py
```
