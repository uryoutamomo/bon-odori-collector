# Official Social Source Discovery

作成日: 2026-06-29 JST  
署名: おと（Codex）

## Purpose

町会・自治会・商店街・神社・寺・実行委員会などの公式/主催SNSを、盆踊り日程の直接根拠として使えるようにする。

鉄砲洲納涼盆踊りのように、Web検索では公式HPが出ず、町会Xだけが最速の一次情報になるケースを拾う。

## Classification

| class | meaning | automatic use |
| --- | --- | --- |
| `registered_official_social` | `data/x_official_source_accounts.json` に登録済みの公式/主催SNS | 投稿本文レビュー後、確認済み根拠として使える |
| `candidate_official_social` | プロフィール・投稿内容から公式/主催らしい | アカウント確認レビューへ回す。未登録のまま公開確定根拠にしない |
| `community_source_candidate` | 地域団体らしいが弱い | 監視または追加証拠待ち |
| `unknown_or_personal_social` | 個人投稿・性質不明 | 従来通り探索ヒント。別根拠が必要 |

## Evidence Rules

`registered_official_social` でも、投稿本文に以下が揃うかレビューする。

- イベント名または会場名
- 開催日
- 時間または開催予定の明記
- 投稿者が主催・地域団体・会場・自治体に相当すること

X認証バッジは必須にしない。町会や商店街は未認証でも公式運用が多いため、プロフィールと継続投稿で判断する。

## Workflow

1. `collect.py` が通常検索・ホワイトリスト・公式SNS台帳からX投稿を収集する。
2. `build_x_news_digest_for_oto.py` が投稿を候補化し、`source_officiality` を付与する。
3. `promote_x_news_digest_reviews.py` が、おとレビュー済み候補を `rare_signal_candidates` に昇格する。
4. `build_rare_signal_backcheck_queue.py` が以下に分岐する。
   - 登録済み公式SNS: `review_official_social_post`
   - 公式候補SNS: `review_source_account_then_find_confirmation`
   - 個人/不明SNS: `find_non_x_confirmation`
5. `build_official_social_source_review.py` が、公式候補アカウントのレビューリストを生成する。
6. 確認できたアカウントだけ `data/x_official_source_accounts.json` に登録する。

## Safety Boundary

- `build_official_social_source_review.py` は台帳を書き換えない。
- 未登録の `candidate_official_social` は公開確定根拠にしない。
- 公式SNS台帳への登録は、プロフィール・投稿履歴・地域一致を見て人間が判断する。
- 公開JSONへの反映は既存のレビュー/登録フロー後に行う。日次Web公開デプロイは別運用。

## Teppozu Example

`@iri2choukai` は「入船二丁目町会」かつプロフィールが町会広報であるため、`data/x_official_source_accounts.json` に登録した。

投稿 `https://x.com/iri2choukai/status/2069959259895496872` は、鉄砲洲納涼盆踊りのイベント名、会場、日程、時間を含むため、`official_or_organizer_social` 根拠として登録候補まで進められる。
