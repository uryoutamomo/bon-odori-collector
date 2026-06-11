import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

from notion_config import COST_DATABASE_ID, load_local_env


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
JST = timezone(timedelta(hours=9))
DEFAULT_BUDGET_FILE = "data/x_budget.json"
DEFAULT_OUT = "data/weekly_cost_sync_result.json"


def week_start_for(value):
    return value - timedelta(days=value.weekday())


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_week_label(week_start):
    return f"{week_start.isoformat()}週"


def load_budget(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {key: float(value) for key, value in raw.items()}


def daily_costs_for_week(budget, week_start):
    return {
        (week_start + timedelta(days=offset)).isoformat(): float(
            budget.get((week_start + timedelta(days=offset)).isoformat(), 0.0)
        )
        for offset in range(7)
    }


def build_weekly_summary(budget, week_start):
    daily = daily_costs_for_week(budget, week_start)
    twitterapi = round(sum(daily.values()), 6)
    fixed_zero = {
        "github_actions": 0.0,
        "notion": 0.0,
        "gmail_smtp": 0.0,
    }
    return {
        "period": format_week_label(week_start),
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "daily": daily,
        "twitterapi_io": twitterapi,
        **fixed_zero,
        "total": twitterapi,
    }


def notion_request(token, method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Notion API {method} {path} failed: HTTP {error.code} {body}"
        ) from error


def rich_text(value):
    return [{"type": "text", "text": {"content": str(value)}}]


def title_value(value):
    return {"title": rich_text(value)}


def number_value(value):
    return {"number": round(float(value), 6)}


def date_value(value):
    return {"date": {"start": value}}


def find_title_property(database):
    for name, prop in database.get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    raise RuntimeError("Cost database has no title property")


def notion_title(object_):
    return "".join(item.get("plain_text", "") for item in object_.get("title", []))


def search_database(token, query):
    response = notion_request(
        token,
        "POST",
        "/search",
        {
            "query": query,
            "filter": {"property": "object", "value": "database"},
            "page_size": 10,
        },
    )
    return response.get("results", [])


def resolve_cost_database_id(token, database_id):
    try:
        database = notion_request(token, "GET", f"/databases/{database_id}")
        return database_id, database, "configured"
    except RuntimeError as error:
        if "HTTP 404" not in str(error):
            raise

    matches = []
    for query in ("週次コスト", "月次コスト"):
        matches.extend(search_database(token, query))

    by_id = {}
    for database in matches:
        by_id[database.get("id")] = database
    candidates = list(by_id.values())
    if not candidates:
        raise RuntimeError(
            "Cost database was not found by configured ID or Notion search"
        )

    for database in candidates:
        if notion_title(database) in ("📊 週次コスト", "📊 月次コスト"):
            return database["id"], database, "search"
    return candidates[0]["id"], candidates[0], "search"


def ensure_database_shape(token, database_id, apply):
    database_id, database, source = resolve_cost_database_id(token, database_id)
    properties = database.get("properties", {})
    patch = {
        "title": rich_text("📊 週次コスト"),
        "properties": {},
    }
    desired = {
        "twitterapi.io": {"number": {"format": "dollar"}},
        "GitHub Actions": {"number": {"format": "dollar"}},
        "Notion": {"number": {"format": "dollar"}},
        "Gmail SMTP": {"number": {"format": "dollar"}},
        "合計": {"number": {"format": "dollar"}},
        "開始日": {"date": {}},
        "終了日": {"date": {}},
        "メモ": {"rich_text": {}},
    }
    for name, definition in desired.items():
        if name not in properties:
            patch["properties"][name] = definition

    changed = bool(patch["properties"])
    current_title = "".join(
        item.get("plain_text", "") for item in database.get("title", [])
    )
    if current_title != "📊 週次コスト":
        changed = True

    if changed and apply:
        database = notion_request(token, "PATCH", f"/databases/{database_id}", patch)
    return database_id, database, changed, source


def query_existing_page(token, database_id, title_property, period):
    payload = {
        "filter": {
            "property": title_property,
            "title": {"equals": period},
        },
        "page_size": 1,
    }
    response = notion_request(token, "POST", f"/databases/{database_id}/query", payload)
    results = response.get("results", [])
    return results[0] if results else None


def build_properties(title_property, summary):
    memo = "日別 twitterapi.io: " + ", ".join(
        f"{day}=${cost:.6f}" for day, cost in summary["daily"].items()
    )
    return {
        title_property: title_value(summary["period"]),
        "twitterapi.io": number_value(summary["twitterapi_io"]),
        "GitHub Actions": number_value(summary["github_actions"]),
        "Notion": number_value(summary["notion"]),
        "Gmail SMTP": number_value(summary["gmail_smtp"]),
        "合計": number_value(summary["total"]),
        "開始日": date_value(summary["week_start"]),
        "終了日": date_value(summary["week_end"]),
        "メモ": {"rich_text": rich_text(memo)},
    }


def upsert_weekly_cost(token, database_id, summary, apply):
    database_id, database, schema_changed, database_source = ensure_database_shape(
        token,
        database_id,
        apply,
    )
    title_property = find_title_property(database)
    existing = query_existing_page(token, database_id, title_property, summary["period"])
    properties = build_properties(title_property, summary)

    action = "update" if existing else "create"
    page_id = existing.get("id") if existing else None
    if apply:
        if existing:
            notion_request(token, "PATCH", f"/pages/{page_id}", {"properties": properties})
        else:
            page = notion_request(
                token,
                "POST",
                "/pages",
                {
                    "parent": {"database_id": database_id},
                    "properties": properties,
                },
            )
            page_id = page.get("id")

    return {
        "database_id": database_id,
        "database_source": database_source,
        "schema_changed": schema_changed,
        "title_property": title_property,
        "action": action,
        "page_id": page_id,
        "applied": apply,
        **summary,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-file", default=DEFAULT_BUDGET_FILE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--database-id", default=COST_DATABASE_ID)
    parser.add_argument("--week-start")
    parser.add_argument("--today")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_local_env()
    today = parse_date(args.today) if args.today else datetime.now(JST).date()
    week_start = parse_date(args.week_start) if args.week_start else week_start_for(today)
    budget = load_budget(args.budget_file)
    summary = build_weekly_summary(budget, week_start)

    token = os.environ.get("NOTION_API_TOKEN")
    if not token:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if not args.database_id:
        raise SystemExit("COST_DATABASE_ID is not set")

    result = upsert_weekly_cost(token, args.database_id, summary, args.apply)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    mode = "applied" if args.apply else "dry-run"
    print(
        f"[weekly-cost] {mode}: {result['action']} {result['period']} "
        f"total=${result['total']:.6f} schema_changed={result['schema_changed']}"
    )


if __name__ == "__main__":
    main()
