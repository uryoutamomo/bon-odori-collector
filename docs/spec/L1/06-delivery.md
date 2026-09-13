---
id: L1-delivery
layer: L1
title: 配信サブシステム（メール）
owns:
  - send_mail.py
  - .github/workflows/send_mail.yml
  - .github/workflows/send_mail_watchdog.yml
depends_on:
  - L1-master
invariants:
  - INV-DLV-001
  - INV-DLV-002
  - INV-DLV-003
  - INV-DLV-004
verified_by:
  - tests/test_send_mail_delivery_guards.py
updated_for: d7d5f3f
---

# 配信サブシステム（メール）

> 上位は[全体地図](../README.md)。日刊メールと金曜週報を内田さんへ届ける工程。

## この工程は何のためにあるか

集めた情報を、毎日メールとして届ける工程である。盆助のサイトは「調べに行く」ものだが、
メールは「向こうから来る」ので、日々の変化に気づくための主要な経路になっている。

この工程が他と決定的に違うのは、**送ってしまうと取り消せない**ことだ。
RDBが壊れても直せるし、公開JSONが変でも作り直せる。だがメールは配送された時点で終わりで、
間違いに気づいてから止める手段が無い。したがって設計は、内容の正しさより先に
**「二重に送らない」「黙って送り損ねない」**の2点に寄っている。

構造としては、本文を作る側（こと）と送る側（GitHub Actions）を分けてある。
ことが `data/pending_mail.json` を書いてコミットし、Actions がそれを見つける。
ActionsはSMTPへ渡す**前**に `data/sending_mail.json` へ移してcommit・pushし、送信権をclaimする。
ローカルから直接SMTPを叩かないのは、送信の記録がリポジトリの履歴に必ず残るようにするためである。

## 入力と出力

**入力**

| 何を | どこから |
|---|---|
| 送信すべき本文 | `data/pending_mail.json`（こと が書いてコミットする） |
| claim済み本文 | `data/sending_mail.json`（workflowだけが `pending` から移す） |
| 宛先 | GitHub Secret `MAIL_TO`（カンマ区切り、既定値なし） |
| 認証情報 | GitHub Secrets `MAIL_USERNAME` / `MAIL_APP_PASSWORD` |

**出力**

| 何を | どこへ |
|---|---|
| メール本体 | Gmail SMTP 経由で宛先へ |
| 送信開始の証跡 | `pending_mail.json` から `sending_mail.json` への移動commit |
| 送信完了の証跡 | `sending_mail.json` の削除commit |

## 不変条件

### INV-DLV-001 claim済み本文が無いときは、SMTPへ触らない

- **内容**: `send_mail.py` は指定されたclaim済み本文が存在するときだけ送信する。
  通常の送信対象は `data/sending_mail.json` で、無ければ正常終了する。
- **なぜ**: 送信workflowは1日に3回（18:23 / 19:23 / 20:23 JST）起動し、
  さらにpushでも起動する。`pending_mail.json` を直接送らず、claim済み本文だけを対象にすることで、
  起動の重複が同じ本文の重複送信にならない。
- **破れたときの症状**: 空メールが届く。あるいは起動のたびに失敗通知が出る。
- **守っているコード**: `send_mail.py` の `main()`
- **守っているテスト**: `tests/test_send_mail_delivery_guards.py::SendMailDraftPresenceTest::test_missing_in_flight_file_returns_zero_without_sending`

### INV-DLV-002 送れないときは、黙って成功にせず、本文を残して失敗させる

- **内容**: workflowはclaim前に宛先・認証設定と本文を事前検査する。設定不足・本文空なら
  `pending_mail.json` を残して非ゼロ終了する。claim後にSMTPが失敗した場合は、
  `sending_mail.json` を残して非ゼロ終了する。
- **なぜ**: ここが「黙って送り損ねない」の要になっている。
  送れなかったのに正常終了してファイルを消してしまうと、本文が失われたうえに、
  誰も送られなかったことに気づけない。**メールが来ないことは、気づきにくい形の障害である。**
- **破れたときの症状**: メールが来ないのに、workflowは緑のまま。本文も失われる。
- **守っているコード**: `send_mail.py` の `main()`、`.github/workflows/send_mail.yml` のclaim前事前検査
- **守っているテスト**: `tests/test_send_mail_delivery_guards.py::SendMailFailureKeepsDraftTest::test_missing_credentials_returns_nonzero_and_keeps_draft`、`tests/test_send_mail_delivery_guards.py::SendMailFailureKeepsDraftTest::test_empty_body_returns_nonzero_and_keeps_draft`、`tests/test_send_mail_delivery_guards.py::SendMailFailureKeepsDraftTest::test_smtp_failure_does_not_become_success_and_keeps_draft`、`tests/test_send_mail_delivery_guards.py::SendMailFailureKeepsDraftTest::test_check_only_validates_without_sending`
  「非ゼロで終わること」と「対象の `pending_mail.json` または `sending_mail.json` が残ること」の両方を見る。
  片方だけだと、送れなかった本文が消える壊れ方を見逃す。

### INV-DLV-003 SMTPへ渡す前にclaimし、成否が曖昧な本文は自動再送しない

