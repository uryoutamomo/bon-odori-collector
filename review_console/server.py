#!/usr/bin/env python3
"""Local HTTP server for the review console."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from review_console import data


STATIC_DIR = Path(__file__).resolve().parent / "static"


class ReviewConsoleHandler(BaseHTTPRequestHandler):
    server_version = "BonOdoriReviewConsole/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[review-console] {self.address_string()} - {fmt % args}")

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            return self.serve_static("index.html")
        if parsed.path.startswith("/static/"):
            return self.serve_static(parsed.path.removeprefix("/static/"))
        if parsed.path == "/api/inventory":
            return self.send_json(data.load_inventory(include_items=False))
        if parsed.path == "/api/admin-summary":
            return self.send_json(data.load_admin_summary())
        if parsed.path == "/api/ops-metrics":
            return self.send_json(data.load_ops_metrics())
        if parsed.path == "/api/collection-status":
            return self.send_json(data.load_collection_status())
        if parsed.path == "/api/ops-history":
            query = parse_qs(parsed.query)
            limit_text = first_query(query, "limit")
            try:
                limit = max(1, min(int(limit_text), 365)) if limit_text else 30
            except ValueError:
                limit = 30
            payload = data.load_ops_metrics(history_limit=limit)
            return self.send_json(
                {
                    "schema_version": payload["schema_version"],
                    "generated_at": payload["generated_at"],
                    "history_path": payload["history_path"],
                    "history": payload["history"],
                    "trend_metrics": payload["trend_metrics"],
                }
            )
        if parsed.path == "/api/items":
            inventory = data.load_inventory()
            query = parse_qs(parsed.query)
            return self.send_json(filter_items(inventory, query))
        if parsed.path.startswith("/api/item/"):
            item_id = unquote(parsed.path.removeprefix("/api/item/"))
            item = data.load_item(item_id)
            if not item:
                return self.send_json({"error": "item not found"}, HTTPStatus.NOT_FOUND)
            return self.send_json(item)
        if parsed.path == "/api/decisions":
            return self.send_json(data.load_decisions())
        if parsed.path == "/api/undo-status":
            return self.send_json(data.undo_status())
        if parsed.path == "/api/stage-status":
            return self.send_json(data.stage_status())
        if parsed.path == "/api/adjudication/holds":
            return self.send_json({"holds": data.load_adjudication_holds()})
        if parsed.path.startswith("/api/adjudication/hold/"):
            hold = data.load_adjudication_hold(unquote(parsed.path.removeprefix("/api/adjudication/hold/")))
            if not hold:
                return self.send_json({"error": "hold not found"}, HTTPStatus.NOT_FOUND)
            return self.send_json(hold)
        if parsed.path == "/api/adjudication/status":
            return self.send_json(data.adjudication_status())
        return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/decision":
                payload = self.read_json_body()
                saved = data.save_decision(
                    item_id=payload.get("item_id", ""),
                    decision=payload.get("decision", ""),
                    note=payload.get("note", ""),
                    apply_value=payload.get("apply_value", ""),
                    target_event_name=payload.get("target_event_name", ""),
                    target_song_names=payload.get("target_song_names", ""),
                    target_song_id=payload.get("target_song_id", ""),
                    reviewer=payload.get("reviewer", "内田さん"),
                )
                return self.send_json({"ok": True, "decision": saved})
            if parsed.path == "/api/undo":
                undone = data.undo_last_decision()
                return self.send_json({"ok": True, **undone})
            if parsed.path == "/api/export":
                exported = data.export_decisions()
                return self.send_json(
                    {
                        "ok": True,
                        "decision_count": exported["decision_count"],
                        "path": data.rel_path(data.EXPORT_PATH),
                        "markdown_path": data.rel_path(data.EXPORT_MD_PATH),
                    }
                )
            if parsed.path == "/api/inventory/write":
                inventory = data.write_inventory()
                return self.send_json(
                    {
                        "ok": True,
                        "source_count": len(inventory["sources"]),
                        "path": data.rel_path(data.INVENTORY_PATH),
                        "markdown_path": data.rel_path(data.INVENTORY_MD_PATH),
                    }
                )
            if parsed.path == "/api/stage-apply":
                result = data.stage_apply(write=True)
                return self.send_json({"ok": True, **result})
            if parsed.path == "/api/stage-ack":
                payload = self.read_json_body()
                result = data.acknowledge_stage(
                    acknowledged_by=payload.get("acknowledged_by", "内田さん"),
                )
                return self.send_json({"ok": True, "acknowledgement": result})
            if parsed.path == "/api/operation/run":
                payload = self.read_json_body()
                result = data.run_console_operation(payload.get("operation_id", ""))
                status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
                return self.send_json({"ok": result.get("ok"), "result": result}, status)
            if parsed.path == "/api/adjudication/claim":
                payload = self.read_json_body()
                return self.send_json({"ok": True, **data.claim_adjudication_hold(payload.get("hold_id", ""), payload.get("claimed_by", "uchida"), bool(payload.get("release")))})
            if parsed.path == "/api/adjudication/decide":
                payload = self.read_json_body()
                return self.send_json({"ok": True, "adjudication": data.save_adjudication(payload.get("hold_id", ""), payload.get("action", ""), payload.get("target_id"), payload.get("reason_detail", ""), payload.get("decided_by", "uchida"))})
            if parsed.path == "/api/adjudication/decide-batch":
                payload = self.read_json_body()
                return self.send_json({"ok": True, "adjudications": data.save_adjudication_batch(payload.get("hold_ids", []), payload.get("action", ""), payload.get("reason_detail", ""), payload.get("decided_by", "uchida"))})
        except ValueError as exc:
            return self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except json.JSONDecodeError as exc:
            return self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def serve_static(self, name: str) -> None:
        safe_name = name.replace("\\", "/").lstrip("/")
        path = (STATIC_DIR / safe_name).resolve()
        if STATIC_DIR not in path.parents and path != STATIC_DIR:
            return self.send_text("bad path", HTTPStatus.BAD_REQUEST)
        if not path.exists() or not path.is_file():
            return self.send_text("not found", HTTPStatus.NOT_FOUND)
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def filter_items(inventory: dict, query: dict[str, list[str]]) -> dict:
    status = first_query(query, "status")
    source_id = first_query(query, "source")
    domain = first_query(query, "domain")
    action_group = first_query(query, "action_group")
    time_scope = first_query(query, "time_scope")
    search = first_query(query, "q").casefold()
    limit_text = first_query(query, "limit")
    try:
        limit = max(1, min(int(limit_text), 1000)) if limit_text else 250
    except ValueError:
        limit = 250
    items = []
    for item in inventory["items"]:
        if status and item["status"] != status:
            continue
        if source_id and item["source_id"] != source_id:
            continue
        if domain and item["domain"] != domain:
            continue
        if action_group and item.get("action_group") != action_group:
            continue
        if time_scope and item.get("time_scope") != time_scope:
            continue
        if search:
            haystack = " ".join(
                str(item.get(name, ""))
                for name in (
                    "title",
                    "subtitle",
                    "source_title",
                    "domain",
                    "action_group_label",
                    "action_group_reason",
                    "action",
                    "description",
                )
            ).casefold()
            if search not in haystack:
                continue
        items.append(item)
    return {"generated_at": inventory["generated_at"], "count": len(items), "items": items[:limit]}


def first_query(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or [""]
    return values[0]


def serve(host: str = "127.0.0.1", port: int = 8751) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("review console must bind to localhost")
    server = ThreadingHTTPServer((host, port), ReviewConsoleHandler)
    print(f"review console: http://{host}:{port}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8751)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
