"""Build the copy sweep review page (build plan everyday chemistry 2026-11, phase 2) for Garrett.

Reads the sweep record (scripts/copy_sweep_2026_11.yaml), main's seeds (the text before, from git), the seeds
as they are now, sources/seeds/claims_allowed.yaml and the snapshot, and writes one self-contained HTML page:
Garrett's rulings of 2026-11-10 with the final text first, then every rewrite before and after with its basis,
then the roster removals and the pages each moves, then (collapsed) every line that keeps a claim word and its
basis. It refuses to write when the record's text and the seeds disagree.
Run from the ETL root after any change to the record or the seeds:
    ./.venv/bin/python3 scripts/copy_sweep_review.py [out.html]
The default output is the web repo's docs/design/copy-sweep-review-2026-11.html.
"""
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from moleculefinder_etl.transform import claims

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "moleculefinder-web" / "docs" / "design" / "copy-sweep-review-2026-11.html"
SNAP = ROOT / "data" / "snapshots"
REC = yaml.safe_load((ROOT / "scripts" / "copy_sweep_2026_11.yaml").read_text())
SEEDS = "moleculefinder_etl/sources/seeds"
BASE = "main"
# The branch as Garrett reviewed it (before his five line fixes of 2026-11-10).
REVIEWED = "c889f21"


def _git(path: str) -> str:
    return subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout


OLD_WIM = yaml.safe_load(_git(f"{SEEDS}/why_it_matters.yaml"))
OLD_CMP = yaml.safe_load(_git(f"{SEEDS}/comparisons.yaml"))
NEW_CMP = yaml.safe_load((ROOT / SEEDS / "comparisons.yaml").read_text())
TITLES = {}
for p in (SNAP / "molecules").glob("*.json"):
    d = json.loads(p.read_text())
    TITLES[d["slug"]] = d["title"]
ALLOWED = claims.load_allowed()
CORPUS = {(k, key): t for k, key, t in claims.corpus()}
esc = html.escape

# The record must say exactly what the seeds say, or the page would show text that will not ship.
_mismatch = [s for s, e in REC["why_it_matters"].items() if claims.normalise(e["new"]) != CORPUS[("why_it_matters", s)]]
_mismatch += [s for s, e in REC["editorial"].items() if claims.normalise(e["new"]) != CORPUS[("editorial", s)]]
_mismatch += [e["pair"] for e in REC["comparison"] if claims.normalise(e["new"]) not in CORPUS[("comparison", e["pair"])]]
_mismatch += [e["pair"] for e in REC["answer"] if claims.normalise(e["new"]) != CORPUS[("answer", e["pair"])]]
assert not _mismatch, f"the record and the seeds disagree: {_mismatch}"


