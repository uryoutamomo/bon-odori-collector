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
verified_by:
  - tests/test_send_mail_delivery_guards.py
updated_for: 6537e7f
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
ことが `data/pending_mail.json` を書いてコミットし、Actions がそれを見つけて送る。
ローカルから直接SMTPを叩かないのは、送信の記録がリポジトリの履歴に必ず残るようにするためである。

## 入力と出力

**入力**

| 何を | どこから |
|---|---|
| 送信すべき本文 | `data/pending_mail.json`（こと が書いてコミットする） |
| 宛先・認証情報 | GitHub Secrets（SMTP 設定） |

**出力**

| 何を | どこへ |
|---|---|
| メール本体 | Gmail SMTP 経由で宛先へ |
| 送信済みの証跡 | `pending_mail.json` の削除コミット |

## 不変条件

### INV-DLV-001 `pending_mail.json` が無いときは、何もせず正常終了する

- **内容**: `send_mail.py` は `data/pending_mail.json` が存在するときだけ送信する。
  無ければ「送信対象なし」と出力して正常終了する。
- **なぜ**: 送信workflowは1日に3回（18:23 / 19:23 / 20:23 JST）起動し、
  さらに push でも起動する。「無ければ何もしない」が守られていないと、
  起動のたびに何かを送ろうとすることになる。
- **破れたときの症状**: 空メールが届く。あるいは起動のたびに失敗通知が出る。
- **守っているコード**: `send_mail.py` の `main()`
- **守っているテスト**: `tests/test_send_mail_delivery_guards.py::SendMailDraftPresenceTest::test_missing_pending_file_returns_zero_without_sending`

### INV-DLV-002 送れないときは、黙って成功にせず、本文を残して失敗させる

- **内容**: `pending_mail.json` があるのに設定不足・本文が空などで送れない場合、
  `send_mail.py` は非ゼロ終了し、**ファイルを削除しない**。
- **なぜ**: ここが「黙って送り損ねない」の要になっている。
  送れなかったのに正常終了してファイルを消してしまうと、本文が失われたうえに、
  誰も送られなかったことに気づけない。**メールが来ないことは、気づきにくい形の障害である。**
- **破れたときの症状**: メールが来ないのに、workflowは緑のまま。本文も失われる。
- **守っているコード**: `send_mail.py` の `main()`（設定不足・本文空で `return 1`）
- **守っているテスト**: `tests/test_send_mail_delivery_guards.py::SendMailFailureKeepsDraftTest::test_missing_credentials_returns_nonzero_and_keeps_draft`、
  `tests/test_send_mail_delivery_guards.py::SendMailFailureKeepsDraftTest::test_empty_body_returns_nonzero_and_keeps_draft`、
  `tests/test_send_mail_delivery_guards.py::SendMailFailureKeepsDraftTest::test_smtp_failure_does_not_become_success_and_keeps_draft`。
  いずれも「非ゼロで終わること」と「`pending_mail.json` が残っていること」の両方を見る。
  片方だけだと、本文が消える壊れ方を見逃す。

### INV-DLV-003 送信に成功したときだけ本文を消し、それをもって二重送信を防ぐ

- **内容**: `send_mail.yml` は `send_mail.py` が成功した後にだけ `pending_mail.json` を
  `git rm` してコミット・プッシュする。以降の起動は INV-DLV-001 により何もしない。
  `send_mail_watchdog.yml` が 19:07 JST に、ファイルが残っていないかを確認し、
  残っていれば送信workflowを起動し直す。
- **なぜ**: 送信済みかどうかの状態を、外部のフラグではなく**リポジトリ上のファイルの有無**で持たせている。
  こうすると「送ったのに記録が無い」状態が原理的に作れない。
  リトライを3回に分けているのも、一時的なSMTP障害で1日ぶんが欠けるのを避けるためである。
- **破れたときの症状**: 同じメールが複数回届く。または障害後に再送されない。
- **守っているコード**: `.github/workflows/send_mail.yml` の削除ステップ、
  `.github/workflows/send_mail_watchdog.yml`
- **守っているテスト**: `tests/test_send_mail_delivery_guards.py::SendMailWorkflowRemovalOrderTest::test_removal_step_does_not_run_when_send_fails`、
  `tests/test_send_mail_delivery_guards.py::SendMailWorkflowRemovalOrderTest::test_workflow_sends_before_removing_the_draft`、
  `tests/test_send_mail_delivery_guards.py::SendMailWorkflowRemovalOrderTest::test_send_step_failure_is_not_swallowed`、
  `tests/test_send_mail_delivery_guards.py::SendMailWatchdogTest::test_watchdog_retriggers_the_send_workflow`。
  削除は workflow 側で起きるため、テストは `send_mail.yml` を YAML として読んで構造を見る。
  **`if: always()` を1行足すだけで、送れなかった本文が消える壊れ方になる**ので、
  順序だけでなく「失敗時にも走る書き方になっていないこと」まで検査している。

## 主要な流れ

1. **こと が本文を書く** — `data/pending_mail.json` を作ってコミット・プッシュ。
2. **送信workflowが起動** — push、または 18:23 / 19:23 / 20:23 JST の定時。
3. **送る** — `send_mail.py`。無ければ何もしない（INV-DLV-001）、送れなければ落とす（INV-DLV-002）。
4. **証跡を残す** — 成功時のみ `pending_mail.json` を削除してコミット（INV-DLV-003）。
5. **見張る** — 19:07 JST の watchdog が残留を確認し、必要なら再起動。

## 依存と影響

**上流**: [マスタ](04-master.md)と各収集工程。本文の中身はこれらから作られる。
ただしこの工程自体は本文の正しさを検査しない。**中身が空でないことしか見ていない。**

**下流**: 無し。ここが終端で、外へ出る。

## 壊れたときの症状

| 症状 | まず見る場所 |
|---|---|
| メールが来ない | `data/pending_mail.json` が残っていないか。残っていれば送信が失敗している |
| メールが来ないのにworkflowは緑 | INV-DLV-002 が破れている可能性。最優先で調べる |
| 同じメールが複数回届く | INV-DLV-003。削除コミットが失敗していないか |
| 本文が空で届く | 本文生成側の問題。この工程は空を弾くだけ |

## 未解決・注意点

- **この工程にはテストが1件も無い。** `tests/` にメール関連のテストファイルが存在しない。
  外向きで取り消せない操作を扱う工程としては、ここが最も薄い。
  上の3つの不変条件はいずれもコードを読んで確認したものだが、
  **壊しても誰も気づかない状態**にある。優先して埋めるべき負債だと考えている。
- 宛先の管理が GitHub Secrets に閉じており、誰に送っているかがリポジトリから読み取れない。
- 週報の分量（声37〜62件・ニュース30〜50件）は運用上の合意だが、機械的な検査は無い。

---

こと（Claude Code）
