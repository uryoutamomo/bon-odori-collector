"""
盆踊り 日刊メール配信スクリプト（Gitでclaimするローカルファイル方式）。

フロー:
  1. ことが data/pending_mail.json を書いてコミット・プッシュ
       {"subject": "...", "html": "完全なHTML文字列", "plain": "省略可"}
  2. GitHub Actions が設定と本文を事前検査する
  3. pending_mail.json を sending_mail.json へ移してcommit・pushし、送信権をclaimする
  4. このスクリプトが sending_mail.json を1回だけ送信する
  5. 送信成功後に sending_mail.json を削除してcommitする

送信後の後処理に失敗しても sending_mail.json は自動再送しない。
この状態は「SMTPへ渡ったかもしれない曖昧状態」としてwatchdogを失敗させ、
送信済みフォルダを確認してから人が解消する。SMTPに冪等キーが無い以上、
自動再送と二重送信防止を同時には保証できないためである。
"""

import argparse
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
MAIL_TO = os.environ.get("MAIL_TO")

IN_FLIGHT_PATH = Path(__file__).parent / "data" / "sending_mail.json"


def get_recipients():
    configured = [a.strip() for a in (MAIL_TO or "").split(",") if a.strip()]
    if not configured:
        raise ValueError("MAIL_TO に宛先が設定されていません")
    invalid = [a for a in configured if "@" not in a or "\r" in a or "\n" in a]
    if invalid:
        raise ValueError(f"MAIL_TO に不正な宛先が {len(invalid)} 件あります")
    # Secrets側で重複しても、同じ宛先へ2通送らない。
    return list(dict.fromkeys(configured))


def send_mail(subject, plain_body, recipients, html_body=None):
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


def main(draft_path=None, check_only=False):
    draft_path = Path(draft_path or IN_FLIGHT_PATH)
    if not draft_path.exists():
        print(f"[mail] {draft_path.name} なし。送信対象なし。終了します。")
        return 0

    missing = [n for n, v in [
        ("MAIL_USERNAME", MAIL_USERNAME),
        ("MAIL_APP_PASSWORD", MAIL_APP_PASSWORD),
        ("MAIL_TO", MAIL_TO),
    ] if not v]
    if missing:
        print(f"[mail] {draft_path.name} はありますが、設定不足のため送信できません: {', '.join(missing)}")
        return 1

    try:
        recipients = get_recipients()
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[mail] {draft_path.name} の事前検査に失敗: {e}")
        return 1

    subject = draft.get("subject") or "盆踊り 日刊配信"
    html_body = draft.get("html") or None
    plain_body = draft.get("plain") or ""

    if not plain_body and html_body:
        # HTML のみの場合は素のテキストとして使い回す（SMTP は plain 必須）
        import re
        plain_body = re.sub(r"<[^>]+>", "", html_body).strip()

    if not plain_body:
        print(f"[mail] {draft_path.name} はありますが、本文が空のため送信できません。")
        return 1

    if check_only:
        print(f"[mail] 事前検査完了: {draft_path.name} / 宛先数: {len(recipients)}")
        return 0

    print(f"[mail] 送信開始: {subject} / 宛先数: {len(recipients)}")
    send_mail(subject, plain_body, recipients, html_body)
    print("[mail] 送信完了。")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", type=Path, default=IN_FLIGHT_PATH)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.draft, args.check_only))
