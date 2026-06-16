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