def reviewed_wim(slug):
    return claims.normalise(yaml.safe_load(subprocess.run(
        ["git", "show", f"{REVIEWED}:{SEEDS}/why_it_matters.yaml"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)[slug])


def old_editorial(slug):
    d = yaml.safe_load(_git(f"moleculefinder_etl/sources/curated/{slug}.yaml"))
    return claims.normalise(d.get("editorial"))


def hl(text):
    """Escape, then mark each claim word."""
    return claims.CLAIM_RE.sub(lambda m: f"<mark>{m.group(0)}</mark>", esc(text))


def pair_title(pair):
    a, b = pair.split("/")
    return f"{TITLES.get(a, a)} vs {TITLES.get(b, b)}"


def mlink(slug):
    return f'<a href="https://moleculefinder.com/m/{slug}">{esc(TITLES.get(slug, slug))}</a>'


def vlink(pair):
    return f'<a href="https://moleculefinder.com/vs/{pair.replace("/", "-vs-")}">{esc(pair_title(pair))}</a>'


# ── counts ───────────────────────────────────────────────────────────────────
old_lines = [("why_it_matters", k, claims.normalise(v)) for k, v in OLD_WIM.items()]
for pair, v in OLD_CMP.items():
    old_lines += [("comparison", pair, claims.normalise(v["text"])), ("answer", pair, claims.normalise(v["answer"]))]
EDITORIAL_COUNT = sum(1 for k, _ in CORPUS if k == "editorial")
old_ed_hits = sum(bool(claims.words_in(old_editorial(key) if key in REC["editorial"] else text))
                  for (k, key), text in CORPUS.items() if k == "editorial")
examined = len(old_lines) + EDITORIAL_COUNT
hits_before = sum(1 for _, _, t in old_lines if claims.words_in(t)) + old_ed_hits
n_wim, n_ed, n_cmp, n_ans = len(REC["why_it_matters"]), len(REC["editorial"]), len(REC["comparison"]), len(REC["answer"])
n_pairs = len({c["pair"] for c in REC["comparison"]})
kept = len(ALLOWED)
held = sorted(key for (k, key), e in ALLOWED.items() if e["basis"] == "held")
by_basis = {}
for e in ALLOWED.values():
    by_basis[e["basis"]] = by_basis.get(e["basis"], 0) + 1
DESC_CHANGED = sorted(REC["why_it_matters"])

parts = []
A = parts.append
A("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Copy sweep review</title><meta name="robots" content="noindex"><style>
:root{--bg:#0e2233;--bg-deep:#09161e;--panel:#12314a;--panel-2:rgba(9,22,34,.35);--line:#244a63;--line-inner:#1b3a50;
--ink:#dbe9f2;--ink-2:#b4cddd;--muted:#86a7bd;--faint:#5f8098;--accent:#7fc4e8;--accent-hover:#a6d6f2;--found:#e9a23b;
--ok:#a6c556;--bad:#e58a7a;--radius:4px;--maxw:1120px;
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
.hero{padding:28px 0 8px}
.hero h1{font:650 40px/1.1 var(--font-mono);letter-spacing:-.03em;margin:0 0 .7rem}
.lede{font-size:19px;color:var(--ink);margin:0 0 1rem}
.note{border:1px dashed color-mix(in srgb,var(--found) 70%,transparent);border-radius:var(--radius);color:#f3c27a;background:rgba(233,162,59,.06);font:400 16px/1.5 var(--font-sans);padding:10px 14px;margin:12px 0}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.stat{border:1px solid var(--line);border-radius:var(--radius);background:var(--panel-2);padding:10px 14px;min-width:120px}
.stat b{display:block;font:650 26px/1.1 var(--font-mono)}
.stat span{font-size:14px;color:var(--muted)}
.sec{padding:36px 0 4px;border-top:1px solid var(--line-inner);margin-top:32px}
.sec>h2{font:650 28px/1.25 var(--font-sans);margin:0 0 10px}
.sec>p{color:var(--ink-2)}
.card{border:1px solid var(--line);border-radius:8px;background:var(--panel-2);padding:14px 18px;margin:14px 0}
.card h3{font:650 18px/1.3 var(--font-mono);margin:0 0 8px}
.card h3 small{font:400 14px/1 var(--font-sans);color:var(--muted);margin-left:8px}
.lbl{display:block;font:600 12.5px/1.2 var(--font-sans);color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:10px 0 3px}
.before{color:var(--ink-2);text-decoration:line-through;text-decoration-color:color-mix(in srgb,var(--bad) 60%,transparent)}
.after{color:var(--ink)}
.fails{color:#f0b3a8;font-size:15.5px}
.basis{color:#cfe3a3;font-size:15.5px}
.cand{border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:10px 0}
.cand--pick{border-color:var(--ok);box-shadow:inset 3px 0 0 var(--ok)}
.cand--plan{opacity:.75;border-style:dashed}
.tag{display:inline-block;font:600 12px/1 var(--font-sans);padding:4px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted);margin-left:6px;vertical-align:middle}
.tag--pick{color:var(--ok);border-color:var(--ok)}
.rec{color:var(--ink);font-weight:600}
mark{background:rgba(233,162,59,.22);color:#f6d29b;padding:0 2px;border-radius:2px}
.pages{font:400 14.5px/1.7 var(--font-mono);color:var(--ink-2)}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-top:1px solid var(--line-inner)}
th{color:var(--muted);font:600 13px/1.2 var(--font-sans);text-transform:uppercase;letter-spacing:.04em}
td.k{font:600 14.5px/1.4 var(--font-mono);white-space:nowrap}
.b{font:600 12.5px/1 var(--font-sans);padding:3px 7px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.b--data{color:var(--found);border-color:var(--found)}.b--science{color:var(--accent)}.b--history{color:#c4a8ef}
.b--ordinary{color:var(--muted)}.b--held{color:var(--bad);border-color:var(--bad)}
details{border:1px solid var(--line);border-radius:8px;background:var(--panel-2);margin:14px 0}
details>summary{cursor:pointer;padding:12px 16px;font:600 17px/1.3 var(--font-sans)}
details>div{padding:0 16px 14px;overflow-x:auto}
.toc{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:15px;margin:6px 0 0}
.foot{border-top:1px solid var(--line);margin-top:4rem;background:var(--bg-deep);color:var(--faint);font-size:13px;padding:1.2rem 0 2rem}
@media (max-width:720px){
 html,body{font-size:16.5px}.wrap{padding-inline:16px}
 .hero h1{font-size:30px}
 td.k{white-space:normal}
}
</style></head><body>
<header class="site-head"><div class="wrap site-head__in"><span class="brand__word">molecule<b>finder</b> · review</span>
<nav class="site-nav"><a href="#garrett">Your rulings</a><a href="#rewrites">Rewrites</a><a href="#removals">Removals</a><a href="#kept">Kept, with basis</a></nav></div></header>
<main class="wrap">
""")
A(f"""<section class="hero"><h1>Copy sweep: no line claims more than we can show</h1>
<p class="lede">Every curated line on the site, checked for "only", "first", "most", "leading", "largest", "world's", "never" and
"always". A line keeps the word when our own data shows it (and the build checks it), when it is a standard, datable fact of
chemistry or history, or when the word ranks nothing. A claim about how common something is, what people do, or a health
outcome is rewritten, and a rewrite has to stay as interesting as the line it replaces: a specific, true fact, not a list of
where the molecule turns up. Build plan everyday chemistry, phase 2, with your amendment of 2026-11-10. <b>Approved by you on
2026-11-10 with the rulings in section 1, which this page now shows applied; it deploys on your word.</b></p>
<div class="stats">
<div class="stat"><b>{examined:,}</b><span>lines examined</span></div>
<div class="stat"><b>{hits_before}</b><span>carried a claim word</span></div>
<div class="stat"><b>{n_wim + n_ed + n_cmp + n_ans}</b><span>rewrites</span></div>
<div class="stat"><b>{kept}</b><span>keep a word, with basis</span></div>
<div class="stat"><b>{n_ans}</b><span>answer lines changed, by your ruling</span></div>
</div>
<p class="note">Examined: {len(OLD_WIM)} why-it-matters lines, {EDITORIAL_COUNT} editorials, {len(OLD_CMP)} comparison paragraphs and
their {len(OLD_CMP)} answer lines. Rewritten: {n_wim} why-it-matters lines, {n_ed} editorials, {n_cmp} sentences in {n_pairs}
comparison paragraphs and {n_ans} answer lines. Kept: {by_basis.get('science', 0)} as standard science, {by_basis.get('history', 0)}
as datable history (an agency's finding named in the line counts here), {by_basis.get('ordinary', 0)} where the word ranks nothing,
{by_basis.get('data', 0)} on our own data (checked by the build every run), {by_basis.get('held', 0)} answer line held as it is, by
your ruling. Unchanged by design: every /vs title, H1 and FAQ question, every other /vs description and answer line, every
molecule page title, the molecule of the week's title and description, and every other page title (checked page by page
against a build of main with the web's scripts/frozen-text.mjs: the only differences are the two answer lines you ruled on, and
six titles whose molecule count follows your removals, which you accepted on 2026-11-10).</p>
</section>""")

# ── 1. Garrett's rulings, 2026-11-10 ─────────────────────────────────────────
A('<section class="sec" id="garrett"><h2>1. Your rulings, 2026-11-10, applied</h2><p>You approved this page with the rulings '
  'below. Each shows the text that ships.</p>')
ed = REC["editorial"]["caffeine"]
pick = next(c for c in ed["candidates"] if c.get("pick"))
A(f'<div class="card"><h3>Caffeine\'s editorial: candidate A <small>/m/caffeine, the paragraph under the facts</small></h3>'
  f'<span class="lbl">Before</span><p class="before">{hl(old_editorial("caffeine"))}</p>'
  f'<span class="lbl">Ships</span><p class="after">{hl(pick["text"])}</p>'
  f'<span class="lbl">Basis</span><p class="basis">{esc(ed["basis"])}</p></div>')

A("""<div class="card"><h3>Table sugar: the 410 stands</h3>
<p>Glucose and fructose are off the Table sugar list, which leaves sucrose alone, under the three-molecule gate. <b>/whats-in/table-sugar
answers 410</b> (its row removed from products.yaml, the path in lib/gone.ts); <b>/in/table-sugar stays</b>, with sucrose alone, and the
classroom's sugar lesson links it. The sitemap goes 1,712 to 1,711.</p></div>""")

A("""<div class="card"><h3>Glutamate on Cheese, Soy sauce and Mushrooms: accepted as built</h3>
<p>The three lists name <b>Glutamic acid</b> with the note <b>"free glutamate, the taste of MSG"</b>, in place of monosodium glutamate. The
presence marks are unchanged. Monosodium glutamate keeps Processed snacks, where the maker adds it.</p></div>""")

A('<div class="card"><h3>Comparison answer lines <small>each is its page\'s description</small></h3>')
ANSWER_RULINGS = {
    "hydrochlorothiazide/furosemide": "Your ruling: fixed now, to your wording. The one /vs description you allowed to change.",
    "formaldehyde/acetaldehyde": "Your choice in the deploy session (asked because it collides with the furosemide ruling): brought into line with the acetaldehyde ruling, so two /vs descriptions change. Trimmed to stay under 160 characters.",
}
for e in REC["answer"]:
    A(f'<span class="lbl">{vlink(e["pair"])}</span><p class="before">{hl(OLD_CMP[e["pair"]]["answer"])}</p>'
      f'<p class="after">{hl(e["new"])}</p><p class="rec">{esc(ANSWER_RULINGS[e["pair"]])}</p>')
A(f'<span class="lbl">{vlink("meloxicam/ibuprofen")}</span><p class="after">{hl(OLD_CMP["meloxicam/ibuprofen"]["answer"])}</p>'
  '<p class="rec">Your ruling: it stays as it is.</p></div>')

FIXES = (
    ("doxorubicin", "The colour comes from the molecule's own ring system, not the bacterium's."),
    ("radon", "Keep the density fact and restore the health fact, with its source named. Your 214-character wording trimmed to 200 (the description limit), facts kept: \"where, as the densest of the gaseous elements, it gathers\" became \"and, as the densest gaseous element, gathers\"."),
    ("acrylonitrile-butadiene-styrene", "LEGO bricks are glossy, not matte, and the line already said gloss."),
    ("acetaldehyde", "\"A large part of a hangover\" overstates disputed science."),
)
A('<div class="card"><h3>Five line fixes from your review</h3>')
for slug, why in FIXES:
    A(f'<span class="lbl">{mlink(slug)}</span><p class="before">{hl(reviewed_wim(slug))}</p>'
      f'<p class="after">{hl(REC["why_it_matters"][slug]["new"])}</p><p class="rec">{esc(why)}</p>')
A(f'<span class="lbl">{mlink("nicotine")}, editorial</span><p class="before">{hl(old_editorial("nicotine"))}</p>'
  f'<p class="after">{hl(REC["editorial"]["nicotine"]["new"])}</p>'
  '<p class="rec">"One of the fastest-clearing drugs people use" is a ranking our data cannot show; it now says plainly that it clears fast.</p>')
A('<p>Radon keeps "only" ("second only to smoking") as an attributed finding of a US government agency, which the rule now says in '
  'its own text, as with suzetrigine\'s FDA line.</p></div>')

A('<div class="card"><h3>Every acetaldehyde hangover line, brought into line</h3><p>Each now says <b>"long blamed for part of a '
  'hangover"</b>; a test fails if any curated line ties acetaldehyde to a hangover in other words. No list note mentions it.</p><ul>'
  f'<li>{mlink("acetaldehyde")}, why it matters (and so its page description): {hl(REC["why_it_matters"]["acetaldehyde"]["new"])}</li>'
  f'<li>{vlink("formaldehyde/acetaldehyde")}, paragraph: {hl(next(e["new"] for e in REC["comparison"] if e["pair"] == "formaldehyde/acetaldehyde"))}</li>'
  f'<li>{vlink("formaldehyde/acetaldehyde")}, answer line (the page\'s description): {hl(next(e["new"] for e in REC["answer"] if e["pair"] == "formaldehyde/acetaldehyde"))}</li>'
  '</ul></div>')
A('</section>')

A('<section class="sec" id="found"><h2>Found while checking, and fixed</h2>')
A("""<div class="card"><ul>
<li><b>Two lines were wrong in our own data:</b> tirzepatide's "the largest medicine on this site by molecular weight" (tesamorelin,
5,136, and insulin, 5,808, are heavier) and the semaglutide and tirzepatide paragraph's "the two largest molecules in this catalog"
(inulin, insulin and tesamorelin outweigh both).</li>
<li><b>Other facts that did not hold:</b> insulin was not the first human protein made by engineered bacteria (somatostatin was);
fluoxetine was not the first SSRI on any market (zimelidine and fluvoxamine in Europe); olive oil does not stay liquid in a fridge;
high-fructose corn syrup can be 42 percent fructose; a start-up source holds micrograms of californium, not a gram; the CDC lists a
second plant-derived repellent beside PMD; celecoxib favours COX-2, it does not act on it alone.</li>
<li><b>Furosemide's paragraph</b> said the thick ascending limb is "where the bulk of" sodium reabsorption happens; it takes back about a
quarter (the proximal tubule about two thirds). Corrected, though it carried no claim word.</li>
<li><b>"Every molecule in coffee":</b> the new completeness check found this link label on all 33 curated food and drink pages. A
curated list is a selection, so it now reads "Browse the coffee list" (and so on). Nothing else on those pages changes.</li>
<li><b>Sulfuric acid:</b> a first rewrite named its old name, oil of vitriol, which is one of its display synonyms, so the title would
have become "Sulfuric acid (Oil of vitriol)". Rewritten without it; no title moves.</li>
</ul></div></section>""")

# ── 2. Rewrites ──────────────────────────────────────────────────────────────
A(f'<section class="sec" id="rewrites"><h2>2. Every rewrite</h2><p>Before, after, why the old line fails, and the basis for every clause of '
  f'the new one. A why-it-matters line leads its molecule page\'s description, so each of these {n_wim} pages gets a new meta '
  f'description, as expected; no title changes. Claim words are marked.</p>'
  f'<div class="toc"><a href="#r-wim">Why it matters ({n_wim})</a><a href="#r-ed">Editorials ({n_ed})</a><a href="#r-cmp">Comparison paragraphs ({n_cmp})</a><a href="#r-ans">Answer lines ({n_ans})</a></div>')
A('<h3 id="r-wim" style="margin:24px 0 0;font:650 22px/1.3 var(--font-sans)">Why it matters</h3>')
for slug in sorted(REC["why_it_matters"], key=lambda s: TITLES.get(s, s).lower()):
    e = REC["why_it_matters"][slug]
    A(f'<div class="card"><h3>{mlink(slug)} <small>why it matters, and the page description</small></h3>'
      f'<span class="lbl">Before</span><p class="before">{hl(OLD_WIM[slug])}</p>'
      f'<span class="lbl">After</span><p class="after">{hl(e["new"])}</p>'
      f'<span class="lbl">Why the old line fails</span><p class="fails">{esc(e["fails"])}</p>'
      f'<span class="lbl">Basis</span><p class="basis">{esc(e["basis"])}</p></div>')
A('<h3 id="r-ed" style="margin:28px 0 0;font:650 22px/1.3 var(--font-sans)">Editorials</h3>')
for slug, e in REC["editorial"].items():
    A(f'<div class="card"><h3>{mlink(slug)} <small>editorial</small></h3>'
      f'<span class="lbl">Before</span><p class="before">{hl(old_editorial(slug))}</p>'
      f'<span class="lbl">After</span><p class="after">{hl(e["new"])}</p>'
      f'<span class="lbl">Why the old one fails</span><p class="fails">{esc(e["fails"])}</p>'
      f'<span class="lbl">Basis</span><p class="basis">{esc(e["basis"])}</p></div>')
A('<h3 id="r-cmp" style="margin:28px 0 0;font:650 22px/1.3 var(--font-sans)">Comparison paragraphs <small style="font:400 15px var(--font-sans);color:var(--muted)">one sentence each</small></h3>')
for e in REC["comparison"]:
    A(f'<div class="card"><h3>{vlink(e["pair"])}</h3>'
      f'<span class="lbl">Before</span><p class="before">{hl(e["old"])}</p>'
      f'<span class="lbl">After</span><p class="after">{hl(e["new"])}</p>'
      f'<span class="lbl">Why the old sentence fails</span><p class="fails">{esc(e["fails"])}</p>'
      f'<span class="lbl">Basis</span><p class="basis">{esc(e["basis"])}</p></div>')
A('<h3 id="r-ans" style="margin:28px 0 0;font:650 22px/1.3 var(--font-sans)">Comparison answer lines <small style="font:400 15px var(--font-sans);color:var(--muted)">the page\'s description; only where you ruled</small></h3>')
for e in REC["answer"]:
    A(f'<div class="card"><h3>{vlink(e["pair"])}</h3>'
      f'<span class="lbl">Before</span><p class="before">{hl(OLD_CMP[e["pair"]]["answer"])}</p>'
      f'<span class="lbl">After</span><p class="after">{hl(e["new"])}</p>'
      f'<span class="lbl">Why the old line fails</span><p class="fails">{esc(e["fails"])}</p>'
      f'<span class="lbl">Basis</span><p class="basis">{esc(e["basis"])}</p></div>')
A('</section>')

# ── 3. Removals ──────────────────────────────────────────────────────────────
REMOVALS = [
    ("Tannic acid off Tea, Wine and A glass of wine (list and journey)",
     "Tea and wine tannins are a different family from tannic acid.",
     ["/whats-in/tea", "/whats-in/wine", "/whats-in/glass-of-wine", "/in/tea", "/in/wine", "/roam/glass-of-wine", "/m/tannic-acid"]),
    ("2-Nonenal off The smell after rain", "No basis found for it there. It stays on Beer, where it forms as beer goes stale.",
     ["/whats-in/after-the-rain", "/roam/after-the-rain", "/m/2-nonenal"]),
    ("Ethyl maltol off Fresh-baked bread (list and journey)", "A synthetic flavouring; baking forms maltol, not ethyl maltol.",
     ["/whats-in/fresh-bread", "/roam/fresh-bread", "/m/ethyl-maltol"]),
    ("Glucose and fructose off Table sugar", "Not in the sugar itself; sucrose splits into them when digested or heated with acid.",
     ["/in/table-sugar", "/whats-in/table-sugar (410)", "/m/glucose", "/m/fructose", "/m/sucrose", "/classroom", "/whats-in (the index)", "/ (the count, 425 to 424 products)"]),
    ("Glutamate, not MSG, on Cheese, Soy sauce and Mushrooms", "Free glutamate is what those foods hold; MSG is the salt a maker adds.",
     ["/whats-in/cheese", "/whats-in/soy-sauce", "/whats-in/mushrooms", "/in/cheese", "/in/soy-sauce", "/in/mushrooms", "/m/glutamic-acid", "/m/monosodium-glutamate"]),
]
A('<section class="sec" id="removals"><h2>3. Your roster rulings, and the pages each moves</h2>'
  '<p>Each entry leaves with its presence mark (the marks file now holds 514 hand marks: natural 207, added 212, formed 57, body 17, none 21). '
  'Nothing still says "due to be removed".</p>')
for title, why, pages in REMOVALS:
    A(f'<div class="card"><h3>{esc(title)}</h3><p class="basis">{esc(why)}</p><span class="lbl">Pages it moves</span>'
      f'<p class="pages">{" · ".join(esc(p) for p in pages)}</p></div>')
A("""<div class="card"><h3>What a search engine is told at deploy</h3>
<p>IndexNow dry run against live main (b0c1412), with your review fixes: sitemap 1,712 to 1,711, <b>0 new, 385 changed, 1 removed</b>
(/whats-in/table-sugar, which answers 410): 83 molecule pages, 60 comparison pages, 230 product pages and the /whats-in index (each lists
a molecule whose line changed, or lost or gained one above), 6 lists, 3 worlds, the home page, /classroom and /embed. Six curated pages
change only in the link label ("Browse the coffee list") and the delta cannot see a label: breakfast cereal, chili peppers, coffee, eggs,
fish and tonic water are sent by hand at deploy (coffee is in the delta now as well, through acetaldehyde; sending it twice is harmless).</p></div>""")
A("""<div class="card"><h3>Found at the final check, and fixed with your word</h3><ul>
<li><b>Six titles carry a molecule count</b> that your removals change: What's in tea 11 to 10, What's in wine 21 to 20, A glass of wine 6
to 5 (its /whats-in and /roam pages), The smell after rain 4 to 3, Fresh-baked bread 6 to 5. You accepted them as they are.</li>
<li><b>/in/table-sugar's title would have read "In Table Sugar"</b>: sucrose's own row named the hub by capitalising its address, and with
glucose and fructose gone it was the only row left. Every food list now takes its name from the list itself, so the title stays "In
Table sugar". Five other rows had the same slip and now match their lists' own names on the molecule pages: Energy drinks (caffeine),
Chili peppers and Hot sauce (capsaicin), Soy sauce (glutamic acid), Black pepper (piperine). No title moves.</li>
</ul></div></section>""")

# ── 4. Kept ──────────────────────────────────────────────────────────────────
A(f'<section class="sec" id="kept"><h2>4. Lines that keep a claim word, and why</h2><p>{kept} lines, each pinned in '
  'sources/seeds/claims_allowed.yaml to the exact text of its line: a new line with one of the words, or an edit to one of these, stops the build '
  'until its basis is written down. A "data" line is also checked against the catalog on every run.</p>')
KIND_NAMES = {"why_it_matters": "Why it matters", "editorial": "Editorials", "comparison": "Comparison paragraphs", "answer": "Comparison answer lines"}
for kind in ("why_it_matters", "editorial", "comparison", "answer"):
    rows = sorted(((key, e) for (k, key), e in ALLOWED.items() if k == kind), key=lambda r: r[0])
    A(f'<details><summary>{KIND_NAMES[kind]} ({len(rows)})</summary><div><table><tr><th>Line</th><th>Basis</th><th>Why it stands</th></tr>')
    for key, e in rows:
        text = CORPUS[(kind, key)]
        if kind == "comparison":
            text = " ".join(s for s in re.split(r"(?<=[.!?])\s+", text) if claims.CLAIM_RE.search(s))
        name = mlink(key) if kind in ("why_it_matters", "editorial") else vlink(key)
        A(f'<tr><td><div class="k">{name}</div>{hl(text)}</td><td><span class="b b--{e["basis"]}">{e["basis"]}</span></td>'
          f'<td>{esc(e["why"])}</td></tr>')
    A("</table></div></details>")
A("</section>")
A(f"""</main><footer class="foot"><div class="wrap">Generated by moleculefinder-etl/scripts/copy_sweep_review.py from
scripts/copy_sweep_2026_11.yaml, {BASE}'s seeds and sources/seeds/claims_allowed.yaml. Branch copy-sweep-2026-11 in both repos; approved by Garrett 2026-11-10.
Molecule pages whose description changes: {", ".join(DESC_CHANGED)}.</div></footer></body></html>
""")
text = "".join(parts)
assert "—" not in text and "–" not in text, "no dashes on the review page"
OUT.write_text(text)
print(f"wrote {OUT} ({len(text):,} bytes)")
