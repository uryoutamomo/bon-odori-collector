"""
盆踊り 日刊メール配信スクリプト。

役割分担:
  - こわ(Cowork) が Notion DB「📧 メール配信ドラフト」に配信文を書く
      件名 / 配信日 / ステータス=送信予約、本文はページ本文に記載。
  - このスクリプト(GitHub Actions) が「配信日<=今日 かつ ステータス=送信予約」の
    レコードを関係者へ Gmail SMTP で送信し、ステータスを「送信済み」に更新する。

LINE 配信(200通/月の枠制限)の置き換え。標準ライブラリのみ・依存追加なし。
fail-safe: 該当レコードが無ければ何もせず正常終了。設定不足でもクラッシュしない。
"""

import os
import json
import smtplib
import urllib.request
import urllib.error
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formatdate
from datetime import datetime, timezone, timedelta

# --- Notion 設定（collect.py と同じトークンを使う）---
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"
MAIL_DB_ID = os.environ.get("MAIL_DB_ID")  # 📧 メール配信ドラフト DB

# --- メール設定 ---
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")        # 送信元 Gmail アドレス
MAIL_APP_PASSWORD = os.environ.get("MAIL_APP_PASSWORD")  # Gmail アプリパスワード
MAIL_TO = os.environ.get("MAIL_TO") or "uryouta77@yahoo.co.jp"  # 宛先(カンマ区切りで複数可。空なら既定)

JST = timezone(timedelta(hours=9))


def _notion_request(method, path, payload=None):
    url = f"{NOTION_API}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def _plain_text(rich_text_list):
    """Notion rich_text 配列を素のテキストにする。"""
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def fetch_due_drafts(today_iso):
    """配信日<=今日 かつ ステータス=送信予約 のレコードを取得する。"""
    payload = {
        "filter": {
            "and": [
                {"property": "ステータス", "select": {"equals": "送信予約"}},
                {"property": "配信日", "date": {"on_or_before": today_iso}},
            ]
        },
        "sorts": [{"property": "配信日", "direction": "ascending"}],
    }
    res = _notion_request("POST", f"/databases/{MAIL_DB_ID}/query", payload)
    return res.get("results", [])


def build_body(page_id):
    """レコードのページ本文(子ブロック)を素のテキストへ組み立てる。"""
    lines = []
    cursor = None
    while True:
        path = f"/blocks/{page_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        res = _notion_request("GET", path)
        for block in res.get("results", []):
            btype = block.get("type", "")
            data = block.get(btype, {})
            rich = data.get("rich_text")
            if rich is not None:
                text = _plain_text(rich)
                if btype == "bulleted_list_item":
                    lines.append(f"・{text}")
                elif btype == "numbered_list_item":
                    lines.append(f"  {text}")
                elif btype in ("heading_1", "heading_2", "heading_3"):
                    lines.append(f"\n{text}")
                else:
                    lines.append(text)
        if res.get("has_more"):
            cursor = res.get("next_cursor")
        else:
            break
    return "\n".join(lines).strip()


def send_mail(subject, body):
    """Gmail SMTP で MAIL_TO 宛にプレーンテキストメールを送る。"""
    recipients = [a.strip() for a in MAIL_TO.split(",") if a.strip()]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = MAIL_USERNAME
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
        server.sendmail(MAIL_USERNAME, recipients, msg.as_string())


def mark_status(page_id, status, sent_at=None):
    props = {"ステータス": {"select": {"name": status}}}
    if sent_at is not None:
        props["送信日時"] = {"rich_text": [{"type": "text", "text": {"content": sent_at}}]}
    _notion_request("PATCH", f"/pages/{page_id}", {"properties": props})


def main():
    # 設定チェック（fail-safe: 足りなければ何もせず終了）
    missing = [n for n, v in [
        ("NOTION_API_TOKEN", NOTION_TOKEN),
        ("MAIL_DB_ID", MAIL_DB_ID),
        ("MAIL_USERNAME", MAIL_USERNAME),
        ("MAIL_APP_PASSWORD", MAIL_APP_PASSWORD),
    ] if not v]
    if missing:
        print(f"[mail] 設定不足のためスキップ: {', '.join(missing)}")
        return

    now = datetime.now(JST)
    today_iso = now.strftime("%Y-%m-%d")
    print(f"[mail] 配信チェック {today_iso} JST / 宛先: {MAIL_TO}")

    try:
        drafts = fetch_due_drafts(today_iso)
    except urllib.error.HTTPError as e:
        print(f"[mail] Notion クエリ失敗: {e} / {e.read().decode('utf-8', 'ignore')}")
        raise

    if not drafts:
        print("[mail] 送信対象なし。終了します。")
        return

    print(f"[mail] 送信対象 {len(drafts)} 件")
    sent = 0
    for page in drafts:
        page_id = page["id"]
        title_prop = page["properties"].get("件名", {}).get("title", [])
        subject = _plain_text(title_prop) or "盆踊り 日刊配信"
        try:
            body = build_body(page_id)
            if not body:
                print(f"[mail] 本文が空のためスキップ: {subject}")
                continue
            send_mail(subject, body)
            mark_status(page_id, "送信済み", now.strftime("%Y-%m-%d %H:%M JST"))
            sent += 1
            print(f"[mail] 送信完了: {subject}")
        except Exception as e:
            print(f"[mail] 送信エラー ({subject}): {e}")
            try:
                mark_status(page_id, "送信エラー")
            except Exception as e2:
                print(f"[mail] ステータス更新も失敗: {e2}")

    print(f"[mail] 完了: {sent}/{len(drafts)} 件送信")


if __name__ == "__main__":
    main()
