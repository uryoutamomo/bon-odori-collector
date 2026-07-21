# Notion RDBスナップショット

作成: 2026-06-16 / おと（Codex）

## 位置づけ

`rdb_builders/build_notion_rdb.py` は、主要Notion DBをローカルSQLiteへ読み取り専用スナップショットとして保存する。
YouTube 2025バックフィルやX/YouTube横断分析で、移行前データを確認するためのレガシーミラー。

2026-06-23以降、公開イベント・イベント正本・キュー運用の正本はNotionではない。
Notionスナップショットは読み取り専用の参照素材として扱い、Master RDBへ自動で書き戻さない。

## 出力

- SQLite: `data/notion_snapshot.sqlite`
- サマリー: `data/notion_rdb_summary.json`

## 対象

- 会場マスタ: `notion_venues`
- イベントDB: `notion_events`
- 予定管理DB: `notion_plans`
- 曲マスタ: `notion_songs`
- 用語集V2: `notion_glossary_terms`

共通テーブル:

- `notion_sources`: 取得元DB/Data Source
- `notion_pages`: Notionページ単位の生スナップショット
- `notion_properties`: プロパティ単位の平文化データ
- `notion_relations`: relationプロパティの接続

## 代表クエリ

開催日つきイベントと会場:

```sql
SELECT e.event_name, e.start_date, v.venue_name, v.area
FROM notion_events e
JOIN notion_relations r
  ON r.page_id = e.page_id AND r.property_name = '会場'
JOIN notion_venues v
  ON v.page_id = r.related_page_id
WHERE e.start_date IS NOT NULL AND e.start_date != ''
ORDER BY e.start_date DESC;
```

会場数を地域別に確認:

```sql
SELECT area, COUNT(*) AS venues
FROM notion_venues
GROUP BY area
ORDER BY venues DESC, area;
```

イベント詳細欄にあるYouTube証拠を探す:

```sql
SELECT event_name, start_date
FROM notion_events
WHERE detail LIKE '%[youtube_evidence]%';
```

## 運用

読み取り専用の作業台として扱う。
Notionへの書き戻しは通常運用では行わない。必要な場合は、対象スクリプトが明示的な手動レビュー用途であることを確認してから個別に実行する。
