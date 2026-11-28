"""Trust review 2, one fact on every surface (moleculefinder_etl/review/facts.py; brief ../TRUST-3-ONE-FACT-PROMPT.md).

Offline: a small fixture snapshot and fixture pages. For each fact kind, one page that must be found and one that must
not; each deliberate difference honoured and nothing else; the date seed; the Tuesday rule; the repetition measure on
three small fixture pages with a known answer; a page not read is never counted as agreeing.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl.review import facts

MOLS = {
    "caffeine": {"title": "Caffeine", "molecular_formula": "C8H10N4O2", "molecular_weight": 194.19,
                 "ld50_mg_per_kg": 192, "ld50_species": "rat", "ld50_route": "oral", "has_3d": True,
                 "structure_svg": "<svg/>", "is_otc": False,
                 "ghs": {"signal_word": "Warning", "pictograms": ["GHS07"], "h_statements": ["H302"],
                         "sources": ["echa"]},
                 "categories": [{"slug": "coffee", "name": "Coffee", "kind": "food"}]},
    "glucose": {"title": "Glucose", "molecular_formula": "C6H12O6", "molecular_weight": 180.16, "structure_svg": "<svg/>",
                "categories": [{"slug": "alcohols", "name": "Alcohols", "kind": "functional_group"}]},
    "candesartan": {"title": "Candesartan", "molecular_formula": "C24H20N6O3", "molecular_weight": 440.5,
                    "ld50_mg_per_kg": 2000, "ld50_qualifier": ">", "ld50_species": "rat", "ld50_route": "oral",
                    "structure_svg": "<svg/>"},
    "silicon-dioxide": {"title": "Silicon dioxide", "molecular_formula": "O2Si", "molecular_weight": 60.084,
                        "structure_none": {"line": "A network solid.", "formula": "SiO2"}},
    "chitin": {"title": "Chitin", "molecular_formula": None, "molecular_weight": None, "macromolecule": True,
               "structure_repeat_unit": {"smiles": "*C*"},
               "categories": [{"slug": "alcohols", "name": "Alcohols", "kind": "functional_group",
                               "from": "repeat_unit"}]},
    "inulin": {"title": "Inulin", "molecular_formula": None, "molecular_weight": None, "macromolecule": True,
               "categories": [{"slug": "alcohols", "name": "Alcohols", "kind": "functional_group"}]},
}


@pytest.fixture()
def snap(tmp_path: Path) -> Path:
    s = tmp_path / "snap"
    (s / "molecules").mkdir(parents=True)
    (s / "leaderboards").mkdir()
    for slug, r in MOLS.items():
        (s / "molecules" / f"{slug}.json").write_text(json.dumps({"slug": slug, **r}))
    (s / "meta.json").write_text(json.dumps({"refreshed": "2026-11-23"}))
    (s / "products.json").write_text(json.dumps({"products": [
        {"slug": "advil", "name": "Advil", "kind": "medicine",
         "source": {"type": "dailymed", "doc_type": "HUMAN OTC DRUG LABEL"},
         "molecules": [{"slug": "caffeine"}, {"slug": "glucose"}, {"slug": "silicon-dioxide"}]},
        {"slug": "lipitor", "name": "Lipitor", "kind": "medicine",
         "source": {"type": "dailymed", "doc_type": "HUMAN PRESCRIPTION DRUG LABEL"},
         "molecules": [{"slug": "glucose"}]}]}))
    (s / "doors.json").write_text(json.dumps({"doors": [{"slug": "coffee"}]}))
    (s / "comparisons.json").write_text(json.dumps({"caffeine-vs-glucose": {"a": "caffeine", "b": "glucose"}}))
    (s / "worlds.json").write_text(json.dumps({"worlds": [{"slug": "morning-coffee", "count": 1}]}))
    (s / "sources.json").write_text(json.dumps({"sources": [{"key": "echa", "short": "ECHA"}]}))
    (s / "leaderboards" / "biggest.json").write_text(json.dumps({
        "slug": "biggest", "metric": "molecular_weight", "entries": [
            {"slug": "caffeine", "title": "Caffeine", "value_num": 194.19},
            {"slug": "glucose", "title": "Glucose", "value_num": 180.16}]}))
    return s


def review(snap: Path, differences: dict | None = None) -> facts.Review:
    return facts.Review(facts.Truth(snap), facts.load_differences() if differences is None else differences)


def run_page(rv: facts.Review, path: str, body: str, sitemap=(), statuses=None) -> list[dict]:
    before = len(rv.findings)
    facts.check_page(rv, facts.page_of(path, f"<html><head>{body.split('<main>')[0]}</head><body><main>"
                                             f"{body.split('<main>', 1)[1] if '<main>' in body else body}</main>"
                                             f"</body></html>"), set(sitemap), statuses or {})
    return rv.findings[before:]


def shapes(found: list[dict]) -> set[tuple[str, str]]:
    return {(f["fact"], f["shape"]) for f in found}


def formula(f: str) -> str:
    """A formula typeset as the site does: the sub-tag twin for the eye, the plain one read aloud."""
    return f'<span class="formula"><span aria-hidden="true">{f}</span><span class="vh">{f}</span></span>'


def mol_page(name: str, f: str | None, w, extra: str = "", title: str = "") -> str:
    top = (f'<div class="meet__facts"><span class="meet__formula"><span aria-hidden="true">{f}</span>'
           f'<span class="vh">{f}</span></span><span class="meet__mw">{w} g/mol</span></div>') if f else ""
    return (f"<title>{title or name + ' · MoleculeFinder'}</title><main><h1>{name}</h1>{top}"
            f'<figure class="v3__2d"></figure>{extra}')


# ── 1. name, formula, weight ────────────────────────────────────────────────────────────────────
def board_row(slug, name, f, w):
    return (f'<a class="rank__row" href="/m/{slug}"><span class="rank__name">{name}</span>'
            f'<span class="rank__formula">{f}</span><span class="rank__val">{w} <span>g/mol</span></span></a>')


def test_formula_and_weight_found_on_a_row(snap):
    rv = review(snap)
    found = run_page(rv, "/best/biggest", "<main>" + board_row("caffeine", "Caffeine", "C8H10N4O3", "194.19")
                     + board_row("glucose", "Glucose", "C6H12O6", "181"))
    assert ("formula", "two different values") in shapes(found)
    assert ("weight", "two different values") in shapes(found)


def test_formula_and_weight_that_agree_are_not_found(snap):
    rv = review(snap)
    found = run_page(rv, "/best/biggest", "<main>" + board_row("caffeine", "Caffeine", "C8H10N4O2", "194.19")
                     + board_row("glucose", "Glucose", "C6H12O6", "180.16"))
    assert not [f for f in found if f["fact"] in ("formula", "weight", "name")]
    assert rv.compared[("weight", "board row", "the record")] == 2


def test_the_weight_rule_rounded_half_up_to_the_precision_shown(snap):
    # Ruled 2026-11-27 (brief ../TRUST-3B-FACT-FINDINGS-PROMPT.md, ruling 1): a shown weight agrees when it is the
    # record's rounded half-up to the precision shown, down to whole grams; anything else is a finding.
    assert facts.weight_shape("60.08", 60.084) is None
    assert facts.weight_shape("60", 60.084) is None
    assert facts.weight_shape("253.81", 253.8089) is None
    assert facts.weight_shape("136", 136.11) is None
    assert facts.weight_shape("441", 440.5) is None                                   # half-up, not half-even
    assert facts.weight_shape("440", 440.5) == "rounded the wrong way"
    assert facts.weight_shape("253.80", 253.8089) == "two different values"
    assert facts.weight_shape("60.0840", 60.084) == "shown to more precision than the record"
    assert facts.weight_shape("427.20", 427.2) == "shown to more precision than the record"
    assert facts.weight_shape("6,179", 6179.0) is None
    rv = review(snap)
    found = run_page(rv, "/best/lightest", "<main>" + board_row("silicon-dioxide", "Silicon dioxide", "SiO2", "60.08"))
    assert not [f for f in found if f["fact"] == "weight"]
    assert ("formula", "one value, written two ways") in shapes(found)   # not ruled on a board row
    bad = run_page(rv, "/m/candesartan", "<main><p>Candesartan (C24H20N6O3, 440 g/mol) is a medicine.</p>")
    assert ("weight", "rounded the wrong way") in shapes(bad)


def test_a_weight_on_a_molecule_with_none_is_stated_here_absent_there(snap):
    rv = review(snap)
    found = run_page(rv, "/best/biggest", "<main>" + board_row("inulin", "Inulin", "C6H12O6", "6,179"))
    assert ("weight", "stated here, absent there") in shapes(found)
    assert ("formula", "stated here, absent there") in shapes(found)


def test_a_name_that_differs(snap):
    rv = review(snap)
    assert ("name", "two different values") in shapes(run_page(
        rv, "/best/biggest", "<main>" + board_row("caffeine", "Theine", "C8H10N4O2", "194.19")))


def test_prose_owns_each_value_by_the_molecule_named_before_it(snap):
    rv = review(snap)
    ok = run_page(rv, "/classroom", "<main><p>Caffeine (C8H10N4O2) is heavier than Glucose (C6H12O6), 194.19 g/mol "
                                    "against 180.16 g/mol for Glucose.</p>")
    assert not [f for f in ok if f["fact"] in ("formula", "weight")]
    bad = run_page(rv, "/classroom", "<main><p>Caffeine (C9H10N4O2) weighs 199.1 g/mol.</p>")
    assert ("formula", "two different values") in shapes(bad) and ("weight", "two different values") in shapes(bad)
    groups = run_page(rv, "/classroom", "<main><p>Caffeine carries a CH3 group and vitamin B12 is another.</p>")
    assert not [f for f in groups if f["fact"] == "formula"]               # a group is not a molecule's formula


def test_a_structure_hub_and_a_size_hub(snap):
    rv = review(snap)
    page = ('<title>Alcohols: 3 examples</title><main><p>3 molecules in the canon sharing alcohols.</p>'
            '<div class="roam__grid"><a href="/m/glucose">Glucose</a><a href="/m/chitin">Chitin</a>'
            '<a href="/m/inulin">Inulin</a></div>')
    found = run_page(rv, "/in/alcohols", page)
    hub = [f for f in found if f["fact"] == "structure hub"]
    assert [f["subject"] for f in hub] == ["inulin"]                       # chitin is the ruled difference
    assert [c["subject"] for c in rv.excused["repeat-unit-hubs"]] == ["chitin"]


# ── 2. LD50 ─────────────────────────────────────────────────────────────────────────────────────
def ld50_block(v, ctx):
    return f'<div class="pg pg--ld50"><p><span class="ld50__value">{v}</span> <span class="ld50__context">{ctx}</span></p></div>'


def test_ld50_found_and_not(snap):
    rv = review(snap)
    ok = run_page(rv, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19",
                                               ld50_block("192 mg/kg", "pure caffeine, rat, oral")))
    assert not [f for f in ok if f["fact"] == "LD50"]
    bad = run_page(rv, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19",
                                                ld50_block("192 mg/kg", "pure caffeine, mouse, oral")))
    assert ("LD50", "two different values") in shapes(bad)
    limit = run_page(rv, "/m/candesartan", mol_page("Candesartan", "C24H20N6O3", "440.5",
                                                     ld50_block("2,000 mg/kg", "pure candesartan, rat, oral")))
    assert ("LD50", "the qualifier differs") in shapes(limit)
    good_limit = run_page(rv, "/m/candesartan", mol_page("Candesartan", "C24H20N6O3", "440.5",
                                                          ld50_block("more than 2,000 mg/kg",
                                                                     "pure candesartan, rat, oral")))
    assert not [f for f in good_limit if f["fact"] == "LD50"]


def test_an_ld50_without_its_form_breaks_the_copy_rule(snap):
    rv = review(snap)
    found = run_page(rv, "/classroom", "<main><p>Caffeine: LD50 192 mg/kg (rat, oral).</p>")
    assert ("LD50", "stated without its chemical form") in shapes(found)


# ── 3. hazard label ─────────────────────────────────────────────────────────────────────────────
def ghs_block(sig, codes, hs, by):
    return (f'<div class="pg pg--ghs"><h3>Hazard label (GHS), {by} via PubChem</h3><p><b class="sig">{sig}</b> '
            f'Irritant pictogram ({codes}); hazard statements:</p><ul class="hz"><li><b>{hs}</b> Harmful</li></ul></div>')


def test_hazard_label_found_and_not(snap):
    rv = review(snap)
    ok = run_page(rv, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19", ghs_block("Warning", "GHS07", "H302", "ECHA")))
    assert not [f for f in ok if f["fact"] == "hazard label"]
    bad = run_page(rv, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19",
                                               ghs_block("Danger", "GHS06", "H301", "HSDB")))
    assert len([f for f in bad if f["fact"] == "hazard label"]) == 4      # signal, pictogram, statement, attribution


# ── 4. status ───────────────────────────────────────────────────────────────────────────────────
def test_label_status_found_and_not(snap):
    rv = review(snap)
    ok = run_page(rv, "/whats-in/advil", "<main><p>A medicine sold over the counter, without a prescription.</p>")
    assert not [f for f in ok if f["fact"] == "status"]
    bad = run_page(rv, "/whats-in/lipitor", "<main><p>A medicine sold over the counter, without a prescription.</p>")
    assert ("status", "two different values") in shapes(bad)


def test_molecule_status_line_against_the_status_rule(snap):
    """The line agrees only with the status the record's own evidence supports (trust 3C, 2026-11-27: the site and the
    review read one rule, transform/medicine_status.py); a record with no status states none."""
    rx = "<p>Dispensed on prescription, not sold on a shelf.</p>"
    otc = "<p>Sold over the counter, without a prescription.</p>"
    both = "<p>Sold over the counter in some products and on prescription in others.</p>"
    rv = review(snap)
    assert ("status", "two different values") in shapes(run_page(rv, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19", rx)))
    lic = {"kind": "licence", "register": "Drugs@FDA", "application": "NDA 000001"}
    lab = {"kind": "label", "register": "DailyMed", "product": "Brand", "category": "OTC MONOGRAPH DRUG"}
    t = facts.Truth(snap)
    t.recs["caffeine"]["medicine_status"] = {"status": "prescription", "otc": [], "prescription": [lic]}
    rv2 = facts.Review(t, facts.load_differences())
    status = lambda html: [f for f in run_page(rv2, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19", html))
                           if f["fact"] == "status"]
    assert not status(rx) and status(otc) and status(both)
    t.recs["caffeine"]["medicine_status"] = {"status": "both", "otc": [lab], "prescription": [lic]}
    assert not status(both) and status(rx)
    # a status field its own evidence does not support is found too
    t.recs["caffeine"]["medicine_status"] = {"status": "both", "otc": [], "prescription": [lic]}
    assert status(both)
    # an unsettled medicine keeps its group's line
    t.recs["caffeine"].update(scope_bucket="otc-medicine",
                              medicine_status={"status": "otc", "otc": [], "prescription": [], "unsettled": "no basis"})
    assert not status(otc) and status(rx)


# ── 5. counts ───────────────────────────────────────────────────────────────────────────────────
def test_hub_count_found_and_not(snap):
    rv = review(snap)
    grid = '<div class="roam__grid"><a href="/m/caffeine">Caffeine</a></div>'
    ok = run_page(rv, "/in/coffee", f"<title>Coffee: 1 molecules</title><main><p>1 molecules in the canon.</p>{grid}")
    assert not [f for f in ok if f["fact"] == "count"]
    bad = run_page(rv, "/in/coffee", f"<title>Coffee: 2 molecules</title><main><p>2 molecules in the canon.</p>{grid}")
    assert {f["surface"] for f in bad if f["fact"] == "count"} == {"hub title", "hub heading"}


def test_site_count_and_board_leader(snap):
    rv = review(snap)
    assert ("count", "two different values") in shapes(run_page(rv, "/explore", "<main><p>All 930 molecules on one map.</p>"))
    assert not run_page(rv, "/explore", "<main><p>All 6 molecules on one map.</p>")
    lead = ('<meta name="description" content="Glucose leads the Biggest board at 180.16 g/mol. Ranked."><main>'
            + board_row("glucose", "Glucose", "C6H12O6", "180.16") + board_row("caffeine", "Caffeine", "C8H10N4O2", "194.19"))
    surfaces = {f["surface"] for f in run_page(rv, "/best/biggest", lead) if f["fact"] == "count"}
    assert surfaces == {"board leader"}


# ── 6. the data date ────────────────────────────────────────────────────────────────────────────
def test_data_date_found_and_not(snap):
    rv = review(snap)
    ok = run_page(rv, "/about", '<main><p>Data refreshed <time dateTime="2026-11-23">2026-11-23</time></p>'
                               "<p>This week 23 to 29 November</p>")
    assert not [f for f in ok if f["fact"] == "data date"]
    bad = run_page(rv, "/about", '<main><p>Data refreshed <time dateTime="2026-11-16">2026-11-16</time></p>'
                                "<p>This week 16 to 22 November</p>")
    assert len([f for f in bad if f["fact"] == "data date"]) == 2


# ── 7. text about a missing fact ────────────────────────────────────────────────────────────────
def test_text_naming_a_formula_the_page_lacks(snap):
    rv = review(snap)
    bad = run_page(rv, "/vs/caffeine-vs-glucose", "<main><p>Chitin's listed formula and weight represent a fragment.</p>")
    assert ("text about a missing fact", "names a formula the molecule's page does not show") in shapes(bad)
    ok = run_page(rv, "/vs/caffeine-vs-glucose", "<main><p>Chitin is a long chain, so it has no single formula or "
                                                 "weight.</p><p>Caffeine's formula is C8H10N4O2.</p>")
    assert not [f for f in ok if f["fact"] == "text about a missing fact"]


# ── 8. promises ─────────────────────────────────────────────────────────────────────────────────
def test_title_promises(snap):
    rv = review(snap)
    page = "<title>Inulin: formula, structure &amp; chemistry · MoleculeFinder</title><main><h1>Inulin</h1>"
    found = {f["shape"] for f in run_page(rv, "/m/inulin", page) if f["fact"] == "promise"}
    assert found == {"promises formula, the page shows none", "promises structure, the page shows none"}
    ok = mol_page("Caffeine", "C8H10N4O2", "194.19", title="Caffeine: formula, structure &amp; chemistry")
    assert not [f for f in run_page(rv, "/m/caffeine", ok) if f["fact"] == "promise"]


# ── 9. links ────────────────────────────────────────────────────────────────────────────────────
def test_links_found_and_not(snap):
    rv = review(snap)
    bad = run_page(rv, "/explore", '<main><p><a href="/m/theine">Theine</a> <a href="/whats-in/gone">Gone</a> '
                                   '<a href="/m/glucose">Caffeine</a></p>', statuses={"/whats-in/gone": 410})
    got = {(f["subject"], f["shape"]) for f in bad if f["fact"] == "link"}
    assert ("/m/theine", "links to a page the catalogue does not have") in got
    assert ("/whats-in/gone", "links to a page that answers 410") in got
    assert ("glucose", "a name that links to another molecule's page") in got
    ok = run_page(rv, "/explore", '<main><p><a href="/m/caffeine">Caffeine</a> <a href="/in/coffee">Coffee</a></p>')
    assert not [f for f in ok if f["fact"] == "link"]


# ── the deliberate differences ──────────────────────────────────────────────────────────────────
def test_the_differences_file_holds_only_ruled_entries():
    raw = yaml.safe_load(facts.DIFFERENCES.read_text())["differences"]
    assert set(raw) == {"conventional-formula-on-panel-pages", "repeat-unit-hubs",
                        "conventional-formula-in-editorial-text"}
    assert {str(e["date"]) for e in raw.values()} == {"2026-11-26", "2026-11-27"}
    for e in raw.values():
        assert e["by"].startswith("Garrett") and e["subjects"] in facts.SUBJECT_RULES and e["fact"] in facts.FACTS
    assert "rounding" not in " ".join(json.dumps(e, default=str) for e in raw.values()).lower()


def test_the_panel_formula_is_excused_on_its_page_and_nowhere_else(snap):
    rv = review(snap)
    found = run_page(rv, "/m/silicon-dioxide", mol_page("Silicon dioxide", "SiO2", "60.084"))
    assert not [f for f in found if f["fact"] == "formula"]
    assert {c["surface"] for c in rv.excused["conventional-formula-on-panel-pages"]} == {"molecule page top line"}
    row = run_page(rv, "/whats-in/advil", '<main><div><a href="/m/silicon-dioxide">Silicon dioxide</a>'
                                          f'{formula("SiO2")}</div>')
    assert ("formula", "one value, written two ways") in shapes(row)
    caffeine = run_page(rv, "/m/caffeine", mol_page("Caffeine", "N4O2C8H10", "194.19"))
    assert ("formula", "one value, written two ways") in shapes(caffeine)    # the ruling names panel pages only


def test_a_conventional_formula_in_editorial_text_is_excused_when_the_atoms_match(snap):
    # Ruled 2026-11-27 (ruling 2): NaHCO3 in a sentence for PubChem's CHNaO3; the atoms must be exactly the record's.
    rv = review(snap)
    ok = run_page(rv, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19",
                                              "<p>Caffeine, written N4O2C8H10 here, is a purine.</p>"))
    assert not [f for f in ok if f["fact"] == "formula"]
    assert any(c["surface"] == "molecule page text" for c in rv.excused["conventional-formula-in-editorial-text"])
    bad = run_page(rv, "/m/caffeine", mol_page("Caffeine", "C8H10N4O2", "194.19",
                                               "<p>Caffeine, written C8H10N4O3 here, is a purine.</p>"))
    assert ("formula", "two different values") in shapes(bad)
    top = run_page(rv, "/m/caffeine", mol_page("Caffeine", "N4O2C8H10", "194.19"))
    assert ("formula", "one value, written two ways") in shapes(top)     # the top line is not editorial text


def test_with_no_differences_nothing_is_excused(snap):
    rv = review(snap, differences={})
    run_page(rv, "/m/silicon-dioxide", mol_page("Silicon dioxide", "SiO2", "60.084"))
    assert ("formula", "one value, written two ways") in shapes(rv.findings) and not rv.excused


def test_a_difference_entry_must_carry_its_ruling(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump({"differences": {"x": {"fact": "formula", "shape": "s", "surfaces": ["a"],
                                                       "subjects": "panel-formula"}}}))
    with pytest.raises(ValueError, match="missing date, by, what, reason"):
        facts.load_differences(p)


# ── which pages: the seed and the Tuesday rule ──────────────────────────────────────────────────
PATHS = (["/", "/explore", "/roam", "/best", "/best/biggest", "/best/lightest"] + [f"/m/m{i}" for i in range(300)]
         + [f"/vs/p{i}" for i in range(50)] + [f"/in/h{i}" for i in range(40)] + [f"/whats-in/w{i}" for i in range(100)])


def test_the_sample_is_seeded_by_the_date_and_spread_across_families():
    a = facts.sample_paths(PATHS, {"/"}, dt.date(2026, 11, 27))
    assert a == facts.sample_paths(PATHS, {"/"}, dt.date(2026, 11, 27))
    assert a != facts.sample_paths(PATHS, {"/"}, dt.date(2026, 11, 28))
    assert len(a) == facts.SAMPLE and "/" not in a
    fams = {facts.family_of(p) for p in a}
    assert {"m", "vs", "in", "whats-in", "best"} <= fams


def test_the_tuesday_rule():
    assert facts.is_full_read(dt.date(2026, 12, 1))                         # a Tuesday
    assert not any(facts.is_full_read(dt.date(2026, 11, 30) + dt.timedelta(days=d)) for d in (0, 2, 3, 4, 5, 6))


SITEMAP = ("<urlset>" + "".join(f"<url><loc>https://moleculefinder.com{p}</loc></url>"
                                for p in ["/", "/m/caffeine", "/m/glucose", "/in/coffee"]) + "</urlset>")


def fake_site(broken: set[str] = frozenset()):
    seen = []

    def fetch(url):
        path = url[len("https://moleculefinder.com"):] or "/"
        seen.append(path)
        if path in broken:
            raise OSError("connection reset")
        if path == "/sitemap.xml":
            return 200, SITEMAP
        if path.startswith("/embed/"):
            return 200, json.dumps({"slug": path[7:-5], "name": path[7:-5].title(), "formula": None, "weight": None})
        if path.startswith("/m/") and path[3:] in MOLS:
            r = MOLS[path[3:]]
            return 200, f"<html><head><title>x</title></head><body><main>{mol_page(r['title'], r['molecular_formula'], r['molecular_weight'])}</main></body></html>"
        return 404, ""
    return fetch, seen


def test_a_tuesday_reads_every_sitemap_address(snap, tmp_path, monkeypatch):
    monkeypatch.setattr(facts, "PINNED", {"/m/caffeine": "a pinned page"})
    fetch, seen = fake_site()
    d = facts.run(snap=snap, out=tmp_path / "out", day=dt.date(2026, 12, 1), fetch=fetch, pause=0, workers=2)
    assert d["mode"] == "full"
    assert {"/", "/m/caffeine", "/m/glucose", "/in/coffee", "/embed/glucose.json"} <= set(seen)
    fetch, seen = fake_site()
    d = facts.run(snap=snap, out=tmp_path / "out2", day=dt.date(2026, 12, 2), fetch=fetch, pause=0, workers=2)
    assert d["mode"] == "sample"                         # a Wednesday: the pinned set and the day's sample
    assert d["live"]["sampled"] == facts.sample_paths(["/", "/m/caffeine", "/m/glucose", "/in/coffee"],
                                                      {"/m/caffeine"}, dt.date(2026, 12, 2))


def test_a_page_not_read_is_never_counted_as_agreeing(snap, tmp_path, monkeypatch):
    monkeypatch.setattr(facts, "PINNED", {"/m/caffeine": "a pinned page", "/m/glucose": "another"})
    fetch, _ = fake_site(broken={"/m/glucose"})
    d = facts.run(snap=snap, out=tmp_path / "out", day=dt.date(2026, 12, 1), fetch=fetch, pause=0, workers=1)
    assert {"path": "/m/glucose", "why": "OSError: connection reset"} in d["live"]["not_read"]
    assert "/m/glucose" not in d["live"]["read"]
    assert "1 pages not read" in d["verdict"] or "pages not read" in d["verdict"]
    assert all("/m/glucose" != c.split(" @ ")[-1] for k in d["classes"].values() for c in k["details"])
    rep = facts.render_md(d)
    assert "NOT READ https://moleculefinder.com/m/glucose" in rep
    # glucose's page facts were never compared: only caffeine's molecule page counted
    assert d["facts_compared"]["formula"]["pages"] >= 1
    assert (tmp_path / "out" / "facts-2026-12-01.json").exists()


# ── the repetition measure ──────────────────────────────────────────────────────────────────────
def test_repetition_on_three_small_pages():
    shared = "Every page of this family carries this sentence."
    n = len(shared)
    pages = {
        "/x/a": f"<main><p>{shared}</p><p>Only page a says this.</p></main>",
        "/x/b": f"<main><p>{shared}</p><p>Page b has a much longer sentence of its very own.</p></main>",
        "/x/c": f"<main><p>{shared}</p></main>",
    }
    texts = {"x": {p: facts.pieces(facts.page_of(p, h).body) for p, h in pages.items()}}
    r = facts.repetition(texts)["x"]
    own_a, own_b = len("Only page a says this."), len("Page b has a much longer sentence of its very own.")
    sa, sb = own_a / (n + own_a), own_b / (n + own_b)
    assert r["pages"] == 3
    assert r["unique_share_min"] == 0.0 and r["unique_share_max"] == round(sb, 3)
    assert r["unique_share_median"] == round(sa, 3)
    assert r["longest_shared"] == [{"text": shared, "chars": n, "pages": 3}]
    assert [x["path"] for x in r["least_own_text"]] == ["/x/c", "/x/a", "/x/b"]
    assert facts.repetition({"y": {"/y/a": ["one"], "/y/b": ["two"]}}) == {}         # under three pages: not measured


def test_pieces_keep_a_paragraphs_links_and_count_a_card():
    page = facts.page_of("/x", '<main><p>From the label on <a href="/d">DailyMed</a>, which lists 26.</p>'
                               '<ul><li>Outer item<p>Inner paragraph.</p></li></ul>'
                               '<div><a href="/m/c"><span>Caffeine</span> <span>C8H10N4O2</span></a></div></main>')
    assert facts.pieces(page.body) == ["From the label on DailyMed , which lists 26.", "Outer item",
                                       "Inner paragraph.", "Caffeine C8H10N4O2"]


def test_the_report_and_heartbeat(snap, tmp_path, monkeypatch):
    monkeypatch.setattr(facts, "PINNED", {"/m/caffeine": "a pinned page"})
    fetch, _ = fake_site()
    out = tmp_path / "out"
    d = facts.run(snap=snap, out=out, day=dt.date(2026, 12, 3), fetch=fetch, pause=0)
    md = (out / "facts-2026-12-03.md").read_text()
    assert md.splitlines()[0] == d["verdict"] and d["verdict"].startswith("VERDICT: ")
    assert "facts compared" in d["verdict"] and "pages not read" in d["verdict"]
    monkeypatch.setattr(facts, "run", lambda **kw: d)
    assert facts.main(["--out", str(out)]) == 0
    hb = json.loads((out / "facts-last-run.json").read_text())
    assert hb["state"] == "ran" and hb["exit"] == 0 and hb["verdict"] == d["verdict"]

    def broken(**kw):
        raise FileNotFoundError("no snapshot")
    monkeypatch.setattr(facts, "run", broken)
    assert facts.main(["--out", str(out)]) == 2
    hb = json.loads((out / "facts-last-run.json").read_text())
    assert hb["state"] == "could not run" and "no snapshot" in hb["reason"]


def test_a_local_builds_sitemap_names_the_production_host():
    xml = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://moleculefinder.com/</loc></url>'
           '<url><loc>https://moleculefinder.com/m/caffeine</loc></url></urlset>')
    assert facts.sitemap_paths(xml, "http://localhost:3137") == ["/", "/m/caffeine"]
    assert facts.sitemap_paths(xml) == ["/", "/m/caffeine"]


def test_the_one_ld50_phrase_names_its_own_molecule(snap):
    # "192 mg/kg (pure caffeine, rat, oral) against 2,000 mg/kg (pure candesartan, ...)": each figure belongs to the
    # molecule its phrase names, not the one named before it; a name with its own parentheses is read whole.
    rv = review(snap)
    ok = run_page(rv, "/classroom", "<main><p>The reported LD50 of Caffeine is 192 mg/kg (pure caffeine, rat, oral) "
                                    "against more than 2,000 mg/kg (pure candesartan, rat, oral).</p>")
    assert not [f for f in ok if f["fact"] == "LD50"]
    ctx = facts.ld50_context(" (pure copper(II) sulfate, rat, oral).")
    assert ctx["form"] == "pure copper(II) sulfate" and ctx["species"] == "rat" and ctx["route"] == "oral"
