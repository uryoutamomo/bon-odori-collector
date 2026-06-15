# 渋谷盆踊り2025 調査メモ

- 調査日: 2026-06-15
- 担当: おと（Codex）
- 結論: 公式URL候補は見つかったが、ページ本文を取得できないため本登録は保留。

## 公式・準公式候補

- 公式URL候補: `https://shibuyadogenzaka.com/?p=6827`
  - Exploring Japan with Zen の動画説明欄に `オフィシャルサイト Official Website` として記載。
  - `curl -I` では `200 OK` と `Link: ... /wp/v2/posts/6827` を確認。
  - HTML本文は空、REST APIは WordPress の重大エラー画面を返すため、開催日・会場・主催情報の本文確認は未完了。

## YouTube証拠

- `https://www.youtube.com/watch?v=CTA9El6Hmfg`
  - 説明欄: 2025年8月2日、渋谷109前、BEGIN特別ゲスト、公式URL候補を記載。
- `https://www.youtube.com/watch?v=D8xMGfqtx-Y`
  - 説明欄: August 2, 2025、Shibuya 109前。
- `https://www.youtube.com/watch?v=Ih9l09h-_uw`
  - 説明欄: `2025.8.2 Sat`、Shibuya109。
- `https://www.youtube.com/watch?v=yqg-YEHbV4A`
  - 説明欄: 第6回 渋谷盆踊り、SHIBUYA109前、ただし `2025.8.3 Sat` は暦上 `2025-08-03` が日曜のため曜日矛盾。

## 判断

- 複数動画では `2025-08-02` が優勢。
- ただし新規イベント作成方針は「YouTube候補だけでは即登録しない」ため、公式ページ本文または同等の一次情報が読めるまで `needs_research` のまま保留。
- 公式ページ復旧後に確認する項目: 正式イベント名、開催日、会場、主催/公開対象、住所。
