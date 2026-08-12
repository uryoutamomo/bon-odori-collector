"""Place-dictionary v1 schema, official seed data, and hierarchy derivation."""

from master_rdb.master_db import normalize_text, now_utc, stable_id


MIGRATION_VERSION = 5
MIGRATION_NAME = "place_dictionary_v1"
PLACE_TYPES = ("prefecture", "municipality", "locality", "site")
MAX_PARENT_DEPTH = 16
TOKYO_23_WARDS = (
    "千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区", "江東区",
    "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区", "杉並区", "豊島区",
    "北区", "荒川区", "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
)
DESIGNATED_CITIES = (
    ("北海道", "札幌市"), ("宮城県", "仙台市"), ("埼玉県", "さいたま市"),
    ("千葉県", "千葉市"), ("神奈川県", "横浜市"), ("神奈川県", "川崎市"),
    ("神奈川県", "相模原市"), ("新潟県", "新潟市"), ("静岡県", "静岡市"),
    ("静岡県", "浜松市"), ("愛知県", "名古屋市"), ("京都府", "京都市"),
    ("大阪府", "大阪市"), ("大阪府", "堺市"), ("兵庫県", "神戸市"),
    ("岡山県", "岡山市"), ("広島県", "広島市"), ("福岡県", "北九州市"),
    ("福岡県", "福岡市"), ("熊本県", "熊本市"),
)
PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県",
    "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県",
    "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府",
    "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県",
    "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
    "鹿児島県", "沖縄県",
)

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS place_nodes (
  place_id TEXT PRIMARY KEY,
  place_type TEXT NOT NULL CHECK(place_type IN ('prefecture', 'municipality', 'locality', 'site')),
  canonical_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  parent_place_id TEXT,
  latitude REAL,
  longitude REAL,
  memo TEXT,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'official',
  review_status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(parent_place_id, normalized_name),
  FOREIGN KEY (parent_place_id) REFERENCES place_nodes(place_id)
);

CREATE TABLE IF NOT EXISTS place_aliases (
  place_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'manual',
  PRIMARY KEY (place_id, normalized_alias),
  FOREIGN KEY (place_id) REFERENCES place_nodes(place_id)
);

CREATE INDEX IF NOT EXISTS idx_place_nodes_parent ON place_nodes(parent_place_id);
CREATE INDEX IF NOT EXISTS idx_place_nodes_name ON place_nodes(normalized_name);
CREATE INDEX IF NOT EXISTS idx_place_aliases_name ON place_aliases(normalized_alias);
"""


def _place_id(place_type, canonical_name, parent_place_id=""):
    return stable_id("place", place_type, parent_place_id, canonical_name)


def _insert_node(conn, place_type, canonical_name, parent_place_id=None):
    place_id = _place_id(place_type, canonical_name, parent_place_id or "")
    timestamp = now_utc()
    conn.execute(
        """
        INSERT OR IGNORE INTO place_nodes(
          place_id, place_type, canonical_name, normalized_name, parent_place_id,
          source, confidence, review_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'official_japan_administrative_division', 'official', 'active', ?, ?)
        """,
        (place_id, place_type, canonical_name, normalize_text(canonical_name), parent_place_id, timestamp, timestamp),
    )
    return place_id


def seed_official_administrative_places(conn):
    """Idempotently seed 47 prefectures, 23 wards, and 20 designated cities."""
    prefecture_ids = {name: _insert_node(conn, "prefecture", name) for name in PREFECTURES}
    for ward in TOKYO_23_WARDS:
        _insert_node(conn, "municipality", ward, prefecture_ids["東京都"])
    for prefecture, city in DESIGNATED_CITIES:
        _insert_node(conn, "municipality", city, prefecture_ids[prefecture])
    return {"prefecture_count": len(PREFECTURES), "municipality_count": len(TOKYO_23_WARDS) + len(DESIGNATED_CITIES)}


def table_names(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def migrate_place_dictionary(conn):
    """Install the independent dictionary and seed only official administrative rows."""
    before = table_names(conn)
    conn.executescript(CREATE_TABLES)
    seed = seed_official_administrative_places(conn)
    if "schema_migrations" in table_names(conn):
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
            (MIGRATION_VERSION, MIGRATION_NAME, now_utc()),
        )
    return {
        "schema": "place_dictionary_v1",
        "migration_version": MIGRATION_VERSION,
        "migration_name": MIGRATION_NAME,
        "tables_created": sorted({"place_nodes", "place_aliases"} - before),
        "place_node_count": conn.execute("SELECT COUNT(*) FROM place_nodes").fetchone()[0],
        "place_alias_count": conn.execute("SELECT COUNT(*) FROM place_aliases").fetchone()[0],
        **seed,
    }


def is_tokyo23_place(conn, place_id):
    """Derive Tokyo-23 membership from the parent chain; reject cycles loudly."""
    seen = set()
    chain = []
    current = place_id
    while current:
        if current in seen:
            raise ValueError(f"place hierarchy cycle detected at {current}")
        if len(seen) >= MAX_PARENT_DEPTH:
            raise ValueError(f"place hierarchy depth exceeded for {place_id}")
        seen.add(current)
        row = conn.execute(
            "SELECT place_id, place_type, canonical_name, parent_place_id FROM place_nodes WHERE place_id = ?",
            (current,),
        ).fetchone()
        if row is None:
            return False
        chain.append(row)
        current = row[3]
    return (
        any(row[1] == "municipality" and row[2] in TOKYO_23_WARDS for row in chain)
        and any(row[1] == "prefecture" and row[2] == "東京都" for row in chain)
    )
