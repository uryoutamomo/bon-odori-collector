import json
import urllib.request

from notion_config import NOTION_API_BASE, NOTION_API_VERSION


class NotionApi:
    def __init__(self, token, api_base=NOTION_API_BASE):
        if not token:
            raise ValueError("NOTION_API_TOKEN is required")
        self.token = token
        self.api_base = api_base

    def request(self, method, path, payload=None):
        data = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )
        req = urllib.request.Request(
            f"{self.api_base}{path}", data=data, method=method
        )
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Notion-Version", NOTION_API_VERSION)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())

    def retrieve_data_source(self, data_source_id):
        return self.request("GET", f"/data_sources/{data_source_id}")

    def query_data_source(self, data_source_id, payload=None):
        rows = []
        cursor = None
        while True:
            page = dict(payload or {})
            page.setdefault("page_size", 100)
            if cursor:
                page["start_cursor"] = cursor
            response = self.request(
                "POST", f"/data_sources/{data_source_id}/query", page
            )
            rows.extend(response.get("results", []))
            if not response.get("has_more"):
                return rows
            cursor = response.get("next_cursor")

    def retrieve_page(self, page_id):
        return self.request("GET", f"/pages/{page_id}")

    def update_page(self, page_id, properties):
        return self.request(
            "PATCH", f"/pages/{page_id}", {"properties": properties}
        )


def validate_data_source(api, data_source_id, expected_properties):
    data_source = api.retrieve_data_source(data_source_id)
    actual = data_source.get("properties", {})
    errors = []
    for name, expected in expected_properties.items():
        prop = actual.get(name)
        if not prop:
            errors.append(f"missing property: {name}")
            continue
        expected_type = expected.get("type")
        if prop.get("type") != expected_type:
            errors.append(
                f"{name}: expected {expected_type}, got {prop.get('type')}"
            )
            continue
        relation_target = expected.get("data_source_id")
        if relation_target:
            actual_target = prop.get("relation", {}).get("data_source_id")
            if actual_target != relation_target:
                errors.append(
                    f"{name}: expected relation to {relation_target}, "
                    f"got {actual_target}"
                )
    if errors:
        raise ValueError(
            f"Notion schema mismatch for {data_source_id}: "
            + "; ".join(errors)
        )
    return data_source


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(
            item.get("plain_text", "")
            for item in prop.get(prop_type, [])
        ).strip()
    if prop_type == "select":
        return (prop.get("select") or {}).get("name", "")
    if prop_type == "url":
        return prop.get("url") or ""
    return ""


def date_value(prop):
    if not prop or prop.get("type") != "date":
        return None
    return prop.get("date")
