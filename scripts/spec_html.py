#!/usr/bin/env python3
"""docs/spec/ の Markdown と index.json から、単一ファイルのHTML閲覧版を生成する。

手書きのHTMLは仕様書が更新された瞬間に古くなるので、必ずここから生成する。
使い方: python3 scripts/spec_html.py --out <path>.html
"""
import argparse
import html
import json
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "docs" / "spec"

LAYER_GROUPS = [
    ("L0", "全体地図"),
    ("L1", "サブシステム"),
    ("L2", "データ契約"),
    ("meta", "仕様書の書き方"),
]


# --------------------------------------------------------------------------
# Markdown（必要な部分集合だけ）
# --------------------------------------------------------------------------

INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def split_front_matter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    return text[4:end], text[end + 4 :].lstrip("\n")


def inline(text, link_resolver):
    # コードは先に退避して、中身がbold等で壊れないようにする
    stash = []

    def keep(match):
        stash.append(match.group(1))
        return f"\x00{len(stash) - 1}\x00"

    text = INLINE_CODE.sub(keep, text)
    text = html.escape(text, quote=False)
    text = BOLD.sub(r"<strong>\1</strong>", text)

    def link(match):
        label, target = match.group(1), match.group(2)
        href = link_resolver(target)
        external = href.startswith("http")
        rel = ' target="_blank" rel="noopener"' if external else ""
        return f'<a href="{html.escape(href, quote=True)}"{rel}>{label}</a>'

    text = LINK.sub(link, text)
    for i, code in enumerate(stash):
        text = text.replace(f"\x00{i}\x00", f"<code>{html.escape(code, quote=False)}</code>")
    return text


def render_markdown(body, link_resolver):
    lines = body.split("\n")
    out = []
    i = 0
    n = len(lines)

    def flush_para(buf):
        if buf:
            out.append("<p>" + inline(" ".join(buf), link_resolver) + "</p>")
            buf.clear()

    para = []
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_para(para)
            lang = stripped[3:].strip()
            i += 1
            block = []
            while i < n and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            content = "\n".join(block)
            if lang == "mermaid":
                out.append(f'<pre class="mermaid">{html.escape(content, quote=False)}</pre>')
            else:
                out.append(
                    '<div class="scroll-x"><pre class="code"><code>'
                    + html.escape(content, quote=False)
                    + "</code></pre></div>"
                )
            continue

        if not stripped:
            flush_para(para)
            i += 1
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush_para(para)
            level = len(heading.group(1))
            text = heading.group(2)
            inv = re.match(r"^(INV-[A-Za-z0-9]+-\d+)\s+(.*)$", text)
            if inv:
                out.append(
                    f'<h{level} class="inv-head" id="{inv.group(1)}">'
                    f'<span class="inv-id">{inv.group(1)}</span>'
                    f'<span class="inv-title">{inline(inv.group(2), link_resolver)}</span>'
                    f"</h{level}>"
                )
            else:
                out.append(f"<h{level}>{inline(text, link_resolver)}</h{level}>")
            i += 1
            continue

        # 表
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush_para(para)
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            thead = "".join(f"<th>{inline(c, link_resolver)}</th>" for c in header)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{inline(c, link_resolver)}</td>" for c in r) + "</tr>"
                for r in rows
            )
            out.append(
                f'<div class="scroll-x"><table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>'
            )
            continue

        # 引用
        if stripped.startswith(">"):
            flush_para(para)
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(quote), link_resolver) + "</blockquote>")
            continue

        # 箇条書き / 番号付き
        bullet = re.match(r"^([-*]|\d+\.)\s+(.*)$", stripped)
        if bullet:
            flush_para(para)
            ordered = bool(re.match(r"^\d+\.", bullet.group(1)))
            tag = "ol" if ordered else "ul"
            items = []
            while i < n:
                m = re.match(r"^([-*]|\d+\.)\s+(.*)$", lines[i].strip())
                if not m:
                    # 継続行（インデントされた折り返し）
                    if items and lines[i].startswith("  ") and lines[i].strip():
                        items[-1] += " " + lines[i].strip()
                        i += 1
                        continue
                    break
                if bool(re.match(r"^\d+\.", m.group(1))) != ordered:
                    break
                items.append(m.group(2))
                i += 1
            body_items = "".join(f"<li>{inline(it, link_resolver)}</li>" for it in items)
            out.append(f"<{tag}>{body_items}</{tag}>")
            continue

        if stripped == "---":
            flush_para(para)
            out.append("<hr />")
            i += 1
            continue

        para.append(stripped)
        i += 1

    flush_para(para)
    return "\n".join(out)


