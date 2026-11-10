"""Build the presence review page (build plan everyday chemistry 2026-11, phase 1) from the seeds.

Reads every hand mark through transform/presence.load_marks (the same marks the build exports) and writes
one self-contained HTML page for Garrett: the entries his corrections of 2026-11-10 changed first, then every formed,
body and reasoned no-mark entry and every molecule marked differently in two places, then every mark by list.
Run after editing a mark, from the ETL root:
    ./.venv/bin/python3 scripts/presence_review.py [out.html]
The default output is the web repo's docs/design/presence-review-2026-11.html.
"""
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from moleculefinder_etl.transform import presence


def _code(m):
    return {"natural": "N", "added": "A", "body": "B", "none": "X"}.get(m["value"]) or "F:" + m["formed_when"]


def _table(marks):
    out = {}
    for (h, s), m in marks.items():
        out.setdefault(h, []).append((s, _code(m), m.get("note") or ""))
    return out


_M = presence.load_marks()
FOOD, PRODUCT, WORLD, WIKIDATA = (_table(_M[k]) for k in ("food", "product", "world", "wikidata"))

ETL = ROOT
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "moleculefinder-web" / "docs" / "design" / "presence-review-2026-11.html"
SNAP = ETL / "data" / "snapshots"
TITLES = {json.loads(p.read_text())["slug"]: json.loads(p.read_text())["title"] for p in (SNAP / "molecules").glob("*.json")}
PRODUCTS = json.loads((SNAP / "products.json").read_text())["products"]
SEED = yaml.safe_load((ETL / "moleculefinder_etl/sources/seeds/products.yaml").read_text())["products"]
KIND_BY_HUB = {r["curated"]: r["kind"] for r in SEED if r.get("curated")}
KIND_BY_HUB.update({"tabletop-sweetener": "food", "diet-soda": "drink", "sugar-free-gum": "food", "stevia": "food"})
KIND_BY_SLUG = {r["slug"]: r["kind"] for r in SEED}
FOOD_NAMES = {h: v["name"] for h, v in yaml.safe_load((ETL / "moleculefinder_etl/sources/seeds/food_hubs.yaml").read_text()).items()}
FOOD_NAMES.update({"tabletop-sweetener": "Tabletop sweetener", "diet-soda": "Diet soda", "sugar-free-gum": "Sugar-free gum", "stevia": "Stevia"})
PROD_NAMES = {h: v["name"] for h, v in yaml.safe_load((ETL / "moleculefinder_etl/sources/seeds/product_hubs.yaml").read_text()).items()}
WORLD_NAMES = {w["slug"]: w["title"] for w in yaml.safe_load((ETL / "moleculefinder_etl/sources/seeds/worlds.yaml").read_text())["worlds"]}
PRODUCT_NAMES = {p["slug"]: p["name"] for p in PRODUCTS}
OVERLAY_ONLY = {"tabletop-sweetener", "diet-soda", "sugar-free-gum", "stevia"}

WHEN = presence.FORMED_WHEN
WORD = {"N": "Naturally present", "A": "Added by the maker", "B": "Made by your body", "X": "No mark"}
CLS = {"N": "natural", "A": "added", "B": "body", "X": "none"}

