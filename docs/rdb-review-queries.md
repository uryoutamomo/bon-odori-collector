# RDBレビュークエリ集

作成: 2026-06-16 / おと（Codex）

## 再生成

```bash
python3 build_all_rdb.py
```

個別再生成:

```bash
python3 build_notion_rdb.py
python3 build_evidence_rdb.py
python3 build_youtube_rdb.py
python3 build_bon_odori_rdb.py
```

## 現在のDB

- `data/notion_snapshot.sqlite`: Notion正本ミラー
- `data/evidence.sqlite`: X/YouTube投稿証拠
- `data/youtube_evidence.sqlite`: YouTube詳細分析
- `data/bon_odori.sqlite`: 横断リンク、レビュー状態、未解決点
- `data/rdb_review_queue.json` / `.md`: 横断DBから作るレビューキュー
- `data/rdb_event_apply_plan.json` / `.md`: Notionイベント詳細欄への反映計画
- `data/rdb_song_review_source.json` / `.md`: 曲マスタ未登録候補のレビュー元データ
- `data/rdb_apply_plan_summary.json`: 反映計画の件数サマリ

## 代表クエリ

YouTube証拠がNotionへ反映済みのイベント:

```sql
SELECT e.event_name, e.start_date, i.title, i.url
FROM event_evidence_links l
JOIN events e ON e.event_id = l.event_id
JOIN evidence_items i ON i.evidence_id = l.evidence_id
WHERE l.link_status = 'already_reflected'
ORDER BY e.start_date DESC, e.event_name;
```

YouTube側では既存イベント一致だが、Notion詳細欄への反映確認がまだ必要なもの:

```sql
SELECT e.event_name, e.start_date, i.title, i.url, l.link_source
FROM event_evidence_links l
JOIN events e ON e.event_id = l.event_id
JOIN evidence_items i ON i.evidence_id = l.evidence_id
WHERE l.link_status = 'matched_existing_event'
ORDER BY e.start_date DESC, e.event_name;
```

公式確認待ち・保留・範囲外などのレビューキュー:

```sql
SELECT review_status, priority, COUNT(*) AS count
FROM review_queue
GROUP BY review_status, priority
ORDER BY priority, review_status;
```

曲目候補が曲マスタに未登録のもの:

```sql
SELECT song_title, COUNT(*) AS evidence_count
FROM song_evidence_links
WHERE link_status = 'unmatched_song'
GROUP BY song_title
ORDER BY evidence_count DESC, song_title;
```

2025年イベントでYouTube証拠リンクがあるもの:

```sql
SELECT e.event_name, e.start_date, i.title, i.url, l.link_status
FROM event_evidence_links l
JOIN events e ON e.event_id = l.event_id
JOIN evidence_items i ON i.evidence_id = l.evidence_id
WHERE e.start_date LIKE '2025%'
  AND i.platform = 'youtube'
ORDER BY e.start_date, e.event_name;
```

小さな未解決点:

```sql
SELECT severity, issue_type, description
FROM rdb_issues
ORDER BY severity, issue_type;
```

## 現時点の注意

- X投稿からNotionイベントへの自動リンクは未実装。X投稿は `evidence_items` に保持し、後続で照合ルールを追加する。
- `matched_existing_event` は `data/rdb_event_apply_plan.json` でNotion詳細欄への反映可否を判定する。山王音頭と民踊大会の11件は、Notion詳細欄に「追加動画: 11件」として要約反映済みなので重複追記しない。
- 曲マスタ未登録候補は `data/rdb_song_review_source.json` から人間レビュー/決定ファイルを作って登録する。RDBから曲マスタへ無確認で直接追加しない。
- YouTube 2025総浚いは、この横断DBを使って既存イベント・会場・曲と照合してから進める。
