import os


def load_local_env(path=None):
    path = path or os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_local_env()


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2025-09-03"

EVENT_DATA_SOURCE_ID = os.environ.get(
    "EVENT_DATA_SOURCE_ID",
    "a83b5a63-7411-4d6a-8bbc-83bedf4e7b5d",
)
PLAN_DATA_SOURCE_ID = os.environ.get(
    "PLAN_DATA_SOURCE_ID",
    "6a29d662-cd27-487f-9d76-5a57239b1aa2",
)
VENUE_DATA_SOURCE_ID = os.environ.get(
    "VENUE_DATA_SOURCE_ID",
    "cacdae5c-d793-43c5-b118-596e13023fcc",
)

EVENT_DATABASE_ID = os.environ.get(
    "EVENT_DATABASE_ID",
    "8293b6a7-3ee0-4a68-a365-78b2624e329c",
)
PLAN_DATABASE_ID = os.environ.get(
    "PLAN_DATABASE_ID",
    "010e6789-358f-4252-b1d4-f01e902ba153",
)
VENUE_DATABASE_ID = os.environ.get(
    "VENUE_DATABASE_ID",
    "cbc56bda-2259-46bf-8aac-adb7efd691c2",
)
