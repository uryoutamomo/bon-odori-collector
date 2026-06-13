#!/usr/bin/env python3
"""Build a local checklist UI for glossary v2 review."""

import argparse
import html
import json
from pathlib import Path

from merge_glossary_v2_oto_reports import FIRST_REVIEW_TERMS, load_rows


OUT = Path("data/glossary_v2_oto123_review_ui.html")


def selected_rows(mode, decisions_path=None):
    rows = load_rows()
    if mode == "first":
        rows = [row for row in rows if row["term"] in FIRST_REVIEW_TERMS]
    elif mode == "unreviewed":
        reviewed = reviewed_tuples(decisions_path)
        rows = [row for row in rows if tuple_for(row) not in reviewed]
    rows.sort(
        key=lambda row: (
            row["category"],
            row["review_priority"],
            row["term"],
        )
    )
    return rows


def tuple_for(row):
    return (
        row.get("term", ""),
        row.get("category", ""),
        row.get("type", ""),
        row.get("evidence_url", ""),
    )


def key_for(row):
    return f"{row.get('category', '')}::{row.get('term', '')}::{row.get('source_file', '')}::{row.get('source_index', '')}"


def reviewed_tuples(decisions_path):
    if not decisions_path:
        return set()
    with decisions_path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {tuple_for(row) for row in data.get("rows", []) if row.get("decision")}


def load_preloaded_decisions(rows, decisions_path):
    if not decisions_path:
        return {}
    with decisions_path.open(encoding="utf-8") as f:
        data = json.load(f)
    by_tuple = {tuple_for(row): row for row in data.get("rows", [])}
    preloaded = {}
    for row in rows:
        decision = by_tuple.get(tuple_for(row))
        if not decision:
            continue
        preloaded[key_for(row)] = {
            "decision": decision.get("decision", ""),
            "note": decision.get("note", ""),
        }
    return preloaded


