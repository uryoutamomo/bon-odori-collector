import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


FEED_URL = "http://minato-bon-odori.blogspot.com/feeds/posts/default?max-results=50"
OUT = Path("data/blog_source_urls.json")
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def main():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    root = ET.fromstring(xml)
    rows = {}
    for entry in root.findall("a:entry", ATOM):
        title_el = entry.find("a:title", ATOM)
        title = (title_el.text or "") if title_el is not None else ""
        url = None
        for link in entry.findall("a:link", ATOM):
            if link.attrib.get("rel") == "alternate":
                url = link.attrib.get("href")
                break
        if title and url and "盆おどり情報" in title:
            rows[title[:120]] = url
            code = re.search(r"\[([A-Za-z0-9-]+)\]", title)
            if code:
                rows[code.group(1)] = url
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} entries -> {OUT}")


if __name__ == "__main__":
    main()