- **内容**: `send_mail.yml` は事前検査後、SMTPへ触る前に `pending_mail.json` を
  `sending_mail.json` へ移してcommit・pushする。送信成功時だけ `sending_mail.json` を削除する。
  送信後のrunner停止や削除push失敗で `sending_mail.json` が残った場合、定時起動もwatchdogも自動再送しない。
- **なぜ**: SMTPには盆助が使える冪等キーが無く、SMTP成功直後にrunnerが止まると
  「届いたが完了記録が無い」と「届いていない」を機械だけでは区別できない。
  この曖昧状態を自動再送すると二重送信になるため、可用性より二重送信防止を優先する。
- **破れたときの症状**: 同じメールが複数回届く。あるいは `sending_mail.json` が残っているのに自動送信が繰り返される。
- **守っているコード**: `.github/workflows/send_mail.yml` のclaim・送信・完了記録、`.github/workflows/send_mail_watchdog.yml`
- **守っているテスト**: `tests/test_send_mail_delivery_guards.py::SendMailWorkflowClaimOrderTest::test_workflow_claims_before_sending_and_completes_afterward`、`tests/test_send_mail_delivery_guards.py::SendMailWorkflowClaimOrderTest::test_claim_is_committed_and_pushed_before_smtp`、`tests/test_send_mail_delivery_guards.py::SendMailWorkflowClaimOrderTest::test_existing_in_flight_mail_blocks_a_new_claim`、`tests/test_send_mail_delivery_guards.py::SendMailWorkflowClaimOrderTest::test_automatic_push_trigger_is_limited_to_main`、`tests/test_send_mail_delivery_guards.py::SendMailWatchdogTest::test_watchdog_fails_without_retrying_in_flight_mail`

### INV-DLV-004 宛先は `MAIL_TO` だけから読み、ログへ表示しない

- **内容**: 宛先はGitHub Secret `MAIL_TO` のカンマ区切り値だけから作る。ソース内の既定宛先・常時追加宛先は持たず、`MAIL_TO` が空なら送信しない。ログには宛先数だけを出す。
- **なぜ**: コード内の宛先は設定変更で外せず、意図しない相手への配送と個人情報の露出につながる。ログも広い閲覧権限を持ち得るため、実アドレスを出さない。
- **破れたときの症状**: Secretを変更しても旧宛先へ届く。リポジトリやActionsログから個人のメールアドレスが見える。
- **守っているコード**: `send_mail.py` の `get_recipients()` と `main()`
- **守っているテスト**: `tests/test_send_mail_delivery_guards.py::SendMailRecipientConfigurationTest::test_mail_to_is_required_and_draft_is_kept`、`tests/test_send_mail_delivery_guards.py::SendMailRecipientConfigurationTest::test_recipients_come_only_from_mail_to_and_are_deduplicated`、`tests/test_send_mail_delivery_guards.py::SendMailRecipientConfigurationTest::test_log_does_not_print_recipient_addresses`

## 主要な流れ

1. **こと が本文を書く** — `data/pending_mail.json` を作ってコミット・プッシュ。
2. **送信workflowが起動** — push、または 18:23 / 19:23 / 20:23 JST の定時。
3. **事前検査する** — 本文、認証情報、`MAIL_TO`を検査。問題があればpendingのまま失敗（INV-DLV-002 / 004）。
4. **claimする** — `pending_mail.json` を `sending_mail.json` へ移してcommit・push（INV-DLV-003）。
5. **1回だけ送る** — `send_mail.py` はclaim済み本文だけをSMTPへ渡す（INV-DLV-001 / 003）。
6. **完了を記録する** — 成功時のみ `sending_mail.json` を削除してcommit。
7. **見張る** — watchdogはpendingならworkflowを起動する。sendingが残っていれば自動再送せず失敗を通知する。

## 依存と影響

**上流**: [マスタ](04-master.md)と各収集工程。本文の中身はこれらから作られる。
ただしこの工程自体は本文の正しさを検査しない。**中身が空でないことしか見ていない。**

**下流**: 無し。ここが終端で、外へ出る。

## 壊れたときの症状

| 症状 | まず見る場所 |
|---|---|
| メールが来ない | `data/pending_mail.json` または `data/sending_mail.json` が残っていないか |
| メールが来ないのにworkflowは緑 | INV-DLV-002 が破れている可能性。最優先で調べる |
| `pending_mail.json` が残る | 事前検査またはclaim前に失敗。修正後は定時起動で再試行できる |
| `sending_mail.json` が残る | SMTP成否が曖昧。Gmailの送信済みを確認するまでpendingへ戻さない |
| 同じメールが複数回届く | INV-DLV-003。claim前の直接送信または人手での誤った再投入がないか |
| 本文が空で届く | 本文生成側の問題。この工程は空を弾くだけ |

## 未解決・注意点

- SMTP自体に冪等キーがないため、`sending_mail.json` が残った場合の成否判定は自動化できない。
  Gmailの送信済みに同じ件名・本文があれば削除し、無ければ `pending_mail.json` へ戻して再試行する。
- watchdogは赤いworkflowとして異常を残すが、GitHub外への専用通知はまだ無い。Actions失敗通知を見ないと気づけない。
- 宛先は意図的にGitHub Secretsへ閉じたため、リポジトリから配送先を監査できない。Secret変更履歴と実設定の確認はGitHub側で行う。
- 週報の分量（声37〜62件・ニュース30〜50件）は運用上の合意だが、機械的な検査は無い。

---

おと（Codex）