# Garrett's corrections of 2026-11-10 (he approved the page with these): (list key, molecule) -> what he ruled.
CORRECTED = {
    ("food:chocolate", "phenethylamine"): "Formed by fermentation, with his reason.",
    ("food:chocolate", "tyramine"): "Formed by fermentation, with his reason.",
    ("food:cocoa", "phenethylamine"): "Formed by fermentation, with his reason.",
    ("food:cocoa", "tyramine"): "Formed by fermentation, with his reason.",
    ("world:chocolate", "phenethylamine"): "Formed by fermentation, with his reason.",
    ("world:chocolate", "tyramine"): "Formed by fermentation, with his reason.",
    ("food:tea", "tannic-acid"): "Stays unmarked, his reason; removal queued for phase 2.",
    ("food:wine", "tannic-acid"): "Stays unmarked, his reason; removal queued for phase 2.",
    ("world:glass-of-wine", "tannic-acid"): "Stays unmarked, his reason; removal queued for phase 2.",
    ("product:fuel-and-flame", "benzene"): "No mark, his reason.",
    ("product:fuel-and-flame", "toluene"): "No mark, his reason.",
    ("world:sunscreen-summer-skin", "hyaluronic-acid"): "Made by your body, his reason.",
    ("wikidata:valio-valsa-milk-salt", "potassium"): "Stays unmarked: its composition is not confirmed.",
    ("wikidata:valio-valsa-milk-salt", "magnesium"): "Stays unmarked: its composition is not confirmed.",
    ("wikidata:valio-valsa-milk-salt", "calcium"): "Stays unmarked: its composition is not confirmed.",
    ("wikidata:valio-valsa-milk-salt", "sodium"): "Stays unmarked: its composition is not confirmed.",
    ("world:after-the-rain", "2-nonenal"): "Stays unmarked, his reason; removal queued for phase 2.",
    ("world:spicy-dinner", "allicin"): "Formed when crushed (the new ending), the reason kept.",
    ("world:spicy-dinner", "allyl-isothiocyanate"): "Formed when crushed (the new ending), the reason kept.",
    ("food:honey", "methylglyoxal"): "Natural to formed when aged, his reason. No other list carries methylglyoxal.",
}


def _row(**kw):
    return kw


def rows():
    out = []
    for hub, rs in FOOD.items():
        group = "drink" if KIND_BY_HUB.get(hub) == "drink" else "food"
        src = "curated overlays only" if hub in OVERLAY_ONLY else "food_hubs.yaml"
        for s, c, n in rs:
            out.append(_row(group=group, list=FOOD_NAMES[hub], key=f"food:{hub}", slug=s, code=c, note=n, src=src))
    for hub, rs in PRODUCT.items():
        for s, c, n in rs:
            out.append(_row(group="product", list=PROD_NAMES[hub], key=f"product:{hub}", slug=s, code=c, note=n,
                            src="product_hubs.yaml"))
    for w, rs in WORLD.items():
        for s, c, n in rs:
            out.append(_row(group="world", list=WORLD_NAMES[w], key=f"world:{w}", slug=s, code=c, note=n, src="worlds.yaml"))
    for p, rs in WIKIDATA.items():
        group = "drink" if KIND_BY_SLUG.get(p) == "drink" else "food"
        for s, c, n in rs:
            out.append(_row(group=group, list=PRODUCT_NAMES.get(p, p) + " (Wikidata ingredients)", key=f"wikidata:{p}",
                            slug=s, code=c, note=n, src="presence_wikidata.yaml"))
    return out


def words(code):
    return WHEN[code[2:]] if code.startswith("F:") else WORD[code]


def pill(code):
    cls = "roast" if code.startswith("F:") else CLS[code]
    return f'<span class="mark mark--{cls}">{html.escape(words(code))}</span>'


def mol(slug):
    return (f'<a class="mol" href="https://moleculefinder.com/m/{slug}">{html.escape(TITLES.get(slug, slug))}</a>')


def row_html(r, show_list=False, reason=None):
    group = {"food": "Food", "drink": "Drink", "product": "Product", "world": "World"}[r["group"]]
    where = f'<span class="where">{group} · {html.escape(r["list"])}</span>' if show_list else ""
    why = reason if reason is not None else r["note"]
    return (f'<div class="r">{where}<div class="m">{mol(r["slug"])}</div><div class="k">{pill(r["code"])}</div>'
            f'<div class="why">{html.escape(why)}</div></div>')


R = rows()
counts = defaultdict(int)
for r in R:
    counts["formed" if r["code"].startswith("F:") else CLS[r["code"]]] += 1
corrected = [r for r in R if (r["key"], r["slug"]) in CORRECTED]
assert len(corrected) == len(CORRECTED), "a corrected entry is missing from the seeds"
assert not any("not yet checked" in r["note"].lower() for r in R)
formed = [r for r in R if r["code"].startswith("F:")]
body = [r for r in R if r["code"] == "B"]
nones = [r for r in R if r["code"] == "X"]
by_mol = defaultdict(list)
for r in R:
    by_mol[r["slug"]].append(r)
mixed = {s: rs for s, rs in by_mol.items() if len({words(x["code"]) for x in rs}) > 1}
labels = sum(1 for p in PRODUCTS for m in p["molecules"] if m["role"] in ("active", "inactive"))
classes = sum(1 for p in PRODUCTS for m in p["molecules"] if m["role"] == "class")
label_pages = sum(1 for p in PRODUCTS if p["source"]["type"] == "dailymed")

