# 公式ソース巡回

定番イベントの公式・準公式ページを定期確認し、今年の告知候補を `data/official_source_candidates.json` に出力する。

## 使い方

```bash
python3 check_official_sources.py --year 2026
```

- 対象は `data/evergreen_events.json` の `official_sources` があるイベント。
- 通常実行では、現在月から `lead_months` 先までのイベントだけを確認する。
- 全件確認したい場合は `--all` を付ける。

```bash
python3 check_official_sources.py --year 2026 --all
```

## 登録ルール

`data/evergreen_events.json` のイベントに次を入れる。

- `official_sources`: 巡回するURL。公式サイトのニュース一覧と、分かっている告知記事URLを入れる。
- `official_source_type`: `official` または `hp`。人間が見て公式と判断できる場合だけ `official` にする。
- `confirmation_terms`: そのイベントだと判断する語。イベント名、略称、会場名を入れる。

## 2025年実績から公式HP候補を作る

まずレビュー候補を生成する。

```bash
python3 build_official_source_review.py
```

出力:

- `data/official_source_review_candidates.json`: 判定を書き込むJSON
- `data/official_source_review_candidates.md`: 人間が見やすい一覧

`data/official_source_review_candidates.json` の各行にある `decision` を、必要に応じて次のどれかに変更する。

- `official`: 主催・会場・自治体など、公開サイトで公式告知としてリンクしてよい
- `hp`: 紹介HPまたは準公式。巡回候補には使うが公開リンクはしない
- `post`: SNS投稿。巡回候補とは別扱いで、公開リンクはしない
- `reject`: このイベントの根拠URLではない
- `hold`: 保留

判定済みの `official` / `hp` だけを定番イベント台帳へ反映する。

```bash
python3 apply_official_source_review_decisions.py --dry-run
python3 apply_official_source_review_decisions.py
```

## 判定の考え方

巡回は「公式URLに今年の告知らしいページがあるか」を検出する。公式サイト内でも、別記事や月別アーカイブにイベント名が混ざる場合があるため、候補は自動で本番データへ反映しない。

自動反映してよいのは、少なくとも次を満たす場合に限定する。

- `status` が `confirmed`
- `source_type` が `official`
- `evidence.url` が公式告知として公開表示できる
- `detected_dates` のうち、開催日と記事公開日を人間または専用ロジックで区別できる

公開サイトでは、公式URLを出せるものだけ `公式告知あり` としてリンク表示する。X投稿や紹介HPは根拠有無の表示に留め、リンクは公開しない。
