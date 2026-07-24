#!/usr/bin/env python3
"""Build a local review page for songs missing public content notes."""

import argparse
import html
import json
from pathlib import Path
from urllib.parse import quote_plus


DATA = Path("data")
DEFAULT_SITE_GLOSSARY = Path.home() / "bon-odori-site" / "data" / "glossary_public.json"
DEFAULT_YOUTUBE_MASTER = DATA / "youtube_song_master.json"
DEFAULT_OUT_JSON = DATA / "song_publication_review_candidates.json"
DEFAULT_OUT_HTML = DATA / "song_publication_review.html"
DEFAULT_DECISIONS = DATA / "song_publication_review_decisions.json"

CANONICAL_SONG_TERMS = {
    "000年音頭": "2000年音頭",
    "２０００年音頭": "2000年音頭",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_decisions(path):
    path = Path(path)
    if not path.exists():
        return {}, ""
    payload = read_json(path)
    rows = payload if isinstance(payload, list) else payload.get("rows", [])
    decisions = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        term = row.get("term") or row.get("key")
        if not term:
            continue
        decision = row.get("decision") or ""
        note = row.get("note") or ""
        if decision or note:
            decisions[str(term)] = {"decision": decision, "note": note}
    return decisions, str(path)


def song_category(item):
    return item.get("category_label") or item.get("category")


def canonical_song_term(value):
    value = str(value or "")
    return CANONICAL_SONG_TERMS.get(value, value)


def number(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def priority_for(item):
    score = number(item.get("bon_usage_score"))
    source_count = number(item.get("source_count"))
    rank = item.get("bon_usage_rank") or ""
    if rank in {"定番", "よく使われる"} or score >= 180 or source_count >= 60:
        return "P0"
    if rank == "ときどき使われる" or score >= 100 or source_count >= 20:
        return "P1"
    return "P2"


def youtube_search_url(term):
    return "https://www.youtube.com/results?search_query=" + quote_plus(f"{term} 盆踊り")


def build_candidates(glossary_path, youtube_master_path):
    glossary = read_json(glossary_path)
    master = read_json(youtube_master_path) if Path(youtube_master_path).exists() else {"songs": []}
    master_by_name = {row.get("song_name"): row for row in master.get("songs", []) if row.get("song_name")}
    terms_with_content_notes = {
        canonical_song_term(item.get("term"))
        for item in glossary.get("items", [])
        if song_category(item) == "曲名・踊り名" and item.get("term") and item.get("content_note")
    }

    candidates = []
    seen_terms = set()
    for item in glossary.get("items", []):
        if song_category(item) != "曲名・踊り名" or not item.get("term"):
            continue
        if item.get("content_note"):
            continue
        name = canonical_song_term(item["term"])
        if name in terms_with_content_notes or name in seen_terms:
            continue
        seen_terms.add(name)
        source = master_by_name.get(name, {})
        merged = {**item, **source}
        candidates.append({
            "priority": priority_for(merged),
            "term": name,
            "source_count": number(merged.get("source_count") or source.get("good_evidence_count")),
            "bon_usage_score": number(merged.get("bon_usage_score")),
            "bon_usage_rank": merged.get("bon_usage_rank") or "",
            "song_genre": merged.get("song_genre") or "",
            "genre_confidence": merged.get("genre_confidence") or "",
            "genre_basis": merged.get("genre_basis") or "",
            "description": merged.get("description") or "",
            "aliases": merged.get("aliases") or [],
            "years": source.get("years") or [],
            "sample_events": source.get("sample_events") or [],
            "sample_venues": source.get("sample_venues") or [],
            "youtube_urls": (merged.get("youtube_urls") or source.get("youtube_urls") or [])[:5],
            "youtube_search_url": youtube_search_url(name),
        })

    candidates.sort(key=lambda row: (
        {"P0": 0, "P1": 1, "P2": 2}.get(row["priority"], 9),
        -row["bon_usage_score"],
        -row["source_count"],
        row["term"],
    ))
    return candidates


def esc(value):
    return html.escape(str(value or ""), quote=True)


def render_html(candidates, preloaded_decisions=None, decisions_source=""):
    data_json = json.dumps(candidates, ensure_ascii=False)
    preload_json = json.dumps(preloaded_decisions or {}, ensure_ascii=False)
    decisions_source_json = json.dumps(decisions_source, ensure_ascii=False)
    terms = [row["term"] for row in candidates]
    duplicate_terms = sorted({term for term in terms if terms.count(term) > 1})
    duplicate_terms_json = json.dumps(duplicate_terms, ensure_ascii=False)
    rows = []
    for index, row in enumerate(candidates):
        urls = "".join(
            f'<a href="{esc(url)}" target="_blank" rel="noopener">動画{idx + 1}</a>'
            for idx, url in enumerate(row["youtube_urls"])
        )
        events = "".join(f"<li>{esc(event)}</li>" for event in row["sample_events"][:4])
        aliases = " / ".join(row["aliases"][:5])
        rows.append(f"""
<article class="card" data-index="{index}" data-key="{esc(row['term'])}" data-priority="{esc(row['priority'])}" data-decision="" tabindex="-1">
  <div class="head">
    <span>{esc(row['priority'])}</span>
    <strong>{esc(row['term'])}</strong>
  </div>
  <p class="meta">利用度 {row['bon_usage_score']} / 根拠 {row['source_count']}件 / {esc(row['bon_usage_rank'])} / {esc(row['song_genre'])}</p>
  <p>{esc(row['description'])}</p>
  {f'<p class="aliases">別名: {esc(aliases)}</p>' if aliases else ''}
  <ul>{events}</ul>
  <div class="links">
    <a href="{esc(row['youtube_search_url'])}" target="_blank" rel="noopener">YouTube検索</a>
    {urls}
  </div>
  <div class="buttons">
    <button type="button" data-choice="publish">公開候補 <kbd>1</kbd></button>
    <button type="button" data-choice="research">要調査 <kbd>2</kbd></button>
    <button type="button" data-choice="reject">除外候補 <kbd>3</kbd></button>
    <button type="button" data-choice="later">後で <kbd>4</kbd></button>
  </div>
  <textarea placeholder="判断メモ"></textarea>
</article>""")

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>曲リスト公開レビュー</title>
<style>
html {{ scroll-padding-top: 16px; }}
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif; background: #0f172a; color: #e5e7eb; }}
header {{ padding: 10px 24px 8px; background: #111827; border-bottom: 1px solid #334155; }}
h1 {{ margin: 0 0 6px; font-size: 19px; line-height: 1.2; }}
.bar {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
input, select, textarea {{ background: #020617; color: #e5e7eb; border: 1px solid #475569; border-radius: 6px; padding: 6px 8px; }}
button, .download {{ background: #f97316; color: #111827; border: 0; border-radius: 6px; padding: 7px 9px; font-weight: 700; cursor: pointer; text-decoration: none; }}
#q {{ width: 220px; }}
main {{ width: min(1480px, calc(100% - 48px)); margin: 0 auto; padding: 14px 0 60px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 560px), 1fr)); gap: 14px; }}
.card {{ border: 1px solid #334155; border-radius: 8px; background: #18213a; padding: 16px; }}
.card.active {{ border-color: #f97316; box-shadow: 0 0 0 3px rgba(249, 115, 22, .28); }}
.card:focus {{ outline: none; }}
.head {{ display: flex; gap: 10px; align-items: baseline; color: #fb923c; }}
.head strong {{ color: #fff7ed; font-size: 22px; }}
.meta, .aliases {{ color: #cbd5e1; }}
ul {{ padding-left: 20px; color: #cbd5e1; }}
.links, .buttons {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
.links a {{ color: #93c5fd; }}
textarea {{ width: 100%; min-height: 64px; box-sizing: border-box; margin-top: 10px; }}
.card[data-decision="publish"] {{ border-color: #22c55e; }}
.card[data-decision="research"] {{ border-color: #facc15; }}
.card[data-decision="reject"] {{ border-color: #ef4444; opacity: .72; }}
.card[data-decision="later"] {{ border-color: #94a3b8; }}
kbd {{ border: 1px solid #475569; border-bottom-width: 2px; border-radius: 4px; background: #020617; color: #e5e7eb; padding: 1px 5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
.shortcut-help {{ flex-basis: 100%; color: #cbd5e1; font-size: 12px; line-height: 1.7; }}
.shortcut-help summary {{ display: inline-flex; gap: 6px; align-items: center; cursor: pointer; color: #93c5fd; }}
.shortcut-help[open] summary {{ margin-bottom: 4px; }}
#safety {{ flex-basis: 100%; color: #fde68a; font-size: 12px; line-height: 1.4; }}
</style>
</head>
<body>
<header>
  <h1>曲リスト公開レビュー</h1>
  <div class="bar">
    <input id="q" placeholder="曲名・説明・イベントで検索">
    <select id="priority"><option value="">全優先度</option><option>P0</option><option>P1</option><option>P2</option></select>
    <select id="decision"><option value="">全判断</option><option value="__unreviewed">未判断</option><option value="publish">公開候補</option><option value="research">要調査</option><option value="reject">除外候補</option><option value="later">後で</option></select>
    <button id="export">判断JSONを書き出し</button>
    <span id="count"></span>
    <span id="safety"></span>
    <details id="shortcuts" class="shortcut-help">
      <summary>ショートカット <kbd>?</kbd></summary>
      <kbd>j</kbd>/<kbd>k</kbd> or <kbd>↓</kbd>/<kbd>↑</kbd> 移動　
      <kbd>1</kbd> 公開候補　
      <kbd>2</kbd> 要調査　
      <kbd>3</kbd> 除外候補　
      <kbd>4</kbd> 後で　
      <kbd>/</kbd> 検索　
      <kbd>n</kbd> メモ　
      <kbd>o</kbd> YouTube検索　
      <kbd>v</kbd> 動画　
      <kbd>u</kbd> 未判断　
      <kbd>a</kbd> 全表示　
      <kbd>e</kbd> 書き出し
    </details>
  </div>
</header>
<main id="cards">{''.join(rows)}</main>
<script>
const DATA = {data_json};
const PRELOADED = {preload_json};
const DECISIONS_SOURCE = {decisions_source_json};
const DUPLICATE_TERMS = {duplicate_terms_json};
const KEY = "song-publication-review-v1";
const state = loadState();
const cards = [...document.querySelectorAll(".card")];
let activeIndex = 0;
let safetyReport = {{}};
function loadState() {{
  try {{
    const parsed = JSON.parse(localStorage.getItem(KEY) || "{{}}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {{}};
  }} catch {{
    return {{}};
  }}
}}
function save() {{ localStorage.setItem(KEY, JSON.stringify(state)); }}
function keyForCard(card) {{ return card.dataset.key; }}
function hasReviewValue(item) {{ return Boolean(item && (item.decision || item.note)); }}
function mergePreloadedDecisions() {{
  let restored = 0;
  let protectedLocal = 0;
  let ignoredMissing = 0;
  let changed = false;
  const currentKeys = new Set(DATA.map(row => row.term));
  Object.entries(PRELOADED).forEach(([key, item]) => {{
    if (!currentKeys.has(key)) {{
      ignoredMissing += 1;
      return;
    }}
    if (!hasReviewValue(item)) return;
    if (!hasReviewValue(state[key])) {{
      state[key] = {{ decision: item.decision || "", note: item.note || "" }};
      restored += 1;
      changed = true;
      return;
    }}
    const local = state[key] || {{}};
    if ((local.decision || "") !== (item.decision || "") || (local.note || "") !== (item.note || "")) {{
      protectedLocal += 1;
    }}
  }});
  const staleLocal = Object.keys(state).filter(key => !currentKeys.has(key) && hasReviewValue(state[key])).length;
  safetyReport = {{ restored, protectedLocal, ignoredMissing, staleLocal, duplicates: DUPLICATE_TERMS.length }};
  if (changed) save();
}}
function renderSafety() {{
  const parts = [];
  if (DECISIONS_SOURCE) parts.push(`復元元: ${{DECISIONS_SOURCE}}`);
  if (safetyReport.restored) parts.push(`復元 ${{safetyReport.restored}}件`);
  if (safetyReport.protectedLocal) parts.push(`ブラウザ側を優先 ${{safetyReport.protectedLocal}}件`);
  if (safetyReport.staleLocal) parts.push(`現リスト外の保存あり ${{safetyReport.staleLocal}}件`);
  if (safetyReport.ignoredMissing) parts.push(`現リスト外の復元候補を無視 ${{safetyReport.ignoredMissing}}件`);
  if (safetyReport.duplicates) parts.push(`重複キー警告 ${{safetyReport.duplicates}}件`);
  document.querySelector("#safety").textContent = parts.join(" / ");
}}
function applyState() {{
  cards.forEach(card => {{
    const item = state[keyForCard(card)] || {{}};
    card.dataset.decision = item.decision || "";
    card.querySelector("textarea").value = item.note || "";
  }});
}}
function visibleCards() {{ return cards.filter(card => !card.hidden); }}
function activeCard() {{ return visibleCards()[activeIndex] || null; }}
function setActiveIndex(index, options = {{}}) {{
  const visible = visibleCards();
  cards.forEach(card => card.classList.remove("active"));
  if (!visible.length) {{
    activeIndex = 0;
    return null;
  }}
  activeIndex = Math.max(0, Math.min(index, visible.length - 1));
  const card = visible[activeIndex];
  card.classList.add("active");
  if (options.focus) card.focus({{ preventScroll: true }});
  if (options.scroll !== false) card.scrollIntoView({{ block: "center", behavior: options.smooth === false ? "auto" : "smooth" }});
  return card;
}}
function moveActive(delta) {{ setActiveIndex(activeIndex + delta, {{ focus: true }}); }}
function filter() {{
  const q = document.querySelector("#q").value.trim().toLowerCase();
  const priority = document.querySelector("#priority").value;
  const decision = document.querySelector("#decision").value;
  let visible = 0;
  cards.forEach(card => {{
    const row = DATA[Number(card.dataset.index)];
    const haystack = JSON.stringify(row).toLowerCase();
    const decisionOk = !decision || (decision === "__unreviewed" ? !card.dataset.decision : card.dataset.decision === decision);
    const ok = (!q || haystack.includes(q)) && (!priority || row.priority === priority) && decisionOk;
    card.hidden = !ok;
    if (ok) visible += 1;
  }});
  document.querySelector("#count").textContent = `${{visible}} / ${{cards.length}}件`;
  setActiveIndex(Math.min(activeIndex, Math.max(visible - 1, 0)), {{ scroll: false }});
}}
function chooseDecision(card, decision) {{
  if (!card) return;
  const key = keyForCard(card);
  state[key] = state[key] || {{}};
  state[key].decision = decision;
  save();
  applyState();
  filter();
  if (document.querySelector("#decision").value === "__unreviewed") {{
    setActiveIndex(activeIndex, {{ focus: true }});
  }} else {{
    moveActive(1);
  }}
}}
cards.forEach(card => {{
  card.querySelectorAll("button[data-choice]").forEach(button => {{
    button.addEventListener("click", () => {{
      chooseDecision(card, button.dataset.choice);
    }});
  }});
  card.querySelector("textarea").addEventListener("input", event => {{
    const key = keyForCard(card);
    state[key] = state[key] || {{}};
    state[key].note = event.target.value;
    save();
  }});
}});
document.querySelectorAll("#q,#priority,#decision").forEach(el => el.addEventListener("input", filter));
function focusActiveNote() {{
  const note = activeCard()?.querySelector("textarea");
  if (note) note.focus();
}}
function openActiveSearch() {{
  const row = DATA[Number(activeCard()?.dataset.index)];
  if (row?.youtube_search_url) window.open(row.youtube_search_url, "_blank", "noopener,noreferrer");
}}
function openActiveVideo() {{
  const row = DATA[Number(activeCard()?.dataset.index)];
  const url = row?.youtube_urls?.[0] || row?.youtube_search_url;
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}}
function toggleShortcuts() {{
  const shortcuts = document.querySelector("#shortcuts");
  if (shortcuts) shortcuts.open = !shortcuts.open;
}}
function exportResults() {{
  const currentKeys = new Set(DATA.map(row => row.term));
  const decisions = DATA
    .map(row => ({{...row, ...(state[row.term] || {{}})}}))
    .filter(row => row.decision || row.note);
  const orphaned_state = Object.fromEntries(
    Object.entries(state).filter(([key, item]) => !currentKeys.has(key) && hasReviewValue(item))
  );
  const payload = {{
    schema_version: 1,
    exported_at: new Date().toISOString(),
    generated_by: "song_publication_review.html",
    storage_key: KEY,
    candidate_count: DATA.length,
    decision_count: decisions.length,
    rows: decisions,
    orphaned_state,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "song_publication_review_decisions.json";
  a.click();
  URL.revokeObjectURL(url);
}}
function isTextInput(target) {{
  return target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable);
}}
document.querySelector("#export").addEventListener("click", exportResults);
document.addEventListener("keydown", event => {{
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (isTextInput(event.target)) {{
    if (event.key === "Escape") {{
      event.target.blur();
      setActiveIndex(activeIndex, {{ scroll: false, focus: true }});
      event.preventDefault();
    }}
    return;
  }}
  const actions = {{
    "j": () => moveActive(1),
    "ArrowDown": () => moveActive(1),
    "k": () => moveActive(-1),
    "ArrowUp": () => moveActive(-1),
    "1": () => chooseDecision(activeCard(), "publish"),
    "2": () => chooseDecision(activeCard(), "research"),
    "3": () => chooseDecision(activeCard(), "reject"),
    "4": () => chooseDecision(activeCard(), "later"),
    "/": () => {{
      const input = document.querySelector("#q");
      input.focus();
      input.select();
    }},
    "n": focusActiveNote,
    "o": openActiveSearch,
    "v": openActiveVideo,
    "?": toggleShortcuts,
    "u": () => {{
      document.querySelector("#decision").value = "__unreviewed";
      activeIndex = 0;
      filter();
    }},
    "a": () => {{
      document.querySelector("#q").value = "";
      document.querySelector("#priority").value = "";
      document.querySelector("#decision").value = "";
      activeIndex = 0;
      filter();
    }},
    "e": exportResults,
    "Escape": () => setActiveIndex(activeIndex, {{ focus: true }})
  }};
  const action = actions[event.key];
  if (!action) return;
  event.preventDefault();
  action();
}});
mergePreloadedDecisions();
applyState();
filter();
renderSafety();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--glossary", default=str(DEFAULT_SITE_GLOSSARY))
    parser.add_argument("--youtube-master", default=str(DEFAULT_YOUTUBE_MASTER))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-html", default=str(DEFAULT_OUT_HTML))
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS))
    args = parser.parse_args()

    candidates = build_candidates(Path(args.glossary), Path(args.youtube_master))
    preloaded_decisions, decisions_source = read_decisions(Path(args.decisions))
    payload = {
        "generated_by": "build_song_publication_review.py",
        "candidate_count": len(candidates),
        "priority_counts": {priority: sum(1 for row in candidates if row["priority"] == priority) for priority in ["P0", "P1", "P2"]},
        "candidates": candidates,
    }
    write_json(Path(args.out_json), payload)
    Path(args.out_html).write_text(
        render_html(candidates, preloaded_decisions, decisions_source),
        encoding="utf-8",
    )
    print(f"曲公開レビュー生成: {len(candidates)}件 -> {args.out_html}")


if __name__ == "__main__":
    main()