parts = []
A = parts.append
A("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Presence marks review</title><meta name="robots" content="noindex"><style>
:root{--bg:#0e2233;--bg-deep:#09161e;--panel:#12314a;--panel-2:rgba(9,22,34,.35);--line:#244a63;--line-inner:#1b3a50;
--ink:#dbe9f2;--ink-2:#b4cddd;--muted:#86a7bd;--faint:#5f8098;--accent:#7fc4e8;--accent-hover:#a6d6f2;--found:#e9a23b;
--bucket-body:#e6a94b;--bucket-plant:#a6c556;--bucket-everyday:#7d94ef;--radius:4px;--maxw:1120px;
--font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--font-mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:400 17px/1.6 var(--font-sans);-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{color:var(--accent-hover);text-decoration:underline}
p{margin:0 0 .8rem}
.wrap{max-width:var(--maxw);margin:0 auto;padding-inline:32px}
h1,h2,h3{margin:0;font-weight:650;letter-spacing:-.01em}
.site-head{position:sticky;top:0;z-index:20;background:var(--bg-deep);border-bottom:1px solid var(--line)}
.site-head__in{height:56px;display:flex;align-items:center;gap:2rem;overflow-x:auto}
.brand__word{font:600 16px/1 var(--font-mono);color:var(--ink);white-space:nowrap}.brand__word b{color:var(--accent);font-weight:600}
.site-nav{display:flex;gap:1.25rem;font:500 15px/1 var(--font-sans);white-space:nowrap}
.site-nav a{color:var(--ink-2);padding:6px 0}
.mark{display:inline-flex;align-items:center;gap:7px;font:600 14px/1.2 var(--font-sans);padding:5px 11px;border-radius:999px;border:1px solid;white-space:nowrap}
.mark::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor}
.mark--natural{color:var(--bucket-plant);border-color:color-mix(in srgb,var(--bucket-plant) 50%,transparent)}
.mark--roast{color:#e0a070;border-color:rgba(224,160,112,.5)}
.mark--added{color:#97a9f3;border-color:color-mix(in srgb,var(--bucket-everyday) 55%,transparent)}
.mark--added::before{background:transparent;border:2px solid currentColor;width:6px;height:6px}
.mark--body{color:var(--bucket-body);border-color:color-mix(in srgb,var(--bucket-body) 50%,transparent)}
.mark--none{color:var(--muted);border-style:dashed;border-color:var(--faint)}
.mark--none::before{background:transparent}
.hero{padding:28px 0 8px}
.hero h1{font:650 40px/1.1 var(--font-mono);letter-spacing:-.03em;margin:0 0 .7rem}
.lede{font-size:19px;color:var(--ink);margin:0 0 1rem}
.note{border:1px dashed color-mix(in srgb,var(--found) 70%,transparent);border-radius:var(--radius);color:#f3c27a;background:rgba(233,162,59,.06);font:400 16px/1.5 var(--font-sans);padding:10px 14px;margin:12px 0}
.note b{font-weight:600}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.stat{border:1px solid var(--line);border-radius:var(--radius);background:var(--panel-2);padding:10px 14px;min-width:120px}
.stat b{display:block;font:650 26px/1.1 var(--font-mono)}
.stat span{font-size:14px;color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0}
.sec{padding:36px 0 4px;border-top:1px solid var(--line-inner);margin-top:32px}
.sec>h2{font:650 28px/1.25 var(--font-sans);margin:0 0 10px}
.sec>p{color:var(--ink-2)}
.list{margin:22px 0 0}
.list>h3{font:650 20px/1.3 var(--font-mono);margin:0 0 4px}
.list>h3 small{font:400 14px/1 var(--font-sans);color:var(--muted);margin-left:8px}
.rows{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel-2)}
.r{display:grid;grid-template-columns:minmax(150px,1fr) auto minmax(0,2.2fr);gap:6px 16px;align-items:baseline;padding:10px 16px;border-top:1px solid var(--line-inner)}
.r:first-child{border-top:0}
.r .where{grid-column:1/-1;font:500 13px/1.2 var(--font-sans);color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.mol{font:600 16px/1.3 var(--font-mono)}
.why{font-size:15.5px;line-height:1.5;color:var(--ink-2)}
.ask{margin:0;padding-left:1.2rem}.ask li{margin:0 0 .7rem;color:var(--ink-2)}.ask b{color:var(--ink)}
.toc{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:15px;margin:6px 0 0}
.foot{border-top:1px solid var(--line);margin-top:4rem;background:var(--bg-deep);color:var(--faint);font-size:13px;padding:1.2rem 0 2rem}
@media (max-width:720px){
 html,body{font-size:16.5px}.wrap{padding-inline:16px}
 .hero h1{font-size:30px}
 .r{grid-template-columns:1fr auto}.r .why{grid-column:1/-1}
}
</style></head><body>
<header class="site-head"><div class="wrap site-head__in"><span class="brand__word">molecule<b>finder</b> · review</span>
<nav class="site-nav"><a href="#corrected">Corrected</a><a href="#second">Second look</a><a href="#asks">Rulings</a><a href="#all">Every mark</a><a href="#rule">By rule</a></nav></div></header>
<main class="wrap">
""")
A(f"""<section class="hero"><h1>Presence marks: how each molecule comes to be there</h1>
<p class="lede">Every curated food, drink, product and world entry now says, by hand, how its molecule comes to be in it.
Build plan everyday chemistry, phase 1. Nothing here is on the site yet: the marks are in the data, and no page renders them
until the door and molecule pages (phases 7 and 8). <b>Approved by Garrett on 2026-11-10 with the corrections below</b>;
this is the page regenerated from the corrected seeds, as it ships.</p>
<div class="stats">
<div class="stat"><b>{len(R)}</b><span>entries marked by hand</span></div>
<div class="stat"><b>{counts['natural']}</b><span>Naturally present</span></div>
<div class="stat"><b>{counts['added']}</b><span>Added by the maker</span></div>
<div class="stat"><b>{counts['formed']}</b><span>Formed when ...</span></div>
<div class="stat"><b>{counts['body']}</b><span>Made by your body</span></div>
<div class="stat"><b>{counts['none']}</b><span>No mark, each with a reason</span></div>
</div>
<div class="legend">{pill('N')}{pill('A')}{pill('B')}{pill('F:roasted')}{pill('F:baked')}{pill('F:cooked')}{pill('F:cured')}{pill('F:aged')}{pill('F:crushed')}{pill('F:fermentation')}{pill('X')}</div>
<p style="margin-top:14px;color:var(--ink-2)">The list of words is closed: a mark is one of the four, or "formed" with one of the seven
endings shown, or no mark with a written reason. The build stops if a curated entry has no mark or a word outside the list.
Each line's reason is the one-line note that a later phase shows under Sources and notes, so it is site copy too.
{len(R)} entries are 329 food and drink list entries, 83 product list entries, 60 world entries and 49 Wikidata ingredient rows;
the 20 sweetener and staple entries that sit both in a molecule's own curated file and in a food list carry one mark,
written once and checked equal by the build.</p>
<div class="note"><b>Approved, 2026-11-10.</b> Garrett's corrections changed {len(corrected)} entries (listed first) and added
"crushed" to the closed list. No entry carries "not yet checked" any more, and a test holds it so. Removals he ruled
(tannic acid from tea, wine and the wine world; 2-nonenal from the smell after rain; ethyl maltol from fresh-baked bread;
glucose and fructose from table sugar) and the glutamate wording are queued for phase 2.</div>
</section>
""")

# Garrett's corrections
A(f'<section class="sec" id="corrected"><h2>Garrett\'s corrections, 2026-11-10 ({len(corrected)})</h2>'
  "<p>Each entry as it now reads in the seeds, with what he ruled.</p><div class=\"rows\">")
for r in corrected:
    A(row_html(r, show_list=True, reason=r["note"] + " (" + CORRECTED[(r["key"], r["slug"])] + ")"))
A("</div></section>")

# Second look
A('<section class="sec" id="second"><h2>Worth a chemist\'s second look</h2>'
  "<p>Every formed mark, every body mark, every no-mark with a written reason, and every molecule that is marked "
  "differently in two places.</p>")
for title, rs in ((f"Formed ({len(formed)})", formed), (f"Made by your body ({len(body)})", body),
                  (f"No mark, with a written reason ({len(nones)})", nones)):
    A(f'<div class="list"><h3>{title}</h3><div class="rows">')
    for r in rs:
        A(row_html(r, show_list=True))
    A("</div></div>")
A(f'<div class="list"><h3>Marked differently in two places ({len(mixed)} molecules)</h3>'
  "<p style=\"color:var(--ink-2);margin:4px 0 10px\">Expected where the chemistry differs (glutamate is natural in "
  "mushrooms, formed in aged cheese and fermented soy, added to snacks); each is listed so a slip shows.</p>")
for s in sorted(mixed, key=lambda x: TITLES.get(x, x).lower()):
    A(f'<div class="list" style="margin-top:14px"><h3>{html.escape(TITLES.get(s, s))}<small>{len(mixed[s])} entries</small></h3><div class="rows">')
    for r in mixed[s]:
        A(row_html(r, show_list=True))
    A("</div></div>")
A("</div></section>")

# Questions
A("""<section class="sec" id="asks"><h2>Rulings, 2026-11-10</h2><ol class="ask">
<li><b>"Formed when crushed" joins the closed list.</b> Allicin and allyl isothiocyanate in A spicy dinner are marked formed,
crushed, keeping their reasons.</li>
<li><b>Queued for phase 2 (the copy sweep), not done here:</b> remove tannic acid from the Tea and Wine lists and the wine
world; remove 2-nonenal from The smell after rain; remove ethyl maltol from Fresh-baked bread; remove glucose and fructose
from the Table sugar list; and where Cheese, Soy sauce and Mushrooms list monosodium glutamate, the page wording says
glutamate (free glutamate, the taste of MSG), not MSG.</li>
<li><b>Folic acid in leafy greens and romaine lettuce</b> stays unmarked, as recommended (folates, not folic acid).</li>
</ol></section>""")

# Every mark
order = (("food", "Foods"), ("drink", "Drinks"), ("product", "Products"), ("world", "Worlds"))
A('<section class="sec" id="all"><h2>Every mark, by food, drink, product and world</h2>'
  "<p>Each list in the order its seed file holds it. Molecule names link to the live molecule page.</p><div class=\"toc\">")
lists = defaultdict(list)
for r in R:
    lists[(r["group"], r["key"])].append(r)
for g, gname in order:
    A(f'<a href="#g-{g}">{gname}</a>')
A("</div>")
for g, gname in order:
    keys = [k for (gg, k) in lists if gg == g]
    A(f'<h2 id="g-{g}" style="font:650 24px/1.3 var(--font-sans);margin:30px 0 0">{gname} ({sum(len(lists[(g, k)]) for k in keys)})</h2>')
    for k in keys:
        rs = lists[(g, k)]
        A(f'<div class="list"><h3>{html.escape(rs[0]["list"])}<small>{len(rs)} · {rs[0]["src"]}</small></h3><div class="rows">')
        for r in rs:
            A(row_html(r))
        A("</div></div>")
A("</section>")

A(f"""<section class="sec" id="rule"><h2>Marked by rule, not by hand</h2>
<p><b>{labels:,} label rows on {label_pages} label pages carry {pill('A')}</b> by rule: a DailyMed label is the maker's own
declaration of what it put in, actives and inactives alike. <b>The PFAS class page's {classes} rows carry no mark</b>, with
the reason "A class page: its molecules share a structure, not a source." Neither is listed above.</p>
<p>A Wikidata ingredient row that a weekly refresh adds with no mark is exported unmarked (a page will say "Not marked"),
listed in the ETL's <code>data/seed/presence_unmarked.json</code> and the run's summary, and never fails the run.
Today that list is empty.</p></section>
</main><footer class="foot"><div class="wrap">Review page for Garrett, built 2026-11-09, regenerated 2026-11-10 after his corrections, from the ETL branch presence-2026-11
(read from the seeds by scripts/presence_review.py). Not part of the site.</div></footer></body></html>
""")
OUT.write_text("".join(parts))
assert "—" not in OUT.read_text() and "–" not in OUT.read_text()
print(OUT, len(OUT.read_text()), "bytes;", len(R), "rows;", len(corrected), "corrected;", len(mixed), "mixed molecules")