# --------------------------------------------------------------------------
# 組み立て
# --------------------------------------------------------------------------


def build(index):
    specs = index["specs"]
    path_to_id = {meta["path"]: sid for sid, meta in specs.items()}

    def order_key(item):
        sid, meta = item
        layer = meta.get("layer") or "meta"
        rank = {"L0": 0, "L1": 1, "L2": 2}.get(layer, 3)
        return (rank, meta.get("path") or sid)

    ordered = sorted(specs.items(), key=order_key)
    sections = []

    for sid, meta in ordered:
        source = ROOT / meta["path"]
        _, body = split_front_matter(source.read_text(encoding="utf-8"))
        here = posixpath.dirname(meta["path"])

        def resolver(target, _here=here):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                return target
            resolved = posixpath.normpath(posixpath.join(_here, target.split("#")[0]))
            if resolved in path_to_id:
                return "#" + path_to_id[resolved]
            return "#" + sid

        sections.append((sid, meta, render_markdown(body, resolver)))

    return ordered, sections


def invariant_rows(index):
    rows = []
    for inv_id, inv in sorted(index["invariants"].items()):
        rows.append(
            {
                "id": inv_id,
                "title": inv.get("title") or "",
                "spec": inv.get("spec") or "",
                "has_test": bool(inv.get("has_test")),
                "tests": inv.get("tests") or [],
            }
        )
    return rows


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --ground:#FAF8F4; --surface:#FFFFFF; --surface-2:#F2EEE7;
  --ink:#16202B; --ink-soft:#3D4A57; --muted:#68727E;
  --rule:#E0D9CE; --rule-soft:#EDE7DC;
  --accent:#1D4E6B; --accent-soft:#E4EDF3; --accent-ink:#123549;
  --warn:#9C5B14; --warn-soft:#F7EDDF;
  --ok:#2F6B4F; --ok-soft:#E6F0E9;
  --shadow:0 1px 2px rgba(22,32,43,.06),0 8px 24px rgba(22,32,43,.05);
  --serif:"Hiragino Mincho ProN","Yu Mincho",YuMincho,"Noto Serif JP",serif;
  --sans:"Hiragino Kaku Gothic ProN","Yu Gothic",YuGothic,"Noto Sans JP",system-ui,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0F151B; --surface:#161E26; --surface-2:#1D2831;
    --ink:#E7ECF1; --ink-soft:#C2CCD6; --muted:#8A97A4;
    --rule:#2A3742; --rule-soft:#212C36;
    --accent:#79ADCC; --accent-soft:#17303F; --accent-ink:#A8CDE3;
    --warn:#D8973C; --warn-soft:#2E2415;
    --ok:#6FB48F; --ok-soft:#14251C;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --ground:#0F151B; --surface:#161E26; --surface-2:#1D2831;
  --ink:#E7ECF1; --ink-soft:#C2CCD6; --muted:#8A97A4;
  --rule:#2A3742; --rule-soft:#212C36;
  --accent:#79ADCC; --accent-soft:#17303F; --accent-ink:#A8CDE3;
  --warn:#D8973C; --warn-soft:#2E2415;
  --ok:#6FB48F; --ok-soft:#14251C;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
}
html{scroll-behavior:smooth}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:var(--sans);font-size:15.5px;line-height:1.85;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--accent);text-underline-offset:2px;text-decoration-thickness:.5px}
a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}

.shell{display:grid;grid-template-columns:270px minmax(0,1fr);gap:0;min-height:100vh}
.rail{border-right:1px solid var(--rule);background:var(--surface);
  position:sticky;top:0;height:100vh;overflow-y:auto;padding:26px 20px 40px}
.brand{font-family:var(--serif);font-size:23px;letter-spacing:.04em;margin:0 0 2px;color:var(--ink)}
.brand small{display:block;font-family:var(--sans);font-size:11px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted);margin-top:7px;font-weight:600}
.stat{margin:20px 0 22px;padding:13px 14px;background:var(--surface-2);border-radius:3px;
  border-left:2px solid var(--accent)}
.stat b{font-family:var(--serif);font-size:21px;font-variant-numeric:tabular-nums;display:block;line-height:1.3}
.stat span{font-size:11.5px;color:var(--muted);letter-spacing:.03em}
.group{margin:0 0 18px}
.group>h2{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);
  margin:0 0 7px;font-weight:700}
