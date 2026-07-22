#!/usr/bin/env python3
"""Replace Mermaid flow diagrams on a Notion page with diagrams.net embeds."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from notion_support.notion_config import load_local_env


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
OUT_DIR = Path("docs/notion-flow-diagrams")


@dataclass
class Node:
    key: str
    label: str = ""
    shape: str = "rectangle"
    group: str = ""


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    dashed: bool = False


@dataclass
class Diagram:
    title: str
    direction: str
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)


def notion_request(method: str, path: str, payload: dict | None = None) -> dict:
    token = os.environ.get("NOTION_API_TOKEN")
    if not token:
        raise SystemExit("NOTION_API_TOKEN is not set")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        NOTION_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def rich_text(value: list[dict] | None) -> str:
    return "".join(part.get("plain_text", "") for part in (value or []))


def children(block_id: str) -> list[dict]:
    rows: list[dict] = []
    cursor = ""
    while True:
        path = f"/blocks/{block_id}/children?page_size=100"
        if cursor:
            path += "&" + urllib.parse.urlencode({"start_cursor": cursor})
        page = notion_request("GET", path)
        rows.extend(page.get("results") or [])
        if not page.get("has_more"):
            return rows
        cursor = page.get("next_cursor") or ""


def slugify(text: str) -> str:
    value = re.sub(r"[^\w一-龥ぁ-んァ-ン]+", "-", text, flags=re.UNICODE)
    return value.strip("-").lower()[:80] or "diagram"


def clean_label(text: str) -> str:
    value = text.strip().strip('"').strip("'")
    value = value.replace("<br/>", "\n").replace("<br>", "\n").replace("\\n", "\n")
    value = re.sub(r"<[^>]+>", "", value)
    return value.strip()


def node_shape(token: str) -> str:
    if "{" in token and "}" in token:
        return "rhombus"
    if "([" in token or "[(" in token:
        return "rounded"
    if "[(" in token and ")]" in token:
        return "cylinder"
    if token.endswith(")") and "([" not in token:
        return "ellipse"
    return "rectangle"


NODE_RE = re.compile(
    r"^\s*([A-Za-z0-9_][\w.-]*|\[\*\])\s*(?:"
    r"(\[\([^\]]+\)\]|\(\[[^\]]+\]\)|\[\[[^\]]+\]\]|\[[^\]]+\]|\{[^}]+\}|\([^)]+\)))?"
)


def parse_node_token(token: str, diagram: Diagram, group: str = "") -> str:
    token = token.strip()
    match = NODE_RE.match(token)
    if not match:
        return token
    key = match.group(1)
    raw_label = match.group(2) or ""
    if key == "[*]":
        label = "Start/End"
        shape = "ellipse"
    elif raw_label:
        label = clean_label(raw_label[1:-1])
        shape = node_shape(raw_label)
    else:
        label = key
        shape = "rectangle"
    node = diagram.nodes.get(key)
    if node is None:
        diagram.nodes[key] = Node(key=key, label=label, shape=shape, group=group)
    else:
        if raw_label and (not node.label or node.label == key):
            node.label = label
            node.shape = shape
        if group and not node.group:
            node.group = group
    return key


def parse_flowchart(title: str, source: str) -> Diagram:
    first = next((line.strip() for line in source.splitlines() if line.strip()), "")
    direction = "LR" if re.search(r"\bLR\b", first) else "TB"
    diagram = Diagram(title=title, direction=direction)
    group_stack: list[str] = []

    for raw in source.splitlines()[1:]:
        line = raw.strip()
        if not line or line.startswith("%%") or line.startswith(("classDef", "class ", "style ")):
            continue
        if line.startswith("subgraph "):
            match = re.match(r"subgraph\s+([^\[]+)(?:\[(.*)\])?", line)
            label = clean_label(match.group(2) if match and match.group(2) else line[9:])
            group_stack.append(label)
            continue
        if line == "end":
            if group_stack:
                group_stack.pop()
            continue
        group = " / ".join(group_stack)

        edge_match = re.search(r"(-\.?\s*(?:[^-.>]+?)?\s*\.?->|==>)", line)
        if edge_match:
            left = line[: edge_match.start()].strip()
            right = line[edge_match.end() :].strip()
            marker = edge_match.group(1)
            label = ""
            if "--" in marker or "-." in marker:
                label = clean_label(marker.replace("-", "").replace(".", "").replace(">", ""))
            if right.startswith("|"):
                pipe_end = right.find("|", 1)
                if pipe_end > 0:
                    label = clean_label(right[1:pipe_end])
                    right = right[pipe_end + 1 :].strip()
            src = parse_node_token(left, diagram, group)
            dst = parse_node_token(right, diagram, group)
            diagram.edges.append(Edge(src=src, dst=dst, label=label, dashed="-." in marker))
            continue

        if NODE_RE.match(line):
            parse_node_token(line, diagram, group)

    return diagram


def parse_state(title: str, source: str) -> Diagram:
    diagram = Diagram(title=title, direction="LR")
    for raw in source.splitlines()[1:]:
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        match = re.match(r"(.+?)\s+-->\s+(.+?)(?:\s*:\s*(.*))?$", line)
        if not match:
            continue
        src = parse_node_token(match.group(1), diagram)
        dst = parse_node_token(match.group(2), diagram)
        label = clean_label(match.group(3) or "")
        diagram.edges.append(Edge(src=src, dst=dst, label=label))
    return diagram


def parse_mermaid(title: str, source: str) -> Diagram:
    stripped = source.lstrip()
    if stripped.startswith("stateDiagram"):
        return parse_state(title, source)
    return parse_flowchart(title, source)


def layout(diagram: Diagram) -> dict[str, tuple[int, int]]:
    indegree = {key: 0 for key in diagram.nodes}
    outgoing: dict[str, list[str]] = {key: [] for key in diagram.nodes}
    for edge in diagram.edges:
        if edge.src in diagram.nodes and edge.dst in diagram.nodes:
            indegree[edge.dst] = indegree.get(edge.dst, 0) + 1
            outgoing.setdefault(edge.src, []).append(edge.dst)

    roots = [key for key, value in indegree.items() if value == 0]
    if not roots and diagram.nodes:
        roots = [next(iter(diagram.nodes))]
    layer = {key: 0 for key in roots}
    queue = list(roots)
    while queue:
        current = queue.pop(0)
        for dst in outgoing.get(current, []):
            if dst in layer:
                continue
            layer[dst] = layer[current] + 1
            queue.append(dst)
    for key in diagram.nodes:
        layer.setdefault(key, max(layer.values(), default=0) + 1)

    groups: dict[int, list[str]] = {}
    for key, value in layer.items():
        groups.setdefault(value, []).append(key)
    for keys in groups.values():
        keys.sort(key=lambda key: (diagram.nodes[key].group, diagram.nodes[key].label))

    positions: dict[str, tuple[int, int]] = {}
    if diagram.direction == "LR":
        x_gap, y_gap = 260, 125
        for value, keys in groups.items():
            total = (len(keys) - 1) * y_gap
            for idx, key in enumerate(keys):
                positions[key] = (40 + value * x_gap, 80 + idx * y_gap - total // 2)
    else:
        x_gap, y_gap = 260, 135
        for value, keys in groups.items():
            total = (len(keys) - 1) * x_gap
            for idx, key in enumerate(keys):
                positions[key] = (80 + idx * x_gap - total // 2, 80 + value * y_gap)
    min_x = min((x for x, _ in positions.values()), default=0)
    min_y = min((y for _, y in positions.values()), default=0)
    return {key: (x - min_x + 40, y - min_y + 40) for key, (x, y) in positions.items()}


def node_style(node: Node) -> str:
    base = [
        "whiteSpace=wrap",
        "html=1",
        "rounded=1",
        "strokeWidth=2",
        "fontSize=13",
        "fontFamily=Helvetica",
    ]
    if node.shape == "rhombus":
        base.append("shape=rhombus")
        base.append("fillColor=#fff2cc")
        base.append("strokeColor=#d6b656")
    elif node.shape == "ellipse":
        base.append("ellipse")
        base.append("fillColor=#dae8fc")
        base.append("strokeColor=#6c8ebf")
    elif node.shape == "cylinder":
        base.append("shape=cylinder3d")
        base.append("fillColor=#e1d5e7")
        base.append("strokeColor=#9673a6")
    elif node.shape == "rounded":
        base.append("fillColor=#d5e8d4")
        base.append("strokeColor=#82b366")
    else:
        base.append("fillColor=#f8f9fa")
        base.append("strokeColor=#666666")
    return ";".join(base) + ";"


def wrap_for_xml(label: str, width: int = 18) -> str:
    lines: list[str] = []
    for part in label.splitlines() or [""]:
        if len(part) <= width:
            lines.append(part)
            continue
        current = ""
        for char in part:
            current += char
            if len(current) >= width:
                lines.append(current)
                current = ""
        if current:
            lines.append(current)
    return "\n".join(lines)


def diagram_to_mxfile(diagram: Diagram) -> str:
    positions = layout(diagram)
    max_x = max((x for x, _ in positions.values()), default=800) + 240
    max_y = max((y for _, y in positions.values()), default=600) + 160

    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "agent": "oto-codex",
            "version": "26.0.0",
        },
    )
    diagram_el = ET.SubElement(mxfile, "diagram", {"id": slugify(diagram.title), "name": diagram.title})
    model = ET.SubElement(
        diagram_el,
        "mxGraphModel",
        {
            "dx": str(max(1000, max_x)),
            "dy": str(max(700, max_y)),
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(max(1160, max_x)),
            "pageHeight": str(max(820, max_y)),
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    node_ids: dict[str, str] = {}
    for idx, (key, node) in enumerate(diagram.nodes.items(), start=2):
        cell_id = f"n{idx}"
        node_ids[key] = cell_id
        label = wrap_for_xml(node.label or key)
        x, y = positions[key]
        width = min(230, max(150, 24 + min(18, max(map(len, label.splitlines() or [""]))) * 10))
        height = max(60, 34 + 18 * max(1, len(label.splitlines())))
        if node.shape == "rhombus":
            width = max(width, 170)
            height = max(height, 86)
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": cell_id,
                "value": label,
                "style": node_style(node),
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {"x": str(x), "y": str(y), "width": str(width), "height": str(height), "as": "geometry"},
        )

    edge_style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
        "jettySize=auto;html=1;strokeWidth=2;endArrow=block;endFill=1;"
    )
    for idx, edge in enumerate(diagram.edges, start=1):
        if edge.src not in node_ids or edge.dst not in node_ids:
            continue
        style = edge_style
        if edge.dashed:
            style += "dashed=1;"
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": f"e{idx}",
                "value": wrap_for_xml(edge.label, 14),
                "style": style,
                "edge": "1",
                "parent": "1",
                "source": node_ids[edge.src],
                "target": node_ids[edge.dst],
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    return ET.tostring(mxfile, encoding="unicode")


def viewer_url(mxfile_xml: str, title: str) -> str:
    quoted = urllib.parse.quote(mxfile_xml, safe="~()*!.'")
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(quoted.encode("utf-8")) + compressor.flush()
    payload = base64.b64encode(compressed).decode("ascii")
    params = urllib.parse.urlencode(
        {
            "highlight": "0000ff",
            "edit": "_blank",
            "layers": "1",
            "nav": "1",
            "title": title,
        },
        quote_via=urllib.parse.quote,
    )
    return f"https://viewer.diagrams.net/?{params}#R{payload}"


def mermaid_blocks(page_id: str) -> list[dict]:
    rows = []
    last_heading = {"text": "", "id": page_id}
    for index, block in enumerate(children(page_id), start=1):
        block_type = block.get("type")
        if block_type in {"heading_1", "heading_2", "heading_3"}:
            last_heading = {
                "text": rich_text((block.get(block_type) or {}).get("rich_text")),
                "id": block.get("id"),
            }
        if block_type == "code":
            code = block.get("code") or {}
            body = rich_text(code.get("rich_text"))
            if code.get("language") == "mermaid":
                rows.append(
                    {
                        "index": index,
                        "id": block.get("id"),
                        "heading": last_heading["text"],
                        "heading_id": last_heading["id"],
                        "source": body,
                    }
                )
    return rows


def local_mermaid_blocks(page_id: str) -> list[dict]:
    embeds = diagrams_net_embeds(page_id)
    sources = sorted(OUT_DIR.glob("*.mmd"))
    rows = []
    for index, path in enumerate(sources, start=1):
        heading = embeds[index - 1]["heading"] if index <= len(embeds) else path.stem.split("-", 1)[-1]
        rows.append(
            {
                "index": index,
                "id": "",
                "heading": heading,
                "heading_id": embeds[index - 1]["heading_id"] if index <= len(embeds) else page_id,
                "source": path.read_text(encoding="utf-8"),
            }
        )
    return rows


def diagrams_net_embeds(page_id: str) -> list[dict]:
    rows = []
    last_heading = {"text": "", "id": page_id}
    for index, block in enumerate(children(page_id), start=1):
        block_type = block.get("type")
        if block_type in {"heading_1", "heading_2", "heading_3"}:
            last_heading = {
                "text": rich_text((block.get(block_type) or {}).get("rich_text")),
                "id": block.get("id"),
            }
        if block_type == "embed":
            url = (block.get("embed") or {}).get("url") or ""
            if "viewer.diagrams.net" in url:
                rows.append(
                    {
                        "index": index,
                        "id": block.get("id"),
                        "heading": last_heading["text"],
                        "heading_id": last_heading["id"],
                        "url": url,
                    }
                )
    return rows


def embed_block(url: str) -> dict:
    return {"object": "block", "type": "embed", "embed": {"url": url}}


def paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def append_after(parent_id: str, after_id: str, blocks: list[dict]) -> None:
    notion_request(
        "PATCH",
        f"/blocks/{parent_id}/children",
        {"after": after_id, "children": blocks},
    )


def archive_block(block_id: str) -> None:
    notion_request("PATCH", f"/blocks/{block_id}", {"archived": True})


def update_embed(block_id: str, url: str) -> None:
    notion_request("PATCH", f"/blocks/{block_id}", {"embed": {"url": url}})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("page_id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--update-existing", action="store_true")
    args = parser.parse_args()

    load_local_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    source_items = mermaid_blocks(args.page_id)
    if not source_items and args.update_existing:
        source_items = local_mermaid_blocks(args.page_id)

    for order, item in enumerate(source_items, start=1):
        title = item["heading"] or f"Flow Diagram {order}"
        slug = f"{order:02d}-{slugify(title)}"
        diagram = parse_mermaid(title, item["source"])
        mxfile = diagram_to_mxfile(diagram)
        url = viewer_url(mxfile, title)
        (OUT_DIR / f"{slug}.mmd").write_text(item["source"], encoding="utf-8")
        (OUT_DIR / f"{slug}.drawio").write_text(mxfile, encoding="utf-8")
        manifest.append(
            {
                "order": order,
                "title": title,
                "source_block_id": item["id"],
                "heading_block_id": item["heading_id"],
                "drawio": str(OUT_DIR / f"{slug}.drawio"),
                "mermaid_source": str(OUT_DIR / f"{slug}.mmd"),
                "node_count": len(diagram.nodes),
                "edge_count": len(diagram.edges),
                "embed_url": url,
                "embed_url_length": len(url),
            }
        )
        if args.apply:
            if not item["id"]:
                raise SystemExit("Cannot --apply from local source without active Notion code blocks")
            append_after(
                args.page_id,
                item["heading_id"],
                [
                    paragraph("diagrams.net版（全画面表示・編集リンク対応）"),
                    embed_block(url),
                ],
            )
            archive_block(item["id"])

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.update_existing:
        embeds_by_heading = {item["heading"]: item for item in diagrams_net_embeds(args.page_id)}
        updated = 0
        for item in manifest:
            embed = embeds_by_heading.get(item["title"])
            if not embed:
                continue
            update_embed(embed["id"], item["embed_url"])
            updated += 1
        print(json.dumps({"count": len(manifest), "updated": updated, "out": str(OUT_DIR)}, ensure_ascii=False))
        return
    print(json.dumps({"count": len(manifest), "applied": args.apply, "out": str(OUT_DIR)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
