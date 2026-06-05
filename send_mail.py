"""
盆踊り 日刊メール配信スクリプト（ローカルファイル方式）。

フロー:
  1. ことが data/pending_mail.json を書いてコミット・プッシュ
       {"subject": "...", "html": "完全なHTML文字列", "plain": "省略可"}
  2. GitHub Actions がこのスクリプトを実行
       - pending_mail.json が存在すれば読んで送信
       - 送信後にファイルを削除してコミット（二重送信防止）

fail-safe: ファイルが無ければ何もせず正常終了。
pending_mail.json があるのに設定不足・本文空で送れない場合は非ゼロ終了し、
後続の削除ステップを止めてドラフトを残す。
"""

import os
import json
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formatdate
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_APP_PASSWORD = os.environ.get("MAIL_APP_PASSWORD")
MAIL_TO = os.environ.get("MAIL_TO") or "uryouta77@yahoo.co.jp"

PENDING_PATH = Path(__file__).parent / "data" / "pending_mail.json"


def send_mail(subject, plain_body, html_body=None):
    recipients = [a.strip() for a in MAIL_TO.split(",") if a.strip()]

    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        msg = MIMEText(plain_body, "plain", "utf-8")

    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = MAIL_USERNAME
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
        server.sendmail(MAIL_USERNAME, recipients, msg.as_string())


def main():
    if not PENDING_PATH.exists():
        print("[mail] pending_mail.json なし。送信対象なし。終了します。")
        return 0

    missing = [n for n, v in [
        ("MAIL_USERNAME", MAIL_USERNAME),
        ("MAIL_APP_PASSWORD", MAIL_APP_PASSWORD),
    ] if not v]
    if missing:
        print(f"[mail] pending_mail.json はありますが、設定不足のため送信できません: {', '.join(missing)}")
        return 1

    try:
        draft = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[mail] pending_mail.json の読み込み失敗: {e}")
        raise

    subject = draft.get("subject") or "盆踊り 日刊配信"
    html_body = draft.get("html") or None
    plain_body = draft.get("plain") or ""

    if not plain_body and html_body:
        # HTML のみの場合は素のテキストとして使い回す（SMTP は plain 必須）
        import re
        plain_body = re.sub(r"<[^>]+>", "", html_body).strip()

    if not plain_body:
        print("[mail] pending_mail.json はありますが、本文が空のため送信できません。")
        return 1

    print(f"[mail] 送信開始: {subject} / 宛先: {MAIL_TO}")
    send_mail(subject, plain_body, html_body)
    print("[mail] 送信完了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