.navlink{display:block;padding:6px 9px;border-radius:3px;color:var(--ink-soft);
  text-decoration:none;font-size:13.5px;line-height:1.5;border-left:2px solid transparent}
.navlink:hover{background:var(--surface-2);color:var(--ink)}
.navlink.on{background:var(--accent-soft);color:var(--accent-ink);border-left-color:var(--accent);font-weight:600}
.navlink .tag{display:block;font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.04em}

.main{min-width:0;display:flex;flex-direction:column}
.topbar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--ground) 92%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--rule);padding:12px 34px;
  display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.search{flex:1;min-width:240px;position:relative}
.search input{width:100%;padding:9px 12px;font:inherit;font-size:14px;font-family:var(--mono);
  background:var(--surface);color:var(--ink);border:1px solid var(--rule);border-radius:3px}
.search input::placeholder{color:var(--muted);font-family:var(--sans)}
.hint{font-size:12px;color:var(--muted)}
.results{position:absolute;top:calc(100% + 6px);left:0;right:0;background:var(--surface);
  border:1px solid var(--rule);border-radius:3px;box-shadow:var(--shadow);max-height:340px;
  overflow-y:auto;display:none;z-index:30}
.results.show{display:block}
.results button{display:block;width:100%;text-align:left;background:none;border:0;
  padding:9px 12px;font:inherit;cursor:pointer;color:var(--ink);border-bottom:1px solid var(--rule-soft)}
.results button:last-child{border-bottom:0}
.results button:hover{background:var(--accent-soft)}
.results .f{font-family:var(--mono);font-size:12.5px}
.results .s{font-size:11.5px;color:var(--muted)}
.results .none{padding:11px 12px;font-size:12.5px;color:var(--muted)}

.page{padding:34px 34px 90px;max-width:860px}
.page[hidden]{display:none}
.eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);
  font-weight:700;margin:0 0 6px}
.page h1{font-family:var(--serif);font-size:33px;line-height:1.35;margin:0 0 6px;
  font-weight:600;text-wrap:balance;letter-spacing:.01em}
.page h2{font-family:var(--serif);font-size:22px;margin:38px 0 10px;font-weight:600;
  text-wrap:balance;padding-bottom:7px;border-bottom:1px solid var(--rule)}
.page h3{font-size:16.5px;margin:26px 0 8px;font-weight:700;text-wrap:balance}
.page h4{font-size:14.5px;margin:20px 0 6px;font-weight:700;color:var(--ink-soft)}
.page p{margin:0 0 15px}
.page ul,.page ol{margin:0 0 15px;padding-left:1.35em}
.page li{margin:0 0 6px}
.page hr{border:0;border-top:1px solid var(--rule);margin:34px 0}
blockquote{margin:0 0 17px;padding:12px 16px;background:var(--surface-2);
  border-left:2px solid var(--accent);border-radius:0 3px 3px 0;color:var(--ink-soft)}
code{font-family:var(--mono);font-size:.855em;background:var(--surface-2);
  padding:.12em .38em;border-radius:2px;word-break:break-word}
pre.code{background:var(--surface-2);border:1px solid var(--rule);border-radius:3px;
  padding:14px 16px;margin:0;line-height:1.6}
pre.code code{background:none;padding:0;font-size:12.8px}
pre.mermaid{background:var(--surface);border:1px solid var(--rule);border-radius:3px;
  padding:18px;margin:0 0 17px;text-align:center;overflow-x:auto}
.scroll-x{overflow-x:auto;margin:0 0 17px}
table{border-collapse:collapse;width:100%;font-size:13.8px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--rule-soft);vertical-align:top}
th{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
  border-bottom:1px solid var(--rule);font-weight:700;white-space:nowrap}
td:has(code){font-variant-numeric:tabular-nums}

.inv-head{display:flex;flex-direction:column;gap:3px;margin:30px 0 10px;
  padding:11px 14px;background:var(--surface-2);border-radius:3px;
  border-left:3px solid var(--accent)}
.inv-id{font-family:var(--mono);font-size:11.5px;letter-spacing:.06em;color:var(--accent);font-weight:700}
.inv-title{font-size:16px;font-weight:700;line-height:1.55}

.invtable td.st{white-space:nowrap}
.pill{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px;
  letter-spacing:.03em;white-space:nowrap}
