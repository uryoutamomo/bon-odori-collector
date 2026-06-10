import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


FEED_URL = "http://minato-bon-odori.blogspot.com/feeds/posts/default?max-results=50"
OUT = Path("data/blog_venue_rows.json")
ATOM = {"a": "http://www.w3.org/2005/Atom"}


WARD_BY_CODE = {
    "chiyoda": "千代田区",
    "chuo": "中央区",
    "minato": "港区",
    "shinjuku": "新宿区",
    "bunkyo": "文京区",
    "taito": "台東区",
    "sumida": "墨田区",
    "koto": "江東区",
    "sinagawa": "品川区",
    "meguro": "目黒区",
    "ota": "大田区",
    "setagaya": "世田谷区",
    "shibuya": "渋谷区",
    "nakano": "中野区",
    "suginami": "杉並区",
    "toshima": "豊島区",
    "kita": "北区",
    "arakawa": "荒川区",
    "itabashi": "板橋区",
    "nerima": "練馬区",
    "adachi": "足立区",
    "katsusika": "葛飾区",
    "edogawa": "江戸川区",
}


def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(?:td|th)>", "\t", value, flags=re.I)
    value = re.sub(r"</tr>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[ \u3000]+", " ", value)
    value = re.sub(r"\t+", "\t", value)
    value = re.sub(r"\n+", "\n", value)
    return value.strip()


def detect_ward(title):
    for ward in WARD_BY_CODE.values():
        if ward in title:
            return ward
    code = re.search(r"\[00[a-z]-([a-z]+)-[pq]\]", title.lower())
    if code:
        return WARD_BY_CODE.get(code.group(1))
    return None


def rows_from_text(text):
    rows = []
    for raw in text.splitlines():
        cells = [c.strip(" \t:：") for c in raw.split("\t") if c.strip(" \t:：")]
        if len(cells) >= 3:
            rows.append(cells)
    return rows


def strip_tags(value):
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[ \u3000]+", " ", value)
    value = re.sub(r"\n\s*", "\n", value)
    return value.strip()


def hrefs(value):
    return re.findall(r"href=['\"]([^'\"]+)['\"]", value)


def extract_structured_rows(title, url, content):
    ward = detect_ward(title)
    out = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", content or "", flags=re.I | re.S):
        cells = re.findall(r"<td\b([^>]*)>(.*?)</td>", tr, flags=re.I | re.S)
        if len(cells) < 5:
            continue
        class_cells = []
        for attrs, body in cells:
            cls = re.search(r"class=['\"]([^'\"]+)['\"]", attrs, flags=re.I)
            class_cells.append((cls.group(1) if cls else "", body))
        loc = next((body for cls, body in class_cells if "cLoc" in cls), "")
        desc = next((body for cls, body in class_cells if "cDsc" in cls), "")
        adr = next((body for cls, body in class_cells if "cAdr" in cls), "")
        src = class_cells[-1][1]
        loc_text = strip_tags(loc)
        loc_lines = [line.strip() for line in loc_text.splitlines() if line.strip()]
        venue = loc_lines[-1] if loc_lines else ""
        if not venue or venue == "会場" or venue == "詳細":
            continue
        date_text = strip_tags(cells[0][1])
        address = strip_tags(adr)
        source_links = [h for h in hrefs(src) if h.startswith("http")]
        out.append(
            {
                "venue": venue,
                "region_hint": ward,
                "address": address or None,
                "date_text": date_text,
                "description": strip_tags(desc),
                "source_title": title[:120],
                "source_url": url,
                "detail_url": source_links[0] if source_links else url,
            }
        )
    return out


def extract_rows(title, url, content):
    structured = extract_structured_rows(title, url, content)
    if structured:
        return structured
    text = clean_text(content)
    ward = detect_ward(title)
    out = []
    for cells in rows_from_text(text):
        joined = " / ".join(cells)
        if "会場" not in joined or "住所" not in joined:
            continue
        venue = None
        address = None
        date = None
        for i, cell in enumerate(cells):
            if cell == "会場" and i + 1 < len(cells):
                venue = cells[i + 1]
            elif cell.startswith("会場"):
                venue = cell.replace("会場", "", 1).strip(" :：")
            if cell == "住所" and i + 1 < len(cells):
                address = cells[i + 1]
            elif cell.startswith("住所"):
                address = cell.replace("住所", "", 1).strip(" :：")
            if cell in ("予定日", "開催日", "日程") and i + 1 < len(cells):
                date = cells[i + 1]
        if venue:
            out.append(
                {
                    "venue": venue,
                    "region_hint": ward,
                    "address": address,
                    "date_text": date,
                    "source_title": title[:120],
                    "source_url": url,
                    "raw": cells,
                }
            )
    return out


def main():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    root = ET.fromstring(xml)
    rows = []
    for entry in root.findall("a:entry", ATOM):
        title_el = entry.find("a:title", ATOM)
        content_el = entry.find("a:content", ATOM)
        title = (title_el.text or "") if title_el is not None else ""
        if "盆おどり情報" not in title:
            continue
        url = None
        for link in entry.findall("a:link", ATOM):
            if link.attrib.get("rel") == "alternate":
                url = link.attrib.get("href")
                break
        rows.extend(extract_rows(title, url, content_el.text if content_el is not None else ""))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
