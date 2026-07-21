#!/usr/bin/env python3
"""Build a reusable local keyboard-first review UI for JSON rows."""

import argparse
import html
import json
from pathlib import Path


DEFAULT_DECISIONS = ["採用", "不採用", "まとめ", "保留"]
DEFAULT_COLORS = ["accept", "reject", "merge", "hold", "extra1", "extra2"]


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def get_path(obj, dotted, default=None):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def rows_from_input(path, rows_key):
    data = load_json(path)
    rows = get_path(data, rows_key, data) if rows_key else data
    if not isinstance(rows, list):
        raise ValueError(f"rows-key did not resolve to a list: {rows_key}")
    return rows


def tuple_for(row, fields):
    return tuple(str(get_path(row, field, "")) for field in fields)


def load_decisions(path, key_fields):
    if not path:
        return {}
    data = load_json(path)
    rows = data.get("rows", data if isinstance(data, list) else [])
    return {
        tuple_for(row, key_fields): {
            "decision": row.get("decision", ""),
            "note": row.get("note", ""),
        }
        for row in rows
        if isinstance(row, dict) and row.get("decision")
    }


def field_list(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def sources_for(row, source_field):
    if not source_field:
        return []
    raw = get_path(row, source_field, []) or []
    if not isinstance(raw, list):
        raw = [raw]
    sources = []
    for item in raw:
        if isinstance(item, dict):
            sources.append(
                {
                    "text": str(item.get("text", "") or ""),
                    "account": str(item.get("account", "") or ""),
                    "date": str(item.get("date", "") or ""),
                    "url": str(item.get("url", "") or ""),
                }
            )
        else:
            sources.append({"text": str(item), "account": "", "date": "", "url": ""})
    return sources


def normalize_rows(rows, args):
    key_fields = field_list(args.key_fields)
    category_field = args.category_field
    term_field = args.term_field
    summary_fields = field_list(args.summary_fields)
    detail_fields = field_list(args.detail_fields)

    normalized = []
    seen = set()
    decisions = load_decisions(args.decisions, key_fields)
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            row = {"value": row}
        row_key = tuple_for(row, key_fields) if key_fields else (str(index),)
        if args.exclude_decided and row_key in decisions:
            continue
        if row_key in seen:
            row_key = (*row_key, str(index))
        seen.add(row_key)
        normalized.append(
            {
                "_key": "||".join(row_key),
                "term": str(get_path(row, term_field, f"row {index}") or f"row {index}"),
                "category": str(get_path(row, category_field, "未分類") or "未分類"),
                "summary": [
                    {"label": field, "value": str(get_path(row, field, "") or "")}
                    for field in summary_fields
                ],
                "details": [
                    {"label": field, "value": str(get_path(row, field, "") or "")}
                    for field in detail_fields
                ],
                "sources": sources_for(row, args.source_field),
                "preloaded": decisions.get(row_key, {}),
            }
        )
    normalized.sort(key=lambda item: (item["category"], item["term"], item["_key"]))
    return normalized


def js_string(value):
    return json.dumps(value, ensure_ascii=False)


def write_html(rows, args):
    title = html.escape(args.title)
    data = json.dumps(rows, ensure_ascii=False)
    decisions = json.dumps(field_list(args.decisions_labels), ensure_ascii=False)
    body = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #fff;
      --text: #20242a;
      --muted: #667085;
      --line: #d8dee8;
      --accent: #0f766e;
      --danger: #b42318;
      --warn: #a15c07;
      --hold: #475467;
      --blue: #2563eb;
      --purple: #7c3aed;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(247, 248, 250, .96);
      border-bottom: 1px solid var(--line);
      padding: 14px 20px;
      backdrop-filter: blur(8px);
    }}
    h1 {{ margin: 0 0 8px; font-size: 20px; letter-spacing: 0; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    .summary {{ color: var(--muted); font-size: 14px; margin-right: auto; }}
    button {{
      border: 1px solid var(--line);
      background: white;
      border-radius: 6px;
      padding: 7px 10px;
      font-size: 14px;
      cursor: pointer;
    }}
    button.primary {{ border-color: var(--accent); background: var(--accent); color: white; }}
    main {{ padding: 18px 20px 40px; max-width: 1200px; margin: 0 auto; }}
    .filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }}
    .filter {{
      border: 1px solid var(--line);
      background: white;
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      cursor: pointer;
      font-size: 13px;
    }}
    .filter.active {{ border-color: var(--accent); color: var(--accent); font-weight: 700; }}
    section {{ margin: 20px 0; }}
    h2 {{ font-size: 16px; margin: 0 0 10px; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      margin: 10px 0;
    }}
    .card.active {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15,118,110,.14); }}
    .row-head {{
      display: grid;
      grid-template-columns: minmax(130px, 220px) minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
    }}
    .term {{ font-size: 17px; font-weight: 800; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .interpretation {{ font-size: 14px; }}
    .choices {{ display: grid; grid-template-columns: repeat(var(--choice-count), 86px); gap: 6px; }}
    .choice {{
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font-size: 13px;
      cursor: pointer;
      user-select: none;
      background: white;
    }}
    .choice input {{ display: none; }}
    .choice:has(input:checked) {{ color: white; font-weight: 700; }}
    .choice.accept:has(input:checked) {{ background: var(--accent); border-color: var(--accent); }}
    .choice.reject:has(input:checked) {{ background: var(--danger); border-color: var(--danger); }}
    .choice.merge:has(input:checked) {{ background: var(--warn); border-color: var(--warn); }}
    .choice.hold:has(input:checked) {{ background: var(--hold); border-color: var(--hold); }}
    .choice.extra1:has(input:checked) {{ background: var(--blue); border-color: var(--blue); }}
    .choice.extra2:has(input:checked) {{ background: var(--purple); border-color: var(--purple); }}
    details {{ margin-top: 10px; color: var(--muted); font-size: 13px; }}
    details p {{ margin: 8px 0; color: var(--text); white-space: pre-wrap; }}
    .source {{
      border-left: 3px solid var(--line);
      padding: 6px 10px;
      margin: 8px 0;
      background: var(--bg);
      border-radius: 0 6px 6px 0;
    }}
    .source-meta {{ color: var(--muted); font-size: 12px; margin-bottom: 2px; }}
    .source-text {{ color: var(--text); font-size: 13px; white-space: pre-wrap; }}
    .note {{
      margin-top: 10px;
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      font: inherit;
      resize: vertical;
    }}
    .help {{ color: var(--muted); font-size: 13px; width: 100%; }}
    kbd {{
      border: 1px solid var(--line);
      border-bottom-width: 2px;
      border-radius: 4px;
      background: white;
      padding: 1px 5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }}
    a {{ color: var(--accent); }}
    @media (max-width: 760px) {{
      .row-head {{ grid-template-columns: 1fr; }}
      .choices {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div class="toolbar">
      <div class="summary" id="summary"></div>
      <button type="button" id="showUnreviewed">未判定だけ</button>
      <button type="button" id="showAll">全部表示</button>
      <button type="button" class="primary" id="exportJson">結果JSONをダウンロード</button>
      <div class="help">
        <kbd>j</kbd>/<kbd>k</kbd> 移動　
        <kbd>1</kbd>-<kbd>9</kbd> 判定　
        <kbd>n</kbd> メモ
        <kbd>s</kbd> ソース
        <kbd>u</kbd> 未判定表示　
        <kbd>a</kbd> 全部表示　
        <kbd>e</kbd> 書き出し
      </div>
    </div>
  </header>
  <main>
    <div class="filters" id="filters"></div>
    <div id="app"></div>
  </main>
  <script>
    const TERMS = {data};
    const DECISIONS = {decisions};
    const STORAGE_KEY = {js_string(args.storage_key)};
    const DOWNLOAD_NAME = {js_string(args.download_name)};
    const COLORS = {json.dumps(DEFAULT_COLORS)};
    let categoryFilter = "all";
    let onlyUnreviewed = false;
    let activeIndex = 0;

    function loadState() {{
      try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {{}}; }}
      catch {{ return {{}}; }}
    }}
    function saveState(state) {{
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      renderSummary();
    }}
    function loadInitialState() {{
      const state = loadState();
      let changed = false;
      for (const row of TERMS) {{
        if (row.preloaded && row.preloaded.decision && (!state[row._key] || !state[row._key].decision)) {{
          state[row._key] = row.preloaded;
          changed = true;
        }}
      }}
      if (changed) saveState(state);
    }}
    function groupedRows() {{
      const rows = TERMS.filter(row => categoryFilter === "all" || row.category === categoryFilter);
      const state = loadState();
      const filtered = onlyUnreviewed ? rows.filter(row => !(state[row._key] || {{}}).decision) : rows;
      return Object.groupBy(filtered, row => row.category);
    }}
    function renderFilters() {{
      const categories = ["all", ...new Set(TERMS.map(row => row.category))];
      document.getElementById("filters").innerHTML = categories.map(cat => (
        `<button class="filter ${{categoryFilter === cat ? "active" : ""}}" data-cat="${{escapeHtml(cat)}}">${{escapeHtml(cat === "all" ? "全部" : cat)}}</button>`
      )).join("");
      document.querySelectorAll(".filter").forEach(btn => {{
        btn.addEventListener("click", () => {{ categoryFilter = btn.dataset.cat; activeIndex = 0; render(); }});
      }});
    }}
    function renderSummary() {{
      const state = loadState();
      const counts = Object.fromEntries(DECISIONS.map(d => [d, 0]));
      let done = 0;
      for (const row of TERMS) {{
        const decision = (state[row._key] || {{}}).decision;
        if (decision) {{
          done++;
          counts[decision] = (counts[decision] || 0) + 1;
        }}
      }}
      const parts = DECISIONS.map(d => `${{d}} ${{counts[d] || 0}}`).join(" / ");
      document.getElementById("summary").textContent = `判定 ${{done}} / ${{TERMS.length}}　${{parts}}`;
    }}
    function render() {{
      renderFilters();
      renderSummary();
      document.documentElement.style.setProperty("--choice-count", Math.min(DECISIONS.length, 4));
      const state = loadState();
      const groups = groupedRows();
      const flatRows = Object.values(groups).flat();
      if (activeIndex >= flatRows.length) activeIndex = Math.max(0, flatRows.length - 1);
      const app = document.getElementById("app");
      app.innerHTML = Object.entries(groups).map(([category, rows]) => `
        <section>
          <h2>${{escapeHtml(category)}}（${{rows.length}}件）</h2>
          ${{rows.map(row => cardHtml(row, state[row._key] || {{}}, flatRows.indexOf(row))).join("")}}
        </section>
      `).join("") || "<p>表示する未判定はありません。</p>";
      app.querySelectorAll("input[type=radio]").forEach(input => {{
        input.addEventListener("change", event => {{
          const state = loadState();
          const key = event.target.dataset.key;
          state[key] = state[key] || {{}};
          state[key].decision = event.target.value;
          saveState(state);
        }});
      }});
      app.querySelectorAll("textarea").forEach(textarea => {{
        textarea.addEventListener("input", event => {{
          const state = loadState();
          const key = event.target.dataset.key;
          state[key] = state[key] || {{}};
          state[key].note = event.target.value;
          saveState(state);
        }});
      }});
      markActive(false);
    }}
    function cardHtml(row, saved, index) {{
      const decision = saved.decision || "";
      const note = saved.note || "";
      const summary = row.summary.filter(item => item.value).map(item => `<div><strong>${{escapeHtml(item.label)}}:</strong> ${{escapeHtml(item.value)}}</div>`).join("");
      const details = row.details.filter(item => item.value).map(item => `<p><strong>${{escapeHtml(item.label)}}:</strong> ${{escapeHtml(item.value)}}</p>`).join("");
      const sources = (row.sources || []).map(src => `
        <div class="source">
          <div class="source-meta">
            ${{escapeHtml(src.account)}}　${{escapeHtml((src.date || "").slice(0, 10))}}
            ${{src.url ? `　<a href="${{escapeAttr(src.url)}}" target="_blank" rel="noopener">元ポストを開く ↗</a>` : ""}}
          </div>
          <div class="source-text">${{escapeHtml(src.text)}}</div>
        </div>
      `).join("");
      const sourcesBlock = sources ? `
          <details class="sources">
            <summary>ソース（${{row.sources.length}}件）</summary>
            ${{sources}}
          </details>` : "";
      return `
        <article class="card" data-index="${{index}}" data-key="${{escapeAttr(row._key)}}">
          <div class="row-head">
            <div>
              <div class="term">${{escapeHtml(row.term)}}</div>
              <div class="meta">${{escapeHtml(row.category)}}</div>
            </div>
            <div class="interpretation">${{summary}}</div>
            <div class="choices">
              ${{DECISIONS.map((label, i) => choiceHtml(row._key, label, COLORS[i] || "extra2", decision)).join("")}}
            </div>
          </div>
          <textarea class="note" data-key="${{escapeHtml(row._key)}}" placeholder="メモ、代表語、まとめ先など">${{escapeHtml(note)}}</textarea>
          ${{sourcesBlock}}
          ${{details ? `<details><summary>詳細</summary>${{details}}</details>` : ""}}
        </article>
      `;
    }}
    function choiceHtml(key, label, klass, decision) {{
      return `<label class="choice ${{klass}}"><input type="radio" name="${{escapeAttr(key)}}" data-key="${{escapeAttr(key)}}" value="${{escapeAttr(label)}}" ${{decision === label ? "checked" : ""}}>${{escapeHtml(label)}}</label>`;
    }}
    function visibleCards() {{ return [...document.querySelectorAll(".card")]; }}
    function markActive(scroll = true) {{
      const cards = visibleCards();
      cards.forEach(card => card.classList.remove("active"));
      if (!cards.length) return;
      activeIndex = Math.max(0, Math.min(activeIndex, cards.length - 1));
      const card = cards[activeIndex];
      card.classList.add("active");
      if (scroll) card.scrollIntoView({{ block: "center", behavior: "smooth" }});
    }}
    function moveActive(delta) {{
      const cards = visibleCards();
      if (!cards.length) return;
      activeIndex = Math.max(0, Math.min(activeIndex + delta, cards.length - 1));
      markActive(true);
    }}
    function setDecisionForActive(decision) {{
      const cards = visibleCards();
      const card = cards[activeIndex];
      if (!card) return;
      const key = card.dataset.key;
      const input = card.querySelector(`input[value="${{cssEscape(decision)}}"]`);
      if (input) input.checked = true;
      const state = loadState();
      state[key] = state[key] || {{}};
      state[key].decision = decision;
      saveState(state);
      if (onlyUnreviewed) render(); else moveActive(1);
    }}
    function focusNoteForActive() {{
      const card = visibleCards()[activeIndex];
      const note = card && card.querySelector("textarea");
      if (note) note.focus();
    }}
    function toggleSourcesForActive() {{
      const card = visibleCards()[activeIndex];
      const sources = card && card.querySelector("details.sources");
      if (sources) sources.open = !sources.open;
    }}
    function exportResults() {{
      const state = loadState();
      const rows = TERMS.map(row => ({{
        key: row._key,
        term: row.term,
        category: row.category,
        decision: (state[row._key] || {{}}).decision || "",
        note: (state[row._key] || {{}}).note || ""
      }}));
      const output = {{ exported_at: new Date().toISOString(), total: rows.length, rows }};
      const blob = new Blob([JSON.stringify(output, null, 2)], {{ type: "application/json" }});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = DOWNLOAD_NAME;
      a.click();
      URL.revokeObjectURL(a.href);
    }}
    function cssEscape(value) {{
      return String(value).replace(/["\\\\]/g, "\\\\$&");
    }}
    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, ch => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[ch]));
    }}
    function escapeAttr(value) {{ return escapeHtml(value).replace(/`/g, "&#96;"); }}
    document.getElementById("exportJson").addEventListener("click", exportResults);
    document.getElementById("showUnreviewed").addEventListener("click", () => {{ onlyUnreviewed = true; activeIndex = 0; render(); }});
    document.getElementById("showAll").addEventListener("click", () => {{ onlyUnreviewed = false; activeIndex = 0; render(); }});
    document.addEventListener("keydown", event => {{
      const target = event.target;
      const typing = target && ["TEXTAREA", "INPUT"].includes(target.tagName);
      if (typing && event.key !== "Escape") return;
      if (event.key === "Escape" && typing) {{ target.blur(); event.preventDefault(); return; }}
      const number = Number(event.key);
      if (number >= 1 && number <= DECISIONS.length) {{
        event.preventDefault();
        setDecisionForActive(DECISIONS[number - 1]);
        return;
      }}
      const actions = {{
        "j": () => moveActive(1),
        "ArrowDown": () => moveActive(1),
        "k": () => moveActive(-1),
        "ArrowUp": () => moveActive(-1),
        "n": () => focusNoteForActive(),
        "s": () => toggleSourcesForActive(),
        "u": () => {{ onlyUnreviewed = true; activeIndex = 0; render(); }},
        "a": () => {{ onlyUnreviewed = false; activeIndex = 0; render(); }},
        "e": () => exportResults()
      }};
      const action = actions[event.key];
      if (action) {{ event.preventDefault(); action(); }}
    }});
    loadInitialState();
    render();
  </script>
</body>
</html>
"""
    args.out.write_text(body, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--rows-key", default="")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", default="キーボード判定レビュー")
    parser.add_argument("--term-field", default="term")
    parser.add_argument("--category-field", default="category")
    parser.add_argument("--summary-fields", default="interpretation,type,confidence,source_agent")
    parser.add_argument("--detail-fields", default="reason,evidence_text,evidence_url")
    parser.add_argument(
        "--source-field",
        default="",
        help="list-of-dict field (text/account/date/url) rendered as source blocks, e.g. evidence",
    )
    parser.add_argument("--key-fields", default="term,category,type,evidence_url")
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--exclude-decided", action="store_true")
    parser.add_argument("--decisions-labels", default="採用,不採用,まとめ,保留")
    parser.add_argument("--download-name", default="review_decisions.json")
    parser.add_argument("--storage-key", default="keyboard-review-ui-v1")
    args = parser.parse_args()

    rows = rows_from_input(args.input, args.rows_key)
    normalized = normalize_rows(rows, args)
    write_html(normalized, args)
    print(f"wrote {args.out} ({len(normalized)} rows)")


if __name__ == "__main__":
    main()