.pill.ok{background:var(--ok-soft);color:var(--ok)}
.pill.warn{background:var(--warn-soft);color:var(--warn)}
tr.risk td{background:color-mix(in srgb,var(--warn-soft) 55%,transparent)}
.lead{font-size:16.5px;color:var(--ink-soft);margin:0 0 24px;max-width:62ch}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:0 0 30px}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:3px;padding:15px 16px}
.card b{font-family:var(--serif);font-size:27px;display:block;line-height:1.2;
  font-variant-numeric:tabular-nums}
.card span{font-size:12px;color:var(--muted);display:block;margin-top:3px}
.card.warn{border-left:3px solid var(--warn)}
.card.warn b{color:var(--warn)}
.foot{margin-top:44px;padding-top:18px;border-top:1px solid var(--rule);
  font-size:12.5px;color:var(--muted)}

@media (max-width:880px){
  .shell{grid-template-columns:1fr}
  .rail{position:static;height:auto;border-right:0;border-bottom:1px solid var(--rule)}
  .page,.topbar{padding-left:20px;padding-right:20px}
}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{animation:none!important;transition:none!important}}
"""


def render_html(index, ordered, sections, rows):
    coverage = index["coverage"]
    total_inv = len(rows)
    with_test = sum(1 for r in rows if r["has_test"])
    missing = [r for r in rows if not r["has_test"]]

    nav = []
    for layer, label in LAYER_GROUPS:
        items = [(sid, m) for sid, m in ordered if (m.get("layer") or "meta") == layer]
        if not items:
            continue
        links = "".join(
            f'<a class="navlink" href="#{sid}" data-target="{sid}">{html.escape(m.get("title") or sid)}'
            f'<span class="tag">{html.escape(sid)}</span></a>'
            for sid, m in items
        )
        nav.append(f'<div class="group"><h2>{label}</h2>{links}</div>')

    nav.append(
        '<div class="group"><h2>横断で見る</h2>'
        '<a class="navlink" href="#invariants" data-target="invariants">不変条件の一覧'
        f'<span class="tag">{total_inv} 件 / 未検査 {len(missing)}</span></a></div>'
    )

    pages = []
    for sid, meta, body in sections:
        layer = meta.get("layer") or "meta"
        stale = meta.get("staleness") or {}
        changed = stale.get("files_changed_since")
        freshness = (
            f'{meta.get("updated_for","")} 時点で確認済み'
            + (f"／以降 {changed} ファイルが変更" if changed else "")
        )
        owned = meta.get("owned_files") or []
        owned_list = (
            '<h2>この仕様が責任を持つファイル</h2><div class="scroll-x"><table><tbody>'
            + "".join(f"<tr><td><code>{html.escape(f)}</code></td></tr>" for f in owned)
            + "</tbody></table></div>"
            if owned
            else ""
        )
        pages.append(
            f'<article class="page" id="{sid}" hidden>'
            f'<p class="eyebrow">{html.escape(layer)} ・ {html.escape(freshness)}</p>'
            f"{body}{owned_list}"
            "</article>"
        )

    inv_rows = "".join(
        f'<tr class="{"risk" if not r["has_test"] else ""}">'
        f'<td><a href="#{r["id"]}"><code>{r["id"]}</code></a></td>'
        f'<td>{html.escape(r["title"])}</td>'
        f'<td><a href="#{r["spec"]}">{html.escape(r["spec"])}</a></td>'
        f'<td class="st">'
        + (
            '<span class="pill ok">テストあり</span>'
            if r["has_test"]
            else '<span class="pill warn">テストなし</span>'
        )
        + "</td></tr>"
        for r in rows
    )

    inv_page = f"""<article class="page" id="invariants" hidden>
