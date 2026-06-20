"""
会場公式サイトの直接監視・収集スクリプト。

Google News などのニュースメディア経由では拾えない、会場公式サイト
（WordPressイベント等）のお知らせを直接 RSS/HTML から取得する。
取得した記事は確定情報として `source: "official_venue"`, `confirmed: true`
を付けて collect.py の latest.json に統合する。

venue_sites.json で監視対象サイトと抽出パターンを定義する。
標準ライブラリ + feedparser のみ・fail-safe（1サイトの失敗が他に影響しない）。
"""

import json
import os
import re
import urllib.request

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "ignore")


def _extract_dates(html: str, date_container_regex: str, date_pair_regex: str):
    """
    記事HTMLから開催日（開始日・終了日）を抽出する。
    見つからなければ (None, None) を返す。
    """
    container_match = re.search(date_container_regex, html, re.S)
    if not container_match:
        return None, None

    container_text = container_match.group(1)
    pair_match = re.search(date_pair_regex, container_text)
    if not pair_match:
        return None, None

    y1, m1, d1, y2, m2, d2 = pair_match.groups()
    y1 = int(y1)
    y2 = int(y2) if y2 else y1  # 終了日に年が省略されていれば開始年を使う

    start = f"{y1:04d}-{int(m1):02d}-{int(d1):02d}"
    end = f"{y2:04d}-{int(m2):02d}-{int(d2):02d}"
    return start, end


def _extract_title(html: str, title_regex: str, fallback: str) -> str:
    m = re.search(title_regex, html)
    if m:
        return m.group(1).strip()
    return fallback


def collect_venue_sites(config_path: str = "venue_sites.json") -> list:
    """
    venue_sites.json の定義に従って各会場公式サイトを巡回し、
    latest.json 形式のアイテムリストを返す。失敗しても空リストを返す（fail-safe）。
    """
    if not _HAS_FEEDPARSER:
        print("[venue_sites] feedparser 未インストールのためスキップ")
        return []

    if not os.path.exists(config_path):
        print(f"[venue_sites] 設定ファイルが無いためスキップ: {config_path}")
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"[venue_sites] 設定ファイル読み込みエラー: {e}")
        return []

    items = []

    for venue in config.get("venues", []):
        venue_name = venue.get("venue_name", "")
        feed_url = venue.get("feed_url", "")
        keywords = venue.get("keywords", [])
        date_container_regex = venue.get("date_container_regex", "")
        date_pair_regex = venue.get("date_pair_regex", "")
        title_regex = venue.get("title_regex", "")

        try:
            parsed = feedparser.parse(feed_url)
            if parsed.bozo and not parsed.entries:
                print(f"[venue_sites] フィード取得失敗: {venue_name}")
                continue

            count = 0
            for entry in parsed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                url = entry.get("link", "")

                # 盆踊り関連のみフィルタ（会場サイトは他イベントも多いため）
                haystack = title + summary
                if keywords and not any(kw in haystack for kw in keywords):
                    continue

                date_start, date_end = None, None
                try:
                    html = _fetch_html(url)
                    date_start, date_end = _extract_dates(
                        html, date_container_regex, date_pair_regex
                    )
                    title = _extract_title(html, title_regex, fallback=title)
                except Exception as e:
                    print(f"[venue_sites] 記事ページ取得エラー ({title}): {e}")

                description = re.sub(r"<[^>]+>", "", summary).strip()[:500]

                items.append({
                    "title": title,
                    "url": url,
                    "date": date_start or "",
                    "date_end": date_end or "",
                    "description": description,
                    "venue_name": venue_name,
                    "source": "official_venue",
                    "confirmed": True,
                    "is_home": False,
                })
                count += 1

            print(f"[venue_sites] {venue_name}: {count} 件追加")

        except Exception as e:
            print(f"[venue_sites] エラー ({venue_name}): {e}")
            # fail-safe: このサイトの失敗は他サイトに影響させない

    return items


def main():
    """
    collect_venue_sites() の結果を data/latest.json に統合し、
    data/seen.json で de-dup する。collect.py 実行後の別ステップとして動く想定。
    fail-safe: 例外が起きてもクラッシュせず終了する（他のワークフローステップに影響しない）。
    """
    try:
        new_items = collect_venue_sites()
    except Exception as e:
        print(f"[venue_sites] 予期せぬエラー（他の収集には影響なし）: {e}")
        return

    if not new_items:
        print("[venue_sites] 新規アイテムなし。終了します。")
        return

    seen_file = "data/seen.json"
    seen_urls = set()
    if os.path.exists(seen_file):
        try:
            with open(seen_file, "r", encoding="utf-8") as f:
                seen_urls = set(json.load(f))
        except Exception:
            pass

    latest_file = "data/latest.json"
    latest_items = []
    if os.path.exists(latest_file):
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                latest_items = json.load(f)
        except Exception:
            pass

    existing_urls = {item.get("url") for item in latest_items}
    new_urls = list(seen_urls)
    added = 0

    for item in new_items:
        if item["url"] not in existing_urls:
            latest_items.append(item)
            existing_urls.add(item["url"])
            added += 1
        if item["url"] not in seen_urls:
            new_urls.append(item["url"])

    os.makedirs("data", exist_ok=True)

    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(latest_items, f, ensure_ascii=False, indent=2)

    with open(seen_file, "w", encoding="utf-8") as f:
        json.dump(new_urls, f, ensure_ascii=False, indent=2)

    print(f"[venue_sites] 完了: 新規 {added} 件を latest.json に追加しました")


if __name__ == "__main__":
    main()
