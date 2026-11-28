"""Trust review 5, findings arithmetic (moleculefinder_etl/review/findings.py; brief ../TRUST-4-FINDINGS-ARITHMETIC-PROMPT.md).

Offline. A small world of eight medicine labels, written with the real dye and ingredient codes; its two findings are
compiled by the real transform (transform/findings.py, which the TEST may import and the review may not); its fourteen
pages, two CSVs and two JSONs are rendered here with the web's markup and sentences (web lib/findings.ts,
lib/dye-pages.ts, lib/inactive.ts) and served through a fake fetch. The world as rendered must give no finding at all;
each check has a mutation that must be found. Then, on the real snapshot: the review's own recomputation equals the
transform's count for every count of both findings.
"""
from __future__ import annotations

import copy
import datetime as dt
import html
import json
import math
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.review import findings as rf
from moleculefinder_etl.transform import findings as tf

SITE = "https://moleculefinder.com"
DAY = dt.date(2026, 11, 28)
REFRESHED = "2026-11-23"
WATER, PG, MGST, TIO2, GEL = "059QF0KO0R", "6DC9Q167V3", "70097M6I30", "15FIX9V2JP", "2G86QN327L"
LACT_M, LACT_A = "EWQ57Q8I5X", "3SY5LH9PMK"
# slug: (name, otc?, routes, [(unii, role, name)])
LABELS = {
    "advil": ("Advil", True, ["ORAL"], [("WK2XYI10QM", "active", "IBUPROFEN"), ("WZB9127XOA", "inactive", "FD&C RED NO. 40"),
                                        (TIO2, "inactive", "TITANIUM DIOXIDE"), (MGST, "inactive", "MAGNESIUM STEARATE")]),
    "tylenol": ("Tylenol", True, ["ORAL"], [("362O9ITL9D", "active", "ACETAMINOPHEN"),
                                            ("J9EQA3S2JM", "inactive", "FD&C BLUE NO. 1 ALUMINUM LAKE"),
                                            ("6T47AS764T", "inactive", "FD&C RED NO. 40 ALUMINUM LAKE"),
                                            (LACT_M, "inactive", "LACTOSE MONOHYDRATE"), (LACT_A, "inactive", "ANHYDROUS LACTOSE")]),
    "claritin": ("Claritin", True, ["ORAL"], [("7AJO3BO7QN", "active", "LORATADINE"), (LACT_M, "inactive", "LACTOSE MONOHYDRATE"),
                                              (MGST, "inactive", "MAGNESIUM STEARATE")]),
    "abreva": ("Abreva", True, ["TOPICAL"], [("O8K7Q3S4RS", "active", "DOCOSANOL"), (WATER, "inactive", "WATER"),
                                             (PG, "inactive", "PROPYLENE GLYCOL")]),
    "zoloft": ("Zoloft", False, ["ORAL"], [("UTI8907Y6X", "active", "SERTRALINE"), ("H77VEI93A8", "inactive", "FD&C YELLOW NO. 6"),
                                           ("35SW5USQ3G", "inactive", "D&C YELLOW NO. 10"), (GEL, "inactive", "GELATIN")]),
    "vyvanse": ("Vyvanse", False, ["ORAL"], [("H645GUL8KJ", "active", "LISDEXAMFETAMINE"), ("PN2ZH5LOQY", "inactive", "FD&C RED NO. 3"),
                                             (GEL, "inactive", "GELATIN"), (TIO2, "inactive", "TITANIUM DIOXIDE")]),
    "lipitor": ("Lipitor", False, ["ORAL"], [("A0JWA85V8F", "active", "ATORVASTATIN"), ("H3R47K3TBD", "inactive", "FD&C BLUE NO. 1"),
                                             ("WZB9127XOA", "inactive", "FD&C RED NO. 40"),
                                             ("GYP6Z2JR6Q", "inactive", "FD&C YELLOW NO. 6 ALUMINUM LAKE")]),
    "kenalog": ("Kenalog", False, ["INTRAMUSCULAR"], [("F446C597KA", "active", "TRIAMCINOLONE")]),
}
EXAMPLES = {"lists": ["advil", "tylenol"], "lists_none": ["claritin"]}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]
ECFR_OTC = "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-C/part-201/subpart-C/section-201.66"
ECFR_RX = "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-C/part-201/subpart-D/section-201.100"
ECFR_Y5 = "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-C/part-201/subpart-A/section-201.20"
GUIDANCE = "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/replacing-color-additives-approved-or-marketed-drug-products"
SHORT = rf.SHORT


def setid(slug: str) -> str:
    return f"{abs(hash(slug)) % 10**8:08d}-0000-0000-0000-{len(slug):012d}"