<p class="eyebrow">横断ビュー</p>
<h1>不変条件の一覧</h1>
<p class="lead">「破ると全体が壊れる約束」を一覧にしたもの。<strong>テストなし</strong>の行は、
仕様書には書いてあるが、実際に壊れても誰も気づかない状態を意味する。</p>
<div class="cards">
<div class="card"><b>{total_inv}</b><span>不変条件</span></div>
<div class="card"><b>{with_test}</b><span>テストで守られている</span></div>
<div class="card warn"><b>{len(missing)}</b><span>守られていない</span></div>
<div class="card"><b>{coverage["owned"]} / {coverage["tracked_source_files"]}</b><span>説明のあるファイル</span></div>
</div>
<div class="scroll-x"><table class="invtable"><thead><tr>
<th>ID</th><th>内容</th><th>どの仕様か</th><th>状態</th>
</tr></thead><tbody>{inv_rows}</tbody></table></div>
<p class="foot">生成元: <code>docs/spec/index.json</code>（<code>{html.escape(index["generated_for_commit"])}</code> 時点）。
この表は手書きではなく、仕様書の本文から機械的に集めている。</p>
</article>"""

    lookup = json.dumps(
        {
            "file_to_spec": index["file_to_spec"],
            "titles": {sid: (m.get("title") or sid) for sid, m in ordered},
            "invariants": {sid: (m.get("invariants") or []) for sid, m in ordered},
        },
        ensure_ascii=False,
    )

    return f"""<title>盆助 仕様書</title>
<style>{CSS}</style>
<div class="shell">
<nav class="rail">
  <h1 class="brand">盆助 仕様書<small>Bonsuke Specification</small></h1>
  <div class="stat">
    <b>{coverage["owned"]} / {coverage["tracked_source_files"]}</b>
    <span>説明のあるファイル（残り {coverage["unowned"]} 件は未記述）</span>
  </div>
  {"".join(nav)}
</nav>
<div class="main">
  <div class="topbar">
    <div class="search">
      <input id="q" type="search" autocomplete="off" spellcheck="false"
             placeholder="ファイル名から逆引き（例: collect.py）" aria-label="ファイル名から逆引き" />
      <div class="results" id="res" role="listbox"></div>
    </div>
    <span class="hint">触るファイルが決まっているときは、ここから引く</span>
  </div>
  {"".join(pages)}
  {inv_page}
</div>
</div>
<script>
const DATA = {lookup};
const pages = [...document.querySelectorAll('.page')];
const links = [...document.querySelectorAll('.navlink')];

function show(id) {{
  const target = document.getElementById(id) ? id : pages[0].id;
  pages.forEach(p => {{ p.hidden = p.id !== target; }});
  links.forEach(a => a.classList.toggle('on', a.dataset.target === target));
  document.querySelector('.main').scrollTo?.({{top: 0}});
  window.scrollTo({{top: 0, behavior: 'auto'}});
}}

function route() {{
  const hash = decodeURIComponent(location.hash.slice(1));
  if (!hash) return show(pages[0].id);
  if (document.getElementById(hash) && document.getElementById(hash).classList.contains('page')) {{
    return show(hash);
  }}
  // 不変条件など、ページ内の見出しを指している場合
  const el = document.getElementById(hash);
  if (el) {{
    const page = el.closest('.page');
    if (page) {{ show(page.id); el.scrollIntoView({{block: 'center'}}); }}
    return;
  }}
  show(pages[0].id);
}}
window.addEventListener('hashchange', route);

const q = document.getElementById('q');
const res = document.getElementById('res');
const files = Object.keys(DATA.file_to_spec);

q.addEventListener('input', () => {{
  const term = q.value.trim().toLowerCase();
  if (!term) {{ res.classList.remove('show'); res.innerHTML = ''; return; }}
  const hits = files.filter(f => f.toLowerCase().includes(term)).slice(0, 40);
  if (!hits.length) {{
    res.innerHTML = '<div class="none">どの仕様も担当していないファイルです。未記述領域なので、ソースを直接読む必要があります。</div>';
    res.classList.add('show');
    return;
  }}
  res.innerHTML = hits.map(f => {{
    const sid = DATA.file_to_spec[f];
    const invs = (DATA.invariants[sid] || []).join(', ') || '不変条件なし';
    return `<button data-go="${{sid}}"><span class="f">${{f}}</span>` +
           `<span class="s">${{DATA.titles[sid] || sid}} ・ ${{invs}}</span></button>`;
  }}).join('');
  res.classList.add('show');
}});

res.addEventListener('click', (e) => {{
  const btn = e.target.closest('button[data-go]');
  if (!btn) return;
  location.hash = btn.dataset.go;
  res.classList.remove('show');
  q.value = '';
}});

document.addEventListener('click', (e) => {{
  if (!e.target.closest('.search')) res.classList.remove('show');
}});

route();
</script>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default=str(SPEC_DIR / "index.json"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    ordered, sections = build(index)
    rows = invariant_rows(index)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(index, ordered, sections, rows), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes) / specs={len(sections)} invariants={len(rows)}")


if __name__ == "__main__":
    raise SystemExit(main())