def write_html(rows, preloaded, title, storage_key, download_name, out_path):
    data = json.dumps(rows, ensure_ascii=False)
    preloaded_data = json.dumps(preloaded, ensure_ascii=False)
    escaped_title = html.escape(title)
    body = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #20242a;
      --muted: #667085;
      --line: #d8dee8;
      --accent: #0f766e;
      --danger: #b42318;
      --warn: #a15c07;
      --hold: #475467;
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
      background: rgba(247, 248, 250, 0.96);
      border-bottom: 1px solid var(--line);
      padding: 14px 20px;
      backdrop-filter: blur(8px);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 20px;
      letter-spacing: 0;
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .summary {{
      color: var(--muted);
      font-size: 14px;
      margin-right: auto;
    }}
    button {{
      border: 1px solid var(--line);
      background: white;
      border-radius: 6px;
      padding: 7px 10px;
      font-size: 14px;
      cursor: pointer;
    }}
    button.primary {{
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }}
    main {{
      padding: 18px 20px 40px;
      max-width: 1200px;
      margin: 0 auto;
    }}
    .filters {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .filter {{
      border: 1px solid var(--line);
      background: white;
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      cursor: pointer;
      font-size: 13px;
    }}
    .filter.active {{
      border-color: var(--accent);
      color: var(--accent);
      font-weight: 700;
    }}
    section {{
      margin: 20px 0;
    }}
    h2 {{
      font-size: 16px;
      margin: 0 0 10px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      margin: 10px 0;
    }}
    .card.active {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.14);
    }}
    .row-head {{
      display: grid;
      grid-template-columns: minmax(130px, 220px) minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
    }}
    .term {{
      font-size: 17px;
      font-weight: 800;
    }}
    .meta {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }}
    .interpretation {{
      font-size: 14px;
    }}
    .choices {{
      display: grid;
      grid-template-columns: repeat(4, 86px);
      gap: 6px;
    }}
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
    .choice:has(input:checked) {{
      color: white;
      font-weight: 700;
    }}
    .choice.accept:has(input:checked) {{ background: var(--accent); border-color: var(--accent); }}
    .choice.reject:has(input:checked) {{ background: var(--danger); border-color: var(--danger); }}
    .choice.merge:has(input:checked) {{ background: var(--warn); border-color: var(--warn); }}
    .choice.hold:has(input:checked) {{ background: var(--hold); border-color: var(--hold); }}
    details {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    details p {{
      margin: 8px 0;
      color: var(--text);
    }}
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
    .help {{
      color: var(--muted);
      font-size: 13px;
      width: 100%;
    }}
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
      .row-head {{
        grid-template-columns: 1fr;
      }}
      .choices {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escaped_title}</h1>
    <div class="toolbar">
      <div class="summary" id="summary"></div>
      <button type="button" id="showUnreviewed">未判定だけ</button>
      <button type="button" id="showAll">全部表示</button>
      <button type="button" class="primary" id="exportJson">結果JSONをダウンロード</button>
      <div class="help">
        <kbd>j</kbd>/<kbd>k</kbd> 移動　
        <kbd>1</kbd> 採用　
        <kbd>2</kbd> 不採用　
        <kbd>3</kbd> まとめ　
        <kbd>4</kbd> 保留　
        <kbd>n</kbd> メモ　
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
    const STORAGE_KEY = "{storage_key}";
    const DOWNLOAD_NAME = "{download_name}";
    const PRELOADED = {preloaded_data};
    const decisions = ["採用", "不採用", "まとめ", "保留"];
    let categoryFilter = "all";
    let onlyUnreviewed = false;
    let activeIndex = 0;

    function loadState() {{
      try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {{}}; }}
      catch {{ return {{}}; }}
    }}
    function loadInitialState() {{
      const state = loadState();
      let changed = false;
      for (const [key, value] of Object.entries(PRELOADED)) {{
        if (!state[key] || !state[key].decision) {{
          state[key] = value;
          changed = true;
        }}
      }}
      if (changed) saveState(state);
    }}
    function saveState(state) {{
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      renderSummary();
    }}
    function keyFor(row) {{
      return `${{row.category}}::${{row.term}}::${{row.source_file}}::${{row.source_index}}`;
    }}
    function groupedRows() {{
      const rows = TERMS.filter(row => categoryFilter === "all" || row.category === categoryFilter);
      const state = loadState();
      const filtered = onlyUnreviewed ? rows.filter(row => !(state[keyFor(row)] || {{}}).decision) : rows;
      return Object.groupBy(filtered, row => row.category);
    }}
    function renderFilters() {{
      const categories = ["all", ...new Set(TERMS.map(row => row.category))];
      const labels = {{ all: "全部" }};
      document.getElementById("filters").innerHTML = categories.map(cat => (
        `<button class="filter ${{categoryFilter === cat ? "active" : ""}}" data-cat="${{escapeHtml(cat)}}">${{escapeHtml(labels[cat] || cat)}}</button>`
      )).join("");
      document.querySelectorAll(".filter").forEach(btn => {{
        btn.addEventListener("click", () => {{
          categoryFilter = btn.dataset.cat;
          render();
        }});
      }});
    }}
    function renderSummary() {{
      const state = loadState();
      const counts = Object.fromEntries(decisions.map(d => [d, 0]));
      let done = 0;
      for (const row of TERMS) {{
        const decision = (state[keyFor(row)] || {{}}).decision;
        if (decision) {{
          done++;
          counts[decision] = (counts[decision] || 0) + 1;
        }}
      }}
      document.getElementById("summary").textContent =
        `判定 ${{done}} / ${{TERMS.length}}　採用 ${{counts["採用"]}} / 不採用 ${{counts["不採用"]}} / まとめ ${{counts["まとめ"]}} / 保留 ${{counts["保留"]}}`;
    }}
    function render() {{
      renderFilters();
      renderSummary();
      const state = loadState();
      const groups = groupedRows();
      const flatRows = Object.values(groups).flat();
      if (activeIndex >= flatRows.length) activeIndex = Math.max(0, flatRows.length - 1);
      const app = document.getElementById("app");
      app.innerHTML = Object.entries(groups).map(([category, rows]) => `
        <section>
          <h2>${{escapeHtml(category)}}（${{rows.length}}件）</h2>
          ${{rows.map(row => cardHtml(row, state[keyFor(row)] || {{}}, flatRows.indexOf(row))).join("")}}
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
      const key = keyFor(row);
      const decision = saved.decision || "";
      const note = saved.note || "";
      return `
        <article class="card" data-index="${{index}}" data-key="${{escapeAttr(key)}}">
          <div class="row-head">
            <div>
              <div class="term">${{escapeHtml(row.term)}}</div>
              <div class="meta">${{escapeHtml(row.confidence)}} / ${{escapeHtml(row.type)}} / ${{escapeHtml(row.source_agent)}}</div>
            </div>
            <div class="interpretation">${{escapeHtml(row.interpretation)}}</div>
            <div class="choices">
              ${{choiceHtml(key, "採用", "accept", decision)}}
              ${{choiceHtml(key, "不採用", "reject", decision)}}
              ${{choiceHtml(key, "まとめ", "merge", decision)}}
              ${{choiceHtml(key, "保留", "hold", decision)}}
            </div>
          </div>
          <textarea class="note" data-key="${{escapeHtml(key)}}" placeholder="メモ、代表語、まとめ先など">${{escapeHtml(note)}}</textarea>
          <details>
            <summary>証拠と理由</summary>
            <p><strong>理由:</strong> ${{escapeHtml(row.reason)}}</p>
            <p><strong>証拠:</strong> ${{escapeHtml(row.evidence_text)}}</p>
            <p><a href="${{escapeAttr(row.evidence_url)}}" target="_blank" rel="noreferrer">証拠URLを開く</a></p>
          </details>
        </article>
      `;
    }}
    function choiceHtml(key, label, klass, decision) {{
      return `<label class="choice ${{klass}}"><input type="radio" name="${{escapeAttr(key)}}" data-key="${{escapeAttr(key)}}" value="${{label}}" ${{decision === label ? "checked" : ""}}>${{label}}</label>`;
    }}
    function visibleCards() {{
      return [...document.querySelectorAll(".card")];
    }}
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
      const input = card.querySelector(`input[value="${{decision}}"]`);
      if (input) input.checked = true;
      const state = loadState();
      state[key] = state[key] || {{}};
      state[key].decision = decision;
      saveState(state);
      if (onlyUnreviewed) {{
        render();
      }} else {{
        moveActive(1);
      }}
    }}
    function focusNoteForActive() {{
      const cards = visibleCards();
      const card = cards[activeIndex];
      const note = card && card.querySelector("textarea");
      if (note) note.focus();
    }}
    function exportResults() {{
      const state = loadState();
      const rows = TERMS.map(row => ({{
        term: row.term,
        category: row.category,
        type: row.type,
        confidence: row.confidence,
        interpretation: row.interpretation,
        evidence_url: row.evidence_url,
        decision: (state[keyFor(row)] || {{}}).decision || "",
        note: (state[keyFor(row)] || {{}}).note || ""
      }}));
      const output = {{
        exported_at: new Date().toISOString(),
        total: rows.length,
        rows
      }};
      const blob = new Blob([JSON.stringify(output, null, 2)], {{ type: "application/json" }});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = DOWNLOAD_NAME;
      a.click();
      URL.revokeObjectURL(a.href);
    }}
    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, ch => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[ch]));
    }}
    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, "&#96;");
    }}
    document.getElementById("exportJson").addEventListener("click", exportResults);
    document.getElementById("showUnreviewed").addEventListener("click", () => {{ onlyUnreviewed = true; render(); }});
    document.getElementById("showAll").addEventListener("click", () => {{ onlyUnreviewed = false; render(); }});
    document.addEventListener("keydown", event => {{
      const target = event.target;
      const typing = target && ["TEXTAREA", "INPUT"].includes(target.tagName);
      if (typing && event.key !== "Escape") return;
      if (event.key === "Escape" && typing) {{
        target.blur();
        event.preventDefault();
        return;
      }}
      const actions = {{
        "j": () => moveActive(1),
        "ArrowDown": () => moveActive(1),
        "k": () => moveActive(-1),
        "ArrowUp": () => moveActive(-1),
        "1": () => setDecisionForActive("採用"),
        "2": () => setDecisionForActive("不採用"),
        "3": () => setDecisionForActive("まとめ"),
        "4": () => setDecisionForActive("保留"),
        "n": () => focusNoteForActive(),
        "u": () => {{ onlyUnreviewed = true; activeIndex = 0; render(); }},
        "a": () => {{ onlyUnreviewed = false; activeIndex = 0; render(); }},
        "e": () => exportResults()
      }};
      const action = actions[event.key];
      if (action) {{
        event.preventDefault();
        action();
      }}
    }});
    loadInitialState();
    render();
  </script>
</body>
</html>
"""
    out_path.write_text(body, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("first", "unreviewed", "all"),
        default="first",
        help="first: initial selected terms, unreviewed: exclude decided rows, all: every merged row",
    )
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    rows = selected_rows(args.mode, args.decisions)
    preloaded = {} if args.mode == "unreviewed" else load_preloaded_decisions(rows, args.decisions)
    if args.mode == "unreviewed":
        title = "用語集v2 未判定レビュー"
        storage_key = "glossary-v2-oto123-unreviewed-review-v1"
        download_name = "glossary_v2_oto123_unreviewed_decisions.json"
    elif args.mode == "all":
        title = "用語集v2 全候補レビュー"
        storage_key = "glossary-v2-oto123-all-review-v1"
        download_name = "glossary_v2_oto123_all_review_decisions.json"
    else:
        title = "用語集v2 第1レビュー"
        storage_key = "glossary-v2-oto123-review-v1"
        download_name = "glossary_v2_oto123_review_decisions.json"
    write_html(rows, preloaded, title, storage_key, download_name, args.out)
    print(f"wrote {args.out} ({len(rows)} terms, preloaded {len(preloaded)} decisions)")


if __name__ == "__main__":
    main()
