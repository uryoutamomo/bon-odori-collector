"""Helpers for keeping public-review queues scoped to Tokyo 23 wards."""

from __future__ import annotations

import re
from typing import Any


TOKYO_23_WARDS = (
    "千代田区",
    "中央区",
    "港区",
    "新宿区",
    "文京区",
    "台東区",
    "墨田区",
    "江東区",
    "品川区",
    "目黒区",
    "大田区",
    "世田谷区",
    "渋谷区",
    "中野区",
    "杉並区",
    "豊島区",
    "北区",
    "荒川区",
    "板橋区",
    "練馬区",
    "足立区",
    "葛飾区",
    "江戸川区",
)

TOKYO_23_RE = re.compile("|".join(re.escape(ward) for ward in TOKYO_23_WARDS))
TOKYO_CITY_RE = re.compile(r"東京都?([^、\s　]+市|[^、\s　]+町|[^、\s　]+村)")
NON_TOKYO_PREF_RE = re.compile(
    r"(北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|"
    r"埼玉県|千葉県|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|"
    r"岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|"
    r"和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|"
    r"高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)"
)
KNOWN_OUTSIDE_TOKYO_23_RE = re.compile(
    r"(横浜|川崎|鎌倉|藤沢|浦安|船橋|市川|松戸|柏|さいたま|川口|所沢|"
    r"大阪|夢洲|箕面|八戸|"
    r"国立市|立川市|三鷹市|武蔵野市|府中市|調布市|小金井市|小平市|"
    r"八王子市|町田市|多摩市|西東京市|東久留米市|清瀬市|狛江市|"
    r"国分寺市|東村山市|日野市|青梅市|昭島市|福生市|羽村市|あきる野市|"
    r"稲城市|武蔵村山市|東大和市)"
)


def joined_scope_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item or "") for item in value)
        else:
            parts.append(str(value or ""))
    return " ".join(part for part in parts if part).strip()


def is_tokyo_23_scope(*values: Any) -> bool:
    text = joined_scope_text(*values)
    return bool(TOKYO_23_RE.search(text))


def is_outside_tokyo_23_scope(*values: Any) -> bool:
    text = joined_scope_text(*values)
    if not text:
        return False
    if TOKYO_23_RE.search(text):
        return False
    return bool(
        NON_TOKYO_PREF_RE.search(text)
        or TOKYO_CITY_RE.search(text)
        or KNOWN_OUTSIDE_TOKYO_23_RE.search(text)
    )
