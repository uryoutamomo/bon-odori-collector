import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

QUERIES = ["盆踊り", "盆おどり"]
HOME_KEYWORDS = []

def fetch_news(query):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return response.read()
    except Exception as e:
        print(f"Error fetching {query}: {e}")
        return None

def parse_rss(xml_data):
    items = []
    if not xml_data:
        return items
    try:
        root = ET.fromstring(xml_data)
        for item in root.findall('.//item'):
            title = item.find('title').text if item.find('title') is not None else ''
            link = item.find('link').text if item.find('link') is not None else ''
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ''
            items.append({'title': title, 'url': link, 'pubDate': pub_date})
    except Exception as e:
        print(f"Error parsing XML: {e}")
    return items

def main():
    seen_file = 'data/seen.json'
    seen_urls = set()
    if os.path.exists(seen_file):
        try:
            with open(seen_file, 'r', encoding='utf-8') as f:
                seen_urls = set(json.load(f))
        except:
            pass

    latest_items = []
    new_urls = list(seen_urls)

    for q in QUERIES:
        print(f"Searching for: {q}")
        xml_data = fetch_news(q)
        items = parse_rss(xml_data)
        
        for item in items:
            if item['url'] not in seen_urls:
                is_home = any(k in item['title'] for k in HOME_KEYWORDS) if HOME_KEYWORDS else False
                latest_items.append({
                    'title': item['title'],
                    'url': item['url'],
                    'date': item['pubDate'],
                    'is_home': is_home
                })
                new_urls.append(item['url'])

    os.makedirs('data', exist_ok=True)

    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(latest_items, f, ensure_ascii=False, indent=2)

    with open(seen_file, 'w', encoding='utf-8') as f:
        json.dump(new_urls, f, ensure_ascii=False, indent=2)

    print(f"完了: 新着 {len(latest_items)} 件を記録しました。")

if __name__ == '__main__':
    main()