def fdate(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def num(n: int) -> str:
    return f"{n:,}"


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ── the world ───────────────────────────────────────────────────────────────────────────────────
def build(labels: dict) -> dict:
    products, spl, routes = [], {}, {}
    for i, (slug, (name, otc, rts, ings)) in enumerate(sorted(labels.items())):
        sid = setid(slug)
        src = {"type": "dailymed", "setid": sid, "labeler": "A maker", "version": 3 + i, "effective": f"202501{10 + i:02d}",
               "doc_type": "HUMAN OTC DRUG LABEL" if otc else "HUMAN PRESCRIPTION DRUG LABEL",
               "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={sid}"}
        act = [x for x in ings if x[1] == "active"]
        products.append({"slug": slug, "name": name, "kind": "medicine", "source": src, "listed": len(ings),
                         "molecules": [{"slug": a[2].lower(), "role": "active", "listed_as": a[2], "unii": a[0]} for a in act],
                         "not_in_catalog": [{"name": x[2], "role": x[1], "unii": x[0]} for x in ings if x[1] != "active"],
                         "actives_not_in_catalog": []})
        spl[sid] = {"setid": sid, "version": src["version"], "ingredients": [{"role": r, "name": n, "unii": u} for u, r, n in ings]}
        routes[sid] = [{"name": r} for r in rts]
    statements = tf.load_statements()
    statements["examples"] = copy.deepcopy(EXAMPLES)
    D = tf.compile_dyes(products, spl=spl.get, routes=lambda s, v: routes.get(s), statements=statements)
    F = tf.compile_inactive(products, spl=spl.get, routes=lambda s, v: routes.get(s), statements=statements)
    wrap = lambda f, path: {**f, "title": "t", "page": SITE + path, "snapshot_date": REFRESHED, "license": "CC0 1.0"}
    return {"products": products, "spl": spl, "D": wrap(D, rf.DYES), "F": wrap(F, rf.INACTIVE), "snapD": D, "snapF": F}


def head(title: str, desc: str, path: str, image: bool = True) -> str:
    img = (f'<meta property="og:image" content="{SITE}{path}/opengraph-image?x"/>'
           f'<meta name="twitter:image" content="{SITE}{path}/opengraph-image?x"/>') if image else ""
    return (f'<!doctype html><html><head><title>{esc(title)} · MoleculeFinder</title><meta name="description" content="{esc(desc)}"/>'
            f'{img}<link rel="alternate" type="application/rss+xml" href="/molecule-of-the-week/feed.xml"/></head><body>')


def by_mouth(r):
    return r["taken"] in ("oral", "oral+other")


def class_word(c):
    return "Over the counter" if c == "otc" else "Prescription"


def route_words(r):
    return rf.taken_words(r)


def version(r):
    return f'<a href="{esc(r["url"])}" target="_blank">Version {r["version"]}, {fdate(rf.iso8(r["effective"]))}</a>'


def links(slugs, names):
    parts = []
    for i, s in enumerate(slugs):
        sep = "" if i == 0 else (" and " if i == len(slugs) - 1 else ", ")
        parts.append(f'<span>{sep}<a href="/whats-in/{s}">{esc(names[s])}</a></span>')
    return "".join(parts)


def methods(n: int, every: int, checked: str = "2026-11-21") -> str:
    return (f'<section class="section" aria-labelledby="fd-methods"><h2 id="fd-methods">How this was counted</h2><ul class="fd-facts">'
            f'<li><b>Which labels.</b> These are {num(n)} well-known brand labels chosen by hand. In {num(every)} of the {num(n)}, every active ingredient is a molecule on MoleculeFinder.</li>'
            f'<li><b>How a dye is matched.</b> By code. Every code was checked against the FDA\'s registry on {fdate(str(checked))}.</li>'
            f'<li><b>Whether a label names its inactive ingredients.</b> An OTC label lists them (<a href="{ECFR_OTC}">21 CFR 201.66(c)(8)</a>). '
            f'A prescription one not by mouth (<a href="{ECFR_RX}">21 CFR 201.100(b)(5)</a>).</li>'
            f'<li><b>Counted weekly.</b> Counted from the labels in the data refreshed {fdate(REFRESHED)}. The count is recomputed every week.</li>'
            '</ul></section>')


def asof() -> str:
    return f'<p class="fd-asof">Counted from the labels in the data refreshed {fdate(REFRESHED)}. The count is recomputed every week.</p>'


def data_section(sid: str, path: str) -> str:
    return (f'<section class="section" aria-labelledby="{sid}"><h2 id="{sid}">The data</h2><p>The table: '
            f'<a href="{path}/data.csv">CSV</a> and <a href="{path}/data.json">JSON</a>. Free to use without asking, under CC0 1.0.</p></section>')


def dataset(path: str) -> str:
    return ('<script type="application/ld+json">' + json.dumps({"@type": "Dataset", "license": rf.CC0_URL, "distribution": [
        {"encodingFormat": "text/csv", "contentUrl": f"{SITE}{path}/data.csv"},
        {"encodingFormat": "application/json", "contentUrl": f"{SITE}{path}/data.json"}]}) + "</script>")


def fda_section(D, ids=None) -> str:
    items = "".join(f'<li><p>{esc(s["says"])}</p><p><a href="{esc(s["url"])}">{esc(s["title"])}</a></p></li>'
                    for s in D["fda"]["statements"] if ids is None or s["id"] in ids)
    return (f'<section class="section" aria-labelledby="fd-fda"><h2 id="fd-fda">What the FDA has said</h2><p class="fd-note">Each '
            f'statement is the FDA\'s own, read on fda.gov or in the Federal Register on {fdate(str(D["fda"]["read"]))}.</p><ol>{items}</ol></section>')


def dye_text(r):
    return rf.dye_text(r)


def render_dyes_main(D, F) -> str:
    t, L = D["totals"], D["labels"]
    names = {r["slug"]: r["name"] for r in L}
    n, a6 = t["labels"]["labels"], t["any_of_six"]["labels"]
    title = f"Food dyes in medicines: what {num(n)} labels list"
    desc = f"{num(a6)} of the {num(n)} medicine labels on MoleculeFinder list one of the six synthetic food dyes the FDA named in April 2025."
    ex = D["examples"]
    exs = (f'<span>Among the {num(a6)}: {links([e["slug"] for e in ex["lists"]], names)}.</span>'
           f'<span> Among the {num(n - a6)} that list none of the six: {links([e["slug"] for e in ex["lists_none"]], names)}.</span>')
    r = t["routes"]["any_of_six"]
    rs = f"{num(r['oral'] + r['oral+other'])} of the {num(a6)} are taken by mouth"
    if r["oral+other"]:
        rs += f" ({num(r['oral+other'])} of them name another route as well)"
    rest = [f"{num(r['other'])} name another route instead"] if r["other"] else []
    rest += [f"{num(r['unstated'])} name no route"] if r["unstated"] else []
    rs += (", " + (" and ".join(rest) if len(rest) == 2 else "and " + rest[0]) if rest else "") + "."
    rows = sorted(rf.SIX, key=lambda i: (-t["by_dye"][i]["labels"], rf.SIX.index(i)))
    bars = "".join(f'<g><a href="{rf.DYES}/{i}"><text class="fd-chart__name">{SHORT[i]}</text></a><rect/>'
                   f'<text class="fd-chart__val">{t["by_dye"][i]["labels"]}</text></g>' for i in rows)
    summary = ", ".join(f"{SHORT[i]} {t['by_dye'][i]['labels']}" for i in rows)
    red = t["red_3"]
    red_p = (f"{red['labels']} {'label lists' if red['labels'] == 1 else 'labels list'} FD&amp;C Red No. 3: "
             f"{links(red['slugs'], names)}, each taken by mouth. Red No. 3 is not one of the six.")
    trs = "".join(
        f'<tr><th data-label="Medicine"><a href="/whats-in/{x["slug"]}">{esc(x["name"])}</a></th><td data-label="Type">{class_word(x["class"])}</td>'
        f'<td data-label="Dyes listed">{dye_text(x) or "None of the six"}{"<span>Also lists Red 3</span>" if x["red_3"] else ""}</td>'
        f'<td data-label="Route">{route_words(x)}</td><td data-label="DailyMed label">{version(x)}</td></tr>' for x in L)
    return (head(title, desc, rf.DYES) + '<main class="fd">' + dataset(rf.DYES) + f'<h1>{esc(title)}</h1>'
            f'<p class="fd-lede">{num(a6)} of the {num(n)} medicine labels on MoleculeFinder list at least one of the six synthetic dyes the FDA named in its April 2025 plan for the food supply.</p>'
            f'<p class="fd-split">{num(t["any_of_six"]["otc"])} of the {num(t["labels"]["otc"])} over-the-counter labels and {num(t["any_of_six"]["prescription"])} of the {num(t["labels"]["prescription"])} prescription labels.</p>'
            f'<p class="fd-examples">{exs}</p>' + asof() +
            f'<section aria-labelledby="fd-numbers"><h2 id="fd-numbers">The numbers</h2><ul class="fd-facts">'
            f'<li><b>{t["two_or_more"]["labels"]}</b> of the {num(n)} labels list two or more of the six, and <b>{t["three_or_more"]["labels"]}</b> list three or more.</li>'
            f'<li>{rs}</li><li><b>{t["d_and_c_any"]["labels"]}</b> labels list a D&amp;C color. Those are counted apart.</li></ul></section>'
            f'<section aria-labelledby="fd-chart"><figure><svg><title>t</title><desc>Of the {num(n)} medicine labels: {summary}.</desc>{bars}</svg>'
            f'<figcaption class="fd-chart__cap">Number of the {num(n)} medicine labels that list each dye.</figcaption></figure></section>'
            f'<section aria-labelledby="fd-red3"><h2 id="fd-red3">FD&amp;C Red No. 3</h2><p>{red_p}</p></section>'
            + fda_section(D) +
            f'<section aria-labelledby="fd-table"><h2 id="fd-table">Every label</h2><p class="fd-note">{num(n)} labels. Each medicine links.</p>'
            f'<table><tbody>{trs}</tbody></table></section>'
            + methods(n, D["selection"]["every_active_is_a_molecule"]) + data_section("fd-data", rf.DYES) + "</main></body></html>")


def dye_rows(rows, extra=None) -> str:
    return "".join(
        f'<tr><th data-label="Medicine"><a href="/whats-in/{x["slug"]}">{esc(x["name"])}</a></th><td data-label="Type">{class_word(x["class"])}</td>'
        f'<td data-label="Route">{route_words(x)}</td>'
        + (f'<td data-label="{extra[0]}">{esc(extra[1](x))}</td>' if extra else "")
        + f'<td data-label="DailyMed label">{version(x)}</td></tr>' for x in rows)


def lists_dye(x, i):
    return x["red_3"] if i == "red-3" else i in x["six"]


def render_dye_page(D, i) -> str:
    L, t = D["labels"], D["totals"]
    n = t["labels"]["labels"]
    name = next(d["name"] for d in D["dyes"] if d["id"] == i)
    yes, no = [x for x in L if lists_dye(x, i)], [x for x in L if not lists_dye(x, i)]
    s = rf.split(yes)
    bm_all = sum(by_mouth(x) for x in L)
    bm = sum(by_mouth(x) for x in yes)
    forms = [{c["form"] for c in x["codes"] if c["dye"] == i} for x in yes]
    has_lake = any(c["form"] == "lake" for d in D["dyes"] if d["id"] == i for c in d["codes"])
    if not has_lake:
        fs = f"The count takes the straight dye, {'which the label lists' if len(yes) == 1 else 'which all ' + num(len(yes)) + ' labels list'}."
    else:
        dn, ln, bn = sum("dye" in f for f in forms), sum("lake" in f for f in forms), sum(f == {"dye", "lake"} for f in forms)
        fs = f"{dn} {'lists' if dn == 1 else 'list'} the straight dye and {ln} {'lists' if ln == 1 else 'list'} its lake" + (f"; {bn} {'lists' if bn == 1 else 'list'} both" if bn else "") + "."
    title = f"Medicines with {SHORT[i]}: which of {num(n)} labels list it"
    desc = f"{s['labels']} of the {num(n)} medicine labels on MoleculeFinder list {name}: {s['otc']} over the counter, {s['prescription']} prescription."
    def listed(x):
        f = {c["form"] for c in x["codes"] if c["dye"] == i}
        return "Straight dye and lake" if f == {"dye", "lake"} else "Lake" if f == {"lake"} else "Straight dye"
    y5 = (f'<p class="fd-note"><b>A rule for this dye.</b> The FDA requires it (<a href="{ECFR_Y5}">21 CFR 201.20(a)</a>).</p>' if i == "yellow-5" else "")
    ids = ["red3-order", "red3-update", "red3-stay", "drugs-guidance"] if i == "red-3" else ["six-announcement", "six-tracker", "drugs-guidance"]
    return (head(title, desc, f"{rf.DYES}/{i}") + f'<main class="fd"><h1>{title}</h1>'
            f'<p class="fd-lede">{s["labels"]} of the {num(n)} medicine labels on MoleculeFinder list {esc(name)}.</p>'
            f'<p class="fd-split">{s["otc"]} of the {t["labels"]["otc"]} over-the-counter labels and {s["prescription"]} of the {t["labels"]["prescription"]} prescription labels. '
            f'{bm} of the {bm_all} labels taken by mouth list {esc(name)}.</p><p class="fd-examples">{fs}</p>' + asof() +
            f'<section aria-labelledby="dp-lists"><h2 id="dp-lists">The {len(yes)} {"label" if len(yes) == 1 else "labels"} that list {SHORT[i]}</h2>'
            f'<table><tbody>{dye_rows(yes, ("Listed as", listed))}</tbody></table></section>'
            f'<section aria-labelledby="dp-lists-not"><h2 id="dp-lists-not">The {len(no)} {"label" if len(no) == 1 else "labels"} that do not list {SHORT[i]}</h2>{y5}'
            f'<table><tbody>{dye_rows(no)}</tbody></table></section>' + fda_section(D, ids)
            + methods(n, D["selection"]["every_active_is_a_molecule"]) + data_section("dp-data", rf.DYES) + "</main></body></html>")


def render_none(D, F) -> str:
    t = D["totals"]
    none = rf.none_rows(D, F)
    otc, rx = [x for x in none if x["class"] == "otc"], [x for x in none if x["class"] == "prescription"]
    groups = {x["slug"]: x["groups"] for x in F["labels"]}
    gname = {g["id"]: g["name"] for g in F["groups"]}
    rxm = sum(by_mouth(x) for x in rx)
    other = lambda x: ", ".join(gname[g] for g in rf.OTHER_COLOURS if g in groups[x["slug"]]) or "None of those"
    cnt = lambda x: num(len(groups[x["slug"]])) if groups[x["slug"]] else "None"

    def rows(rs):
        return "".join(
            f'<tr><th data-label="Medicine"><a href="/whats-in/{x["slug"]}">{esc(x["name"])}</a></th><td data-label="Type">{class_word(x["class"])}</td>'
            f'<td data-label="Route">{route_words(x)}</td><td data-label="Other colors listed">{esc(other(x))}</td>'
            f'<td data-label="Inactive ingredients listed">{cnt(x)}</td><td data-label="DailyMed label">{version(x)}</td></tr>' for x in rs)
    oth = sum(any(g in groups[x["slug"]] for g in rf.OTHER_COLOURS) for x in otc)
    noi = sum(not groups[x["slug"]] for x in none)
    n = t["labels"]["labels"]
    rx_s = f"{len(rx)} of the {t['labels']['prescription']} prescription labels list none, {rxm} of them for a medicine taken by mouth, which the FDA does not require."
    dc = len([d for d in D["dyes"] if d["group"] == "d-and-c"])
    return (head(f"Medicines with no dye listed: which of {n} labels",
                 f"{len(otc)} of the {t['labels']['otc']} over-the-counter labels on MoleculeFinder list no FD&C or D&C color, and {len(rx)} of the {t['labels']['prescription']} prescription labels.",
                 rf.NONE) + '<main class="fd">'
            f'<p class="fd-lede">{len(otc)} of the {t["labels"]["otc"]} over-the-counter medicine labels on MoleculeFinder list no FD&amp;C or D&amp;C color.</p>'
            f'<p class="fd-split">The FDA requires it (<a href="{ECFR_OTC}">21 CFR 201.66(c)(8)</a>). {rx_s}</p>'
            f'<p class="fd-examples">None here means none of the colors: the six, Red 3 and {dc} D&amp;C colors.</p>' + asof() +
            f'<section aria-labelledby="nl-otc"><h2 id="nl-otc">The {len(otc)} over-the-counter labels that list none</h2><p class="fd-note">'
            f'Of the {t["labels"]["otc"]} over-the-counter labels, {len(otc)} list none of the FD&amp;C or D&amp;C colors and {t["labels"]["otc"] - len(otc)} list at least one. '
            f'{oth} of the {len(otc)} list another color, shown in the table.' + (f" {noi} {'label here lists' if noi == 1 else 'labels here list'} no inactive ingredient at all in its DailyMed record." if noi else "")
            + f'</p><table><tbody>{rows(otc)}</tbody></table></section>'
            f'<section aria-labelledby="nl-rx"><h2 id="nl-rx">The {len(rx)} prescription labels that list none</h2><p class="fd-note">Read these with care. {rx_s} '
            f'A prescription medicine for use other than by mouth is asked; {len(rx) - rxm} of these {len(rx)} {"is" if len(rx) - rxm == 1 else "are"} not taken by mouth.</p>'
            f'<table><tbody>{rows(rx)}</tbody></table></section>'
            + methods(n, D["selection"]["every_active_is_a_molecule"]) + data_section("dp-data", rf.DYES) + "</main></body></html>")


def shown_groups(F):
    by = {g["id"]: g for g in F["groups"]}
    return [by[g] for g in F["totals"]["shown"]["groups"]]


def label_cell(F, x):
    by = {g["id"]: g for g in F["groups"]}
    order = {g: i for i, g in enumerate(F["totals"]["shown"]["groups"])}
    mine = [by[g] for g in x["groups"]]
    sh = sorted((g for g in mine if g["id"] in order), key=lambda g: order[g["id"]])
    ot = sorted((g for g in mine if g["id"] not in order), key=lambda g: g["phrase"])
    a, b = "; ".join(g["phrase"] for g in sh), "; ".join(g["phrase"] for g in ot)
    if not a and not b:
        return "None listed"
    return a + (f"<span>; {b}</span>" if a and b else f"<span>{b}</span>")


def render_inactive_main(F) -> str:
    t, L = F["totals"], F["labels"]
    n = t["labels"]["labels"]
    sh = shown_groups(F)
    names = {x["slug"]: x["name"] for x in L}
    a, b, c = sh[:3]
    lede = f"{a['labels']} of the {n} medicine labels on MoleculeFinder list {a['phrase']} as an inactive ingredient, {b['labels']} list {b['phrase']} and {c['labels']} list {c['phrase']}."
    chart = "".join(f'<li class="fi-chart__row"><span class="fi-chart__name">{esc(g["name"])}</span><span class="fi-chart__track"></span>'
                    f'<span class="fi-chart__val">{g["labels"]}</span></li>' for g in sh)
    trs = "".join(
        f'<tr><th data-label="Medicine"><a href="/whats-in/{x["slug"]}">{esc(x["name"])}</a></th><td data-label="Type">{class_word(x["class"])}</td>'
        f'<td data-label="Route">{route_words(x)}</td><td data-label="Inactive ingredients">{label_cell(F, x)}</td>'
        f'<td data-label="DailyMed label">{version(x)}</td></tr>' for x in L)
    codes = "".join(f'<tr><th>{esc(g["name"])}</th><td>{c["unii"]}</td><td>{esc(c["member"])}</td><td>x</td><td>approved</td><td>{c["labels"]}</td></tr>'
                    for g in F["groups"] if g["kind"] != "code" and g["labels"] > 0 for c in g["codes"])
    none = t["lists_none"]
    return (head(f"Inactive ingredients in medicines: what {n} labels list",
                 f"{a['labels']} of the {n} medicine labels on MoleculeFinder list {a['phrase']}, {b['labels']} {b['phrase']}. Counted by FDA code.",
                 rf.INACTIVE) + '<main class="fd">' + dataset(rf.INACTIVE) +
            f'<p class="fd-lede">{esc(lede)}</p><p class="fd-split">{len(sh)} ingredients are each listed by at least {t["shown"]["floor"]} of the {n} labels, one in ten. '
            f'In all the labels list {t["codes"]} different inactive ingredient codes.</p>' + asof() +
            f'<section aria-labelledby="fi-chart-h"><ol>{chart}</ol><figcaption class="fd-chart__cap">Number of the {n} medicine labels that list each ingredient, '
            f'for every ingredient at least {t["shown"]["floor"]} labels list.</figcaption></section>'
            f'<section aria-labelledby="fi-numbers"><h2 id="fi-numbers">The numbers</h2><ul class="fd-facts">'
            f'<li>The count covers <b>{t["labels"]["otc"]}</b> over-the-counter and <b>{t["labels"]["prescription"]}</b> prescription labels; <b>{t["labels"]["by_mouth"]}</b> of the {n} are taken by mouth.</li>'
            f'<li>{none["labels"]} {"label lists" if none["labels"] == 1 else "labels list"} no inactive ingredient in {"its" if none["labels"] == 1 else "their"} DailyMed record. '
            + "".join(f'<span><a href="/whats-in/{s}">{esc(names[s])}</a></span>' for s in none["slugs"]) + '.</li></ul></section>'
            f'<section aria-labelledby="fi-table"><p class="fd-note">{n} labels, each with every inactive ingredient it lists.</p><table><tbody>{trs}</tbody></table></section>'
            + methods(n, F["selection"]["every_active_is_a_molecule"], F["registry"]["checked"]).replace("</ul></section>", "") + f"</ul><table><tbody>{codes}</tbody></table></section>"
            + data_section("fi-data", rf.INACTIVE) + "</main></body></html>")


def render_group(F, gid) -> str:
    t, L = F["totals"], F["labels"]
    n = t["labels"]["labels"]
    g = next(x for x in F["groups"] if x["id"] == gid)
    yes, no = [x for x in L if gid in x["groups"]], [x for x in L if gid not in x["groups"]]
    forms = ""
    if len(g["codes"]) > 1:
        forms = '<div class="fd-examples"><ul class="fi-forms">' + "".join(
            f'<li>{esc(c["member"])}: {c["labels"]} {"label" if c["labels"] == 1 else "labels"}</li>' for c in g["codes"] if c["labels"] > 0) + "</ul></div>"
    rows = lambda rs: "".join(
        f'<tr><th data-label="Medicine"><a href="/whats-in/{x["slug"]}">{esc(x["name"])}</a></th><td data-label="Type">{class_word(x["class"])}</td>'
        f'<td data-label="Route">{route_words(x)}</td><td data-label="DailyMed label">{version(x)}</td></tr>' for x in rs)
    return (head(f"Medicines with {g['phrase']}: which of {n} labels list it",
                 f"{g['labels']} of the {n} medicine labels on MoleculeFinder list {g['phrase']}: {g['otc']} over the counter, {g['prescription']} prescription.",
                 f"{rf.INACTIVE}/{gid}") + '<main class="fd">'
            f'<p class="fd-lede">{g["labels"]} of the {n} medicine labels on MoleculeFinder list {esc(g["phrase"])}.</p>'
            f'<p class="fd-split">{g["otc"]} of the {t["labels"]["otc"]} over-the-counter labels and {g["prescription"]} of the {t["labels"]["prescription"]} prescription labels. '
            f'{g["by_mouth"]} of the {t["labels"]["by_mouth"]} labels taken by mouth list {esc(g["phrase"])}.</p>{forms}' + asof() +
            f'<section aria-labelledby="fi-lists"><h2 id="fi-lists">The {len(yes)} labels that list {esc(g["phrase"])}</h2><table><tbody>{rows(yes)}</tbody></table></section>'
            f'<section aria-labelledby="fi-lists-not"><h2 id="fi-lists-not">The {len(no)} labels that do not list {esc(g["phrase"])}</h2><table><tbody>{rows(no)}</tbody></table></section>'
            + methods(n, F["selection"]["every_active_is_a_molecule"], F["registry"]["checked"]) + data_section("fi-data", rf.INACTIVE) + "</main></body></html>")


def render_index(D, F) -> str:
    t = D["totals"]
    top = shown_groups(F)[0]
    return (head("Findings", "Facts.", rf.FINDINGS) + '<main class="fd"><ul class="fd-index">'
            f'<li><h2><a href="{rf.INACTIVE}">Inactive ingredients in medicines: what {F["totals"]["labels"]["labels"]} labels list</a></h2>'
            f'<p>{top["labels"]} of the {F["totals"]["labels"]["labels"]} medicine labels on MoleculeFinder list {esc(top["phrase"])} as an inactive ingredient.</p></li>'
            f'<li><h2><a href="{rf.DYES}">Food dyes in medicines: what {t["labels"]["labels"]} labels list</a></h2>'
            f'<p>{t["any_of_six"]["labels"]} of the {t["labels"]["labels"]} medicine labels on MoleculeFinder list at least one of the six synthetic dyes.</p></li>'
            "</ul></main></body></html>")


def csv_cell(v: str) -> str:
    return f'"{v.replace(chr(34), chr(34) * 2)}"' if any(ch in v for ch in '",\n\r') else v


def dyes_csv(D) -> str:
    names = {d["id"]: d["name"] for d in D["dyes"]}
    out = [",".join(rf.DYES_CSV)]
    for x in D["labels"]:
        out.append(",".join(csv_cell(v) for v in [
            x["name"], f"{SITE}/whats-in/{x['slug']}", "over the counter" if x["class"] == "otc" else "prescription",
            rf.yn(bool(x["six"])), *[rf.yn(i in x["six"]) for i in rf.SIX], rf.yn(x["red_3"]),
            "; ".join(names[i] for i in x["d_and_c"]), "; ".join(c["unii"] for c in x["codes"]),
            "; ".join(x["routes"] or []).lower(), rf.taken_cell(x), x["setid"], str(x["version"]), rf.iso8(x["effective"]), x["url"]]))
    return "\r\n".join(out) + "\r\n"


def inactive_csv(F) -> str:
    ph = {g["id"]: g["phrase"] for g in F["groups"]}
    shown = F["totals"]["shown"]["groups"]
    out = [",".join([*rf.INACTIVE_CSV, *(f"lists_{g.replace('-', '_')}" for g in shown)])]
    for x in F["labels"]:
        out.append(",".join(csv_cell(v) for v in [
            x["name"], f"{SITE}/whats-in/{x['slug']}", "over the counter" if x["class"] == "otc" else "prescription", rf.taken_cell(x),
            " | ".join(sorted(ph[g] for g in x["groups"])), "; ".join(x["codes"]), "; ".join(x["routes"] or []).lower(),
            x["setid"], str(x["version"]), rf.iso8(x["effective"]), x["url"], *[rf.yn(g in x["groups"]) for g in shown]]))
    return "\r\n".join(out) + "\r\n"


def render_all(w: dict) -> dict:
    D, F = w["D"], w["F"]
    pages = {rf.FINDINGS: render_index(D, F), rf.DYES: render_dyes_main(D, F), rf.NONE: render_none(D, F),
             rf.INACTIVE: render_inactive_main(F)}
    for i in rf.DYE_PAGES:
        pages[f"{rf.DYES}/{i}"] = render_dye_page(D, i)
    for g in F["pages"]:
        pages[f"{rf.INACTIVE}/{g}"] = render_group(F, g)
    return {"pages": pages, "csv": {rf.DYES: dyes_csv(D), rf.INACTIVE: inactive_csv(F)},
            "json": {rf.DYES: json.dumps(D), rf.INACTIVE: json.dumps(F)}}


BOT = "<html><head><title>Federal Register :: Request Access</title></head></html>"


def served(w: dict, r: dict) -> dict:
    m = {}
    for p, body in r["pages"].items():
        m[SITE + p] = (200, "text/html; charset=utf-8", body)
    for p in (rf.DYES, rf.INACTIVE):
        m[f"{SITE}{p}/data.csv"] = (200, "text/csv; charset=utf-8", r["csv"][p])
        m[f"{SITE}{p}/data.json"] = (200, "application/json", r["json"][p])
        m[f"{SITE}{p}/opengraph-image?x"] = (200, "image/png", "")
    for p in r["pages"]:
        m[f"{SITE}{p}/opengraph-image?x"] = (200, "image/png", "")
    m[f"{SITE}/molecule-of-the-week/feed.xml"] = (200, "application/rss+xml", "<rss/>")
    m[f"{SITE}/sitemap.xml"] = (200, "application/xml", "<urlset>" + "".join(f"<url><loc>{SITE}{p}</loc></url>" for p in r["pages"]) + "</urlset>")
    for x in w["D"]["labels"]:
        m[f"{SITE}/whats-in/{x['slug']}"] = (200, "text/html", "")
    for s in w["D"]["fda"]["statements"]:
        if "federalregister.gov" in s["url"]:
            m[s["url"]] = (200, "text/html", BOT)
            m[rf.api_for(s["url"])] = (200, "application/json", json.dumps({"html_url": s["url"]}))
        else:
            m[s["url"]] = (200, "text/html", "<title>FDA</title>")
    for u in (ECFR_OTC, ECFR_RX, ECFR_Y5):
        m[u] = (200, "text/html", BOT)
        m[rf.api_for(u)] = (200, "application/json", json.dumps({"content_versions": [{"removed": False}]}))
    return m


def world_files(tmp: Path, w: dict, base: dict | None = None) -> dict:
    snap = tmp / "snap"
    (snap / "findings").mkdir(parents=True, exist_ok=True)
    (snap / "meta.json").write_text(json.dumps({"refreshed": REFRESHED}))
    (snap / "products.json").write_text(json.dumps({"products": w["products"]}))
    (snap / "findings" / "dyes-in-medicines.json").write_text(json.dumps(w["snapD"]))
    (snap / "findings" / "inactive-ingredients.json").write_text(json.dumps(w["snapF"]))
    cache = tmp / "cache"
    (cache / "dailymed").mkdir(parents=True, exist_ok=True)
    for sid, v in w["spl"].items():
        (cache / "dailymed" / f"spl1-{sid}.json").write_text(json.dumps({"value": v}))
    b = base or w
    pdir = tmp / "pitched"
    pdir.mkdir(exist_ok=True)
    (pdir / "base.json").write_text(json.dumps({"labels": {x["slug"]: {k: x[k] for k in ("setid", "version", "class", "six", "red_3")}
                                                            for x in b["D"]["labels"]}}))
    t = b["D"]["totals"]
    (tmp / "pitched.yaml").write_text(yaml.safe_dump({"pitches": [{
        "id": "p", "finding": "dyes-in-medicines", "page": rf.DYES, "sent": "2026-11-23", "to": "a reporter",
        "baseline": "pitched/base.json", "figures": [
            {"id": "headline", "words": "w", "value": t["any_of_six"]["labels"], "of": t["labels"]["labels"],
             "data": "any_of_six.labels", "of_data": "labels.labels", "confirmed": True, "evidence": "e"},
            {"id": "otc", "words": "w", "value": t["any_of_six"]["otc"], "of": t["labels"]["otc"], "data": "any_of_six.otc",
             "of_data": "labels.otc", "confirmed": False, "evidence": "e"}]}]}))
    return {"snap": snap, "cache": cache, "pitched": tmp / "pitched.yaml", "out": tmp / "out"}


def go(tmp: Path, w: dict, mutate=None, base=None, day=DAY, out=None) -> dict:
    f = world_files(tmp, w, base)
    r = render_all(w)
    m = served(w, r)
    if mutate:
        mutate(m, r)
    fetch = lambda url, head=False: m.get(url, (404, "text/html", ""))
    return rf.run(snap=f["snap"], out=out or f["out"], day=day, fetch_fn=fetch, workers=2, pause=0,
                  pitched_path=f["pitched"], label_caches=[f["cache"]])


def classes_of(data: dict) -> dict[str, dict]:
    return data["classes"]


def shapes(data: dict) -> set[tuple[str, str]]:
    return {(c["check"], c["shape"]) for c in data["classes"].values()}


@pytest.fixture(scope="module")
def world():
    return build(LABELS)


# ── the world as rendered: nothing found ────────────────────────────────────────────────────────
def test_the_world_as_rendered_is_clean(tmp_path, world):
    d = go(tmp_path, world)
    assert d["classes"] == {}, json.dumps(d["classes"], indent=1)[:3000]
    assert d["recomputation"]["differ"] == 0 and d["recomputation"]["origin"] == {"the cached label": len(LABELS)}
    assert d["verdict"].startswith("VERDICT: 0 finding classes found (0 findings)")
    assert all(r["holds"] for r in d["pitched"])
    assert d["addresses"]["not_read"] == 0 and len(d["addresses"]["pages"]) == 14
    for ck in ("page", "forms", "parts", "recomputed", "labels", "named", "date", "pitched", "citations", "share"):
        assert d["checked"][ck]["checked"] > 0, ck           # every check ran
    hb = rf.shared.previous_report(d and tmp_path / "out", DAY + dt.timedelta(days=1), rf.NAME)
    assert hb and hb["date"] == DAY.isoformat()


def sub(m, path, old, new, count=1):
    url = SITE + path
    status, typ, body = m[url]
    assert body.count(old) >= 1, (path, old)
    m[url] = (status, typ, body.replace(old, new, count))


# ── check 1: a headline off by one ──────────────────────────────────────────────────────────────
def test_a_headline_off_by_one_is_found(tmp_path, world):
    a6, n = world["D"]["totals"]["any_of_six"]["labels"], world["D"]["totals"]["labels"]["labels"]
    d = go(tmp_path, world, lambda m, r: sub(m, rf.DYES, f'<p class="fd-lede">{a6} of the {n}', f'<p class="fd-lede">{a6 + 1} of the {n}'))
    assert ("page", "the page and its data differ") in shapes(d)
    c = next(c for c in d["classes"].values() if c["surface"] == "headline")
    assert c["count"] == 1 and rf.DYES in c["addresses"]


def test_a_chart_bar_off_and_a_sentence_moved_are_found(tmp_path, world):
    def mut(m, r):
        sub(m, rf.DYES, '<text class="fd-chart__val">3</text>', '<text class="fd-chart__val">4</text>')
        sub(m, f"{rf.DYES}/red-40", "labels taken by mouth list", "labels swallowed list")
    d = go(tmp_path, world, mut)
    keys = list(d["classes"])
    assert any("/ chart /" in k for k in keys)
    assert ("page", "the sentence is not where the review reads it") in shapes(d)    # never a silent pass


# ── check 2: a CSV row missing ──────────────────────────────────────────────────────────────────
def test_a_csv_row_missing_is_found(tmp_path, world):
    def mut(m, r):
        st, typ, body = m[f"{SITE}{rf.DYES}/data.csv"]
        m[f"{SITE}{rf.DYES}/data.csv"] = (st, typ, "\r\n".join(x for x in body.split("\r\n") if "/whats-in/zoloft," not in x))
    d = go(tmp_path, world, mut)
    assert ("forms", "a JSON label missing from the CSV") in shapes(d)
    assert "zoloft" in json.dumps(d["classes"])


def test_a_csv_value_a_header_and_the_licence_are_found(tmp_path, world):
    def mut(m, r):
        st, typ, body = m[f"{SITE}{rf.INACTIVE}/data.csv"]
        m[f"{SITE}{rf.INACTIVE}/data.csv"] = (st, typ, body.replace("dailymed_url", "dailymed_link", 1).replace(",prescription,", ",over the counter,", 1))
        sub(m, rf.DYES, "under CC0 1.0", "under a licence")
    d = go(tmp_path, world, mut)
    s = shapes(d)
    assert ("forms", "the CSV header is not the documented one") in s
    assert ("forms", "the licence is not stated") in s


# ── check 3: a label in two lists; a sub-page list that is not the filter ──────────────────────
def test_a_label_in_both_lists_is_found(tmp_path, world):
    def mut(m, r):
        st, typ, body = m[f"{SITE}{rf.DYES}/red-40"]
        yes, no = body.split('aria-labelledby="dp-lists-not"')
        row = next(x for x in no.split("<tr>") if "/whats-in/claritin" in x)
        yes = yes.replace("<tbody>", "<tbody><tr>" + row.split("</tr>")[0] + "</tr>", 1)
        m[f"{SITE}{rf.DYES}/red-40"] = (st, typ, yes + 'aria-labelledby="dp-lists-not"' + no)
    d = go(tmp_path, world, mut)
    assert ("parts", "a label in both lists") in shapes(d)


def test_a_sub_page_that_is_not_the_main_tables_filter_is_found(tmp_path, world):
    # the main table says Zoloft lists Red 40; the Red 40 page (and the data) says it does not
    d = go(tmp_path, world, lambda m, r: sub(m, rf.DYES, '<td data-label="Dyes listed">Yellow 6</td>', '<td data-label="Dyes listed">Red 40, Yellow 6</td>'))
    s = shapes(d)
    assert ("parts", "the list is not the main table's filter") in s
    assert ("forms", "a table value differs from the JSON") in s


def test_a_none_page_label_that_lists_a_dye_is_found(tmp_path, world):
    def mut(m, r):
        _st, _typ, body = m[f"{SITE}{rf.DYES}"]
        row = next(x for x in body.split("<tr>") if "/whats-in/advil" in x).split("</tr>")[0]
        st2, typ2, nb = m[f"{SITE}{rf.NONE}"]
        cells = row.replace('<td data-label="Dyes listed">Red 40</td>', "")
        cells = cells.replace("</td><td data-label=\"DailyMed label\">", '</td><td data-label="Other colors listed">None of those</td>'
                              '<td data-label="Inactive ingredients listed">3</td><td data-label="DailyMed label">')
        m[f"{SITE}{rf.NONE}"] = (st2, typ2, nb.replace("<tbody>", "<tbody><tr>" + cells + "</tr>", 1))
    d = go(tmp_path, world, mut)
    assert ("parts", "a label on the none page lists a counted colour") in shapes(d)


# ── check 4: a count the transform made differently from the labels ────────────────────────────
def test_a_count_the_transform_made_differently_is_found_and_queued_at_once(tmp_path, world):
    w = copy.deepcopy(world)
    sid = next(p["source"]["setid"] for p in w["products"] if p["slug"] == "claritin")
    w["spl"][sid]["ingredients"].append({"role": "inactive", "name": "FD&C BLUE NO. 1", "unii": "H3R47K3TBD"})
    d = go(tmp_path, w)
    c = [c for c in d["classes"].values() if c["check"] == "recomputed"]
    assert c and all(x["shape"] == "the transform's count differs" for x in c)
    assert d["recomputation"]["differ"] > 0
    q = (tmp_path / "out" / "QUEUE.md").read_text()
    assert "findings: **recomputed from the source" in q                      # first run, queued at once


# ── check 5: the label set ──────────────────────────────────────────────────────────────────────
def test_a_label_page_that_does_not_answer_and_a_wrong_dailymed_link_are_found(tmp_path, world):
    def mut(m, r):
        m[f"{SITE}/whats-in/abreva"] = (404, "text/html", "")
        sid = next(x["setid"] for x in world["D"]["labels"] if x["slug"] == "lipitor")
        sub(m, f"{rf.DYES}/blue-1", f"setid={sid}", "setid=00000000-wrong")
    d = go(tmp_path, world, mut)
    s = shapes(d)
    assert ("labels", "the label's page does not answer") in s
    assert ("labels", "the link is not the label's own record") in s


def test_a_label_missing_from_the_finding_is_found(tmp_path, world):
    w = copy.deepcopy(world)
    w["D"]["labels"] = [x for x in w["D"]["labels"] if x["slug"] != "kenalog"]
    d = go(tmp_path, w)
    assert ("labels", "a declared label is not in the finding") in shapes(d)


# ── check 6 and 7: a named label with the wrong status; a page's date ──────────────────────────
def test_a_named_label_on_the_wrong_side_and_a_wrong_date_are_found(tmp_path, world):
    def mut(m, r):
        sub(m, rf.DYES, 'list none of the six: <span><a href="/whats-in/claritin">Claritin</a></span>',
            'list none of the six: <span><a href="/whats-in/zoloft">Zoloft</a></span>')
        sub(m, f"{rf.DYES}/yellow-6", f"data refreshed {fdate(REFRESHED)}", "data refreshed 16 November 2026")
    w = copy.deepcopy(world)
    d = go(tmp_path, w, mut)
    s = shapes(d)
    assert ("named", "a named label does not have that status") in s
    assert ("named", "the sentence names other labels than the data") in s
    assert ("date", "the page's date is not the data's") in s


# ── check 8: a pitched number moved ─────────────────────────────────────────────────────────────
def test_a_pitched_number_that_moved_is_loud_on_the_first_run(tmp_path, world):
    labels = copy.deepcopy(LABELS)
    name, otc, rts, ings = labels["tylenol"]
    labels["tylenol"] = (name, otc, rts, [x for x in ings if "FD&C" not in x[2]])       # a new label lists no dye
    moved = build(labels)
    d = go(tmp_path, moved, base=world)
    assert d["verdict"].startswith("VERDICT: A PITCHED NUMBER MOVED (headline, otc).")
    c = [c for c in d["classes"].values() if c["check"] == "pitched"]
    assert len(c) == 1 and c[0]["count"] == 2 and c[0]["change"] == "first run"
    assert "tylenol: dyes ['blue-1', 'red-40'] to none" in json.dumps(c[0]["details"])
    assert not any(x["check"] == "recomputed" for x in d["classes"].values())        # the transform is right
    md = (tmp_path / "out" / f"findings-{DAY.isoformat()}.md").read_text()
    assert md.index("## Pitched numbers") < md.index("## Findings, class by class") and "**NO: MOVED**" in md
    assert "A PITCHED NUMBER MOVED" in (tmp_path / "out" / "QUEUE.md").read_text()


def test_the_pitched_numbers_on_file():
    p = rf.load_pitched()
    dyes = next(x for x in p["pitches"] if x["finding"] == "dyes-in-medicines")
    got = {f["id"]: (f["value"], f.get("of"), f["confirmed"]) for f in dyes["figures"]}
    # 2026-11-28 (brief TRUST-5 section B): Cowork read the five emails; every figure is confirmed, three per-dye counts
    # and the four Red No. 3 labels by name are watched too, and AP's email bounced (four recipients)
    got["red 3 labels"] = (tuple(got["red 3 labels"][0]), None, True)
    assert got == {"headline": (112, 300, True), "over the counter": (47, 116, True), "prescription": (65, 184, True),
                   "red 3": (4, None, True), "blue 1": (53, None, True), "red 40": (45, None, True),
                   "yellow 6": (45, None, True),
                   "red 3 labels": (("inderal-la", "restoril", "vraylar", "vyvanse"), None, True)}
    assert dyes["sent"] == "2026-11-23" and "STAT" in dyes["to"] and "@" not in json.dumps(p)    # outlets only, public repo
    assert "four delivered" in dyes["to"] and "AP's mail server" in dyes["to"]
    D = json.loads((rf.SNAP / "findings" / "dyes-in-medicines.json").read_text())
    for f in dyes["figures"]:                                         # every pitched figure holds in today's data
        assert rf.dig(D["totals"], f["data"]) == f["value"], f["id"]
    base = json.loads((rf.PITCHED.parent / dyes["baseline"]).read_text())
    assert base["totals"]["any_of_six"] == {"labels": 112, "otc": 47, "prescription": 65} and len(base["labels"]) == 300
    assert sum(1 for x in base["labels"].values() if x["six"]) == 112


# ── check 9 and 10: citations, share images ─────────────────────────────────────────────────────
def test_a_citation_that_does_not_answer_and_a_page_with_no_share_image_are_found(tmp_path, world):
    def mut(m, r):
        m[GUIDANCE] = (404, "text/html", "")
        m[rf.api_for(ECFR_RX)] = (500, "text/plain", "")
        st, typ, body = m[SITE + rf.FINDINGS]
        m[SITE + rf.FINDINGS] = (st, typ, body.replace('<meta property="og:image"', '<meta property="og:x"'))
    d = go(tmp_path, world, mut)
    s = shapes(d)
    assert ("citations", "the link does not answer") in s
    assert ("citations", "the link was not read") in s
    assert ("share", "the page has no share image") in s
    assert any("not read" in x["why"] for x in d["addresses"]["not_read_list"])


def test_a_citation_whose_text_names_another_section_is_found(tmp_path, world):
    d = go(tmp_path, world, lambda m, r: sub(m, rf.DYES, ">21 CFR 201.66(c)(8)<", ">21 CFR 201.60(c)(8)<"))
    assert ("citations", "the text names another section than the link") in shapes(d)


def test_a_page_not_read_is_never_a_pass(tmp_path, world):
    d = go(tmp_path, world, lambda m, r: m.pop(f"{SITE}{rf.DYES}/green-3"))
    assert any(x["url"].endswith("/green-3") for x in d["addresses"]["not_read_list"])
    assert "1 not read" in d["verdict"]


# ── the queue: two consecutive runs for the ordinary classes ────────────────────────────────────
def test_an_ordinary_class_is_queued_on_its_second_run_only(tmp_path, world):
    out = tmp_path / "out"

    def mut(m, r):
        st, typ, body = m[SITE + rf.FINDINGS]
        m[SITE + rf.FINDINGS] = (st, typ, body.replace('<meta property="og:image"', '<meta property="og:x"'))
    go(tmp_path / "a", world, mut, out=out)
    assert not (out / "QUEUE.md").exists()
    d = go(tmp_path / "b", world, mut, day=DAY + dt.timedelta(days=1), out=out)
    assert d["queued_today"] and "share images and feeds" in (out / "QUEUE.md").read_text()
    c = next(iter(d["classes"].values()))
    assert c["change"] == "+0"


# ── on the real snapshot: the review's recomputation equals the transform ──────────────────────
SNAP = rf.SNAP


def test_the_recomputation_equals_the_transform_on_the_same_input():
    """On the real products.json with no label cache, both the review and the transform read the page data: every
    count of both findings must agree (two separate pieces of code, one input)."""
    products = json.loads((SNAP / "products.json").read_text())
    ps = rf.medicine_labels(products)
    statements = tf.load_statements()
    D = tf.compile_dyes(ps, spl=lambda s: None, routes=lambda s, v: None, statements=statements)
    F = tf.compile_inactive(ps, spl=lambda s: None, routes=lambda s, v: None, statements=statements)
    rec = rf.recompute(products, rf.load_tables())
    rv = rf.Review()
    rf.compare_recomputed(rv, rec, D, F, "d", "i")
    assert rv.total() > 2500 and not rv.findings, rv.findings[:5]


@pytest.mark.skipif(not any((d / "dailymed").is_dir() for d in rf.LABEL_CACHES), reason="no DailyMed label cache on this machine")
def test_the_recomputation_from_the_labels_equals_the_shipped_findings():
    """From each label's own cached ingredient list, every count equals the snapshot's findings files."""
    spl = rf.label_cache()
    products = json.loads((SNAP / "products.json").read_text())
    rec = rf.recompute(products, rf.load_tables(), spl)
    if rec["origin"].get("the page data"):
        pytest.skip(f"{rec['origin']['the page data']} label(s) not cached here")
    D = json.loads((SNAP / "findings" / "dyes-in-medicines.json").read_text())
    F = json.loads((SNAP / "findings" / "inactive-ingredients.json").read_text())
    rv = rf.Review()
    compared = rf.compare_recomputed(rv, rec, D, F, "d", "i")
    assert len(compared) > 2500 and not rv.findings, rv.findings[:5]
    assert rec["dyes"]["any_of_six"] == D["totals"]["any_of_six"] and rec["dyes"]["labels"]["labels"] == 300


def test_the_review_does_not_import_the_transform():
    src = Path(rf.__file__).read_text()
    assert "transform" not in "".join(x for x in src.splitlines() if x.startswith(("import", "from")))
    assert "findings as" not in src.split('"""', 2)[2].split("\n\n", 1)[0]


WEB = Path(__file__).resolve().parents[2] / "moleculefinder-web" / "lib"


@pytest.mark.skipif(not (WEB / "findings.ts").exists(), reason="the web repo is not beside this one")
def test_the_documented_csv_headers_are_the_webs():
    import re
    dyes = re.search(r"CSV_COLUMNS = \[(.*?)\] as const", (WEB / "findings.ts").read_text(), re.DOTALL).group(1)
    inact = re.search(r"CSV_FIXED = \[(.*?)\] as const", (WEB / "inactive.ts").read_text(), re.DOTALL).group(1)
    assert tuple(re.findall(r'"([a-z_0-9]+)"', dyes)) == rf.DYES_CSV
    assert tuple(re.findall(r'"([a-z_0-9]+)"', inact)) == rf.INACTIVE_CSV
    pages = re.search(r"DYE_PAGE_IDS = \[(.*?)\] as const", (WEB / "dye-pages.ts").read_text(), re.DOTALL).group(1)
    assert tuple(re.findall(r'"([a-z0-9-]+)"', pages)) == rf.DYE_PAGES
    other = re.search(r"OTHER_COLOR_IDS = \[(.*?)\] as const", (WEB / "dye-pages.ts").read_text(), re.DOTALL).group(1)
    assert tuple(re.findall(r'"([a-z0-9-]+)"', other)) == rf.OTHER_COLOURS


def test_mfetl_names_the_review():
    from moleculefinder_etl import cli
    assert "findings" in Path(cli.__file__).read_text().split("review_what", 1)[1].split("\n", 1)[0]
    assert math.ceil(300 / 10) == 30
