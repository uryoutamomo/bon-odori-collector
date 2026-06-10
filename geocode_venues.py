"""公開用会場データに緯度経度を付与する。

入力:
  data/public/venues_public.json

出力:
  data/public/venues_geo.json

国土地理院の住所検索APIを使い、export_public_venues.py とは分離しておく。
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request


BASE_DIR = os.path.dirname(__file__)
IN_JSON = os.path.join(BASE_DIR, "data", "public", "venues_public.json")
OUT_JSON = os.path.join(BASE_DIR, "data", "public", "venues_geo.json")
GSI_ENDPOINT = "https://msearch.gsi.go.jp/address-search/AddressSearch"


POSTAL_RE = re.compile(r"〒\d{3}-\d{4}\s*")
PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)")


def clean_address(address):
    if not address:
        return ""
    address = POSTAL_RE.sub("", address)
    address = PAREN_RE.sub("", address)
    return address.replace("　", " ").strip()


def geocode(address):
    query = urllib.parse.urlencode({"q": address})
    req = urllib.request.Request(f"{GSI_ENDPOINT}?{query}")
    req.add_header("User-Agent", "bon-odori-collector/1.0")
    with urllib.request.urlopen(req, timeout=20) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if not rows:
        return None
    first = rows[0]
    coordinates = first.get("geometry", {}).get("coordinates") or []
    if len(coordinates) != 2:
        return None
    lon, lat = coordinates
    return {
        "lat": lat,
        "lon": lon,
        "matched_title": first.get("properties", {}).get("title"),
    }


def main():
    with open(IN_JSON, "r", encoding="utf-8") as f:
        venues = json.load(f)

    output = []
    failed = []
    for venue in venues:
        name = venue["name"]
        address = clean_address(venue.get("address"))
        item = {
            "name": name,
            "area": venue.get("area"),
            "address": venue.get("address"),
            "query": address,
            "source": "GSI AddressSearch",
        }
        result = geocode(address) if address else None
        if result:
            item.update(result)
        else:
            failed.append(name)
            item.update({"lat": None, "lon": None, "matched_title": None})
        output.append(item)
        time.sleep(0.1)

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"geocoded: {len(output) - len(failed)} / {len(output)} -> {OUT_JSON}")
    if failed:
        print("failed:")
        for name in failed:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
