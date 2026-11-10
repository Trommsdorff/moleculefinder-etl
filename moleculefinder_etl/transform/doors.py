"""The six doors (build plan everyday chemistry 2026-11, phase 4): hand seeds compiled into doors.json.

A door is a familiar thing (coffee, the medicine cabinet, bread, sugar and sweeteners, household
cleaners, citrus) opened into a numbered chain of molecules. Each door is one hand seed,
``sources/seeds/doors/<slug>.yaml``, and the web only renders what this module compiles.

**A seed holds references, not copies.** A stop names a molecule and, for each thing it shows, where
the words come from: the molecule's why-it-matters line (``why``), one sentence of a comparison's
paragraph found by its opening words (``sentence``), a comparison's answer line (``answer``), one
sentence of a curated editorial (``editorial``), a product comparison's answer line
(``product_pair``), a board's description (``board``), a world's blurb (``world``). Every text
reference carries ``pin``, the first 12 hex of sha256 over the whitespace-collapsed text (the same
hash claims_allowed.yaml pins by), so a quoted line that changes stops the build until someone looks
at the door again. Numbers are references too: a list entry's amount (``amount``), a label's
strength (``strength``), a molecule's sourced relative sweetness (``sweetness``). Presence marks are
read from the list the seed names (``mark: {list: ...}``), never written in the seed, so a stop can
show only a mark phase 1's seeds hold.

**The only new writing** is the door's title, lede and card line, each stop's heading and short nav
label, a sub-heading inside Read more, and a Where next card's link text and line. It is held to the
house rules (no dash, no advice word, no completeness phrase, no "LD50", no claim word without an
entry in claims_allowed.yaml: ``claims.corpus`` reads it as kind ``door``).

**Requires.** Any stop, card or Where next item may list ``requires:`` facts the new writing rests on
(ruling h: "the build stops if a product it names stops carrying the molecule the line names"):
``lists`` (a product page lists a molecule, optionally in a role, optionally with a purpose that
contains given words), ``not_lists``, ``in_list`` (a list, product page or curated hub, carries it),
``page`` (a page exists), ``formula_delta`` (two formulas differ by exactly the given atoms),
``sweetness_at_least``, ``says`` (a referenced line contains given words). Resolving a reference is
itself a requirement: a mark from a list the molecule left, a label's strength for an active the
label dropped, or a sentence whose opening words no longer match all stop the build.

**Where it runs.** ``compile_doors`` runs in the export preflight (``pipeline._preflight``), against
the built catalog, the compiled comparisons, the boards and the product pages the transform staged,
so a failure stops the run before the Supabase load and before anything is written, names the door
and the fact, and leaves last week's snapshot live (the existing refusal path). It raises
``DoorError`` listing every problem at once.

**Groups and dark pages.** Three doors are upgraded in place (an existing ``/whats-in/<product>``
page: coffee, bread, citrus); three are new group pages (``/whats-in/<slug>``: the medicine cabinet,
sugar and sweeteners, household cleaners). A group is a source type beside the PFAS class: its
molecule list is its chain, it must hold at least ``products.MIN_MOLECULES`` molecules (the same
three-molecule gate), and it lists its ``members``, the label pages and lists it gathers. The groups
are seeded ``live: false``: they are in doors.json and nowhere else (not products.json, the search
index or the sitemap) until phase 7 flips them. A dark door names ``interim``, the existing page its
home card links to until then.

**In-place doors keep every molecule.** For a door on an existing product page, the molecules its
stops show plus ``also`` must equal that page's list exactly, so the upgraded page loses nothing; a
list edited without its door stops the build.

``what_it_does.yaml`` (the molecule page's "What it does", phase 8) lives here too: for a molecule
with a curated mechanism, sentences by reference to a comparison's paragraph (pinned) and the name
of a hand-made illustration, or none. ``attach_what_it_does`` stamps it on the records in the
transform; a molecule with no entry carries no field.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

SEEDS_DIR = Path(__file__).resolve().parent.parent / "sources" / "seeds"
DOORS_DIR = SEEDS_DIR / "doors"
WHAT_IT_DOES_YAML = SEEDS_DIR / "what_it_does.yaml"

# The six, in the home page's order (the README's rulings; the plan's phase 4 table).
DOOR_ORDER = ("coffee", "medicine-cabinet", "bread", "sugar-and-sweeteners", "household-cleaners", "citrus")
# The three new group pages: permanent slugs once live (the plan, "Slugs for the new group pages").
GROUPS = ("medicine-cabinet", "sugar-and-sweeteners", "household-cleaners")
# Illustrations a what-it-does entry may name: hand-made SVG assets in the web repo (phase 8 adds
# the file and its component). An unknown name stops the build.
ILLUSTRATIONS = ("receptor-block",)

MIN_MOLECULES = 3                     # the product gate's floor (products.MIN_MOLECULES)

# House rules for every string a door shows. The web's lib/copy-rules.ts ADVICE is the same word list.
DASH = re.compile("[—–]")
ADVICE = re.compile(r"\b(safe|safer|unsafe|should|recommend|take \d|dose|dosing|consult|per day)\b", re.IGNORECASE)
COMPLETENESS = ("every molecule in", "all the molecules in", "the molecules in it")
# The narrower advice patterns of the /vs prose, for new writing (an amount or a strength is a
# number field, never new writing, so "500 mg" there is the label's own figure).
NEW_WRITING_ADVICE = (
    r"\byou should\b", r"\bconsult\b", r"\bask your doctor\b", r"\bwe recommend\b", r"\brecommended dose\b",
    r"\btake \d", r"\b\d+(?:\.\d+)?\s*mg\b(?!\s*/)", r"\bper day\b", r"\bdaily dose\b", r"\btwice a day\b",
    r"\bbetter (?:choice|option) (?:for|if)\b",
)
# Acetaldehyde and the hangover (Garrett, 2026-11-10): any door string on it says exactly this.
HANGOVER_WORDING = "long blamed for part of a hangover"

LENGTHS = {  # new writing, in characters (min, max)
    "title": (12, 60), "lede": (60, 260), "card.line": (40, 130), "card.go": (8, 40),
    "heading": (8, 72), "nav": (3, 24), "subheading": (8, 72), "where_next.go": (8, 50),
    "where_next.line": (20, 130), "page_title": (20, 65), "description": (100, 160),
}

TEXT_KINDS = ("why", "sentence", "answer", "editorial", "product_pair", "board", "world")
REQUIRE_KINDS = ("lists", "not_lists", "in_list", "page", "formula_delta", "sweetness_at_least", "says")
TARGET_KINDS = ("molecule", "pair", "product", "product_pair", "hub", "board", "world")


class DoorError(SystemExit):
    """A door seed does not compile: a reference does not resolve or a requirement does not hold."""


def pin(text: str) -> str:
    """The short hash a reference pins its text by (the same as claims.line_id)."""
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8")).hexdigest()[:12]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join((text or "").split())) if s]


def load_seeds(directory: Path = DOORS_DIR) -> dict[str, dict]:
    """Every door seed, keyed by its slug (the file name, which must equal the seed's ``slug``)."""
    out: dict[str, dict] = {}
    for f in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or {}
        out[f.stem] = data
    return out


def load_what_it_does(path: Path = WHAT_IT_DOES_YAML) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {str(k): v or {} for k, v in (yaml.safe_load(path.read_text()) or {}).items()}


def _formula_counts(f: str | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for el, n in re.findall(r"([A-Z][a-z]?)(-?\d*)", f or ""):
        out[el] = out.get(el, 0) + (int(n) if n else 1)
    return out


class _Catalog:
    """What a door may refer to: the built records, comparisons, boards and product pages."""

    def __init__(self, molecules, comparisons, boards, products, product_pairs, worlds):
        self.mol = {m["slug"]: m for m in molecules}
        self.cmp = comparisons or {}
        self.boards = boards or {}
        self.products = {p["slug"]: p for p in (products or [])}
        self.pairs = {p["slug"]: p for p in (product_pairs or [])}
        self.worlds = {w["slug"]: w for w in (worlds or [])}
        # Curated hubs (/in/<slug>) of kind food or product, from the records' categories.
        self.hubs: dict[str, dict] = {}
        self.hub_rows: dict[tuple[str, str], dict] = {}
        self.all_hubs: dict[str, dict] = {}
        for m in molecules:
            for c in m.get("categories") or []:
                self.all_hubs.setdefault(c["slug"], {"slug": c["slug"], "name": c.get("name"), "kind": c.get("kind")})
                if c.get("kind") in ("food", "product"):
                    self.hubs.setdefault(c["slug"], {"slug": c["slug"], "name": c.get("name"), "kind": c.get("kind")})
                    self.hub_rows[(c["slug"], m["slug"])] = c


def _list_row(cat: _Catalog, lst: str, slug: str) -> tuple[dict | None, dict | None]:
    """A molecule's row on a list: a product page's molecule row, else a curated hub's category."""
    p = cat.products.get(lst)
    if p is not None:
        for row in p["molecules"]:
            if row["slug"] == slug:
                return row, {"kind": "product", "slug": lst, "name": p["name"], "href": f"/whats-in/{lst}"}
        return None, {"kind": "product", "slug": lst, "name": p["name"], "href": f"/whats-in/{lst}"}
    h = cat.hubs.get(lst)
    if h is not None:
        row = cat.hub_rows.get((lst, slug))
        return row, {"kind": "hub", "slug": lst, "name": h["name"], "href": f"/in/{lst}"}
    return None, None


def _list_members(cat: _Catalog, lst: str) -> list[str] | None:
    p = cat.products.get(lst)
    if p is not None:
        return [r["slug"] for r in p["molecules"]]
    if lst in cat.hubs:
        return sorted(s for (h, s) in cat.hub_rows if h == lst)
    return None


def _mol_ref(cat: _Catalog, slug: str) -> dict:
    m = cat.mol[slug]
    return {"slug": slug, "title": m["title"], "formula": m.get("molecular_formula"),
            "has_structure": bool(m.get("structure_svg"))}


class _Compiler:
    def __init__(self, cat: _Catalog, door: str):
        self.cat = cat
        self.door = door
        self.problems: list[str] = []
        self.new_strings: list[tuple[str, str]] = []      # (where, text): new writing
        self.shown_strings: list[tuple[str, str]] = []    # (where, text): every string the door shows

    def fail(self, where: str, msg: str) -> None:
        self.problems.append(f"door {self.door}: {where}: {msg}")

    # ── new writing ─────────────────────────────────────────────────────────
    def new(self, where: str, text, length_key: str | None = None) -> dict | None:
        if not isinstance(text, str) or not text.strip():
            self.fail(where, "missing new writing")
            return None
        text = " ".join(text.split())
        if length_key:
            lo, hi = LENGTHS[length_key]
            if not lo <= len(text) <= hi:
                self.fail(where, f"{len(text)} characters, the rule is {lo} to {hi}")
        self.new_strings.append((where, text))
        self.shown_strings.append((where, text))
        return {"text": text, "new": True}

    def fill(self, text: str, counts: dict[str, int]) -> str:
        """``{count:<list>}`` in new writing: the number of molecules on that list, from the data."""
        def sub(m):
            lst = m.group(1)
            if lst not in counts:
                self.fail("lede", f"{{count:{lst}}} names a list this door does not read")
                return m.group(0)
            return str(counts[lst])
        return re.sub(r"\{count:([a-z0-9-]+)\}", sub, text)

    # ── references ──────────────────────────────────────────────────────────
    def text(self, where: str, ref, pinned: bool = True) -> dict | None:
        if not isinstance(ref, dict):
            self.fail(where, f"a text reference must be a mapping, got {ref!r}")
            return None
        kinds = [k for k in TEXT_KINDS if k in ref]
        if len(kinds) != 1:
            self.fail(where, f"a text reference names exactly one of {TEXT_KINDS}, got {sorted(ref)}")
            return None
        kind = kinds[0]
        resolved, source = self._resolve_text(where, kind, ref)
        if resolved is None:
            return None
        want = ref.get("pin")
        got = pin(resolved)
        if pinned and want != got:
            self.fail(where, f"{kind} {ref[kind]!r}: the quoted text is {'new' if not want else 'changed'} "
                             f"(pin {want!r}, text now {got}): read it again, then update the pin. "
                             f"Text: {resolved!r}")
        self.shown_strings.append((where, resolved))
        return {"text": resolved, "new": False, "ref": {**source, "pinned": pinned}}

    def _resolve_text(self, where, kind, ref):
        cat = self.cat
        key = ref[kind]
        if kind == "why":
            m = cat.mol.get(key)
            if m is None:
                self.fail(where, f"why: {key!r} is not a catalog molecule")
                return None, None
            t = (m.get("why_it_matters") or {}).get("text")
            if not t:
                self.fail(where, f"why: {key} has no why-it-matters line")
                return None, None
            return " ".join(t.split()), {"kind": "why", "molecule": key, "source": "curated"}
        if kind in ("sentence", "answer"):
            c = cat.cmp.get(key)
            if c is None:
                self.fail(where, f"{kind}: {key!r} has no comparison page")
                return None, None
            if kind == "answer":
                return c["answer"], {"kind": "answer", "pair": key, "href": f"/vs/{key}", "source": "curated"}
            starts = ref.get("starts")
            hits = [s for s in sentences(c["text"]) if starts and s.startswith(starts)]
            if len(hits) != 1:
                self.fail(where, f"sentence: no single sentence of {key} starts {starts!r} ({len(hits)} found)")
                return None, None
            return hits[0], {"kind": "sentence", "pair": key, "starts": starts, "href": f"/vs/{key}",
                             "source": "curated"}
        if kind == "editorial":
            m = cat.mol.get(key)
            eds = [b["body_md"] for b in (m or {}).get("content_blocks") or [] if b.get("block_type") == "editorial"]
            starts = ref.get("starts")
            hits = [s for e in eds for s in sentences(e) if starts and s.startswith(starts)]
            if len(hits) != 1:
                self.fail(where, f"editorial: no single sentence of {key}'s editorial starts {starts!r}")
                return None, None
            return hits[0], {"kind": "editorial", "molecule": key, "starts": starts, "source": "curated"}
        if kind == "product_pair":
            p = cat.pairs.get(key)
            if p is None:
                self.fail(where, f"product_pair: {key!r} is not a built product comparison")
                return None, None
            return p["answer"], {"kind": "product_pair", "pair": key, "href": f"/whats-in/{key}", "source": "curated"}
        if kind == "board":
            b = cat.boards.get(key)
            if b is None or not b.get("entries"):
                self.fail(where, f"board: {key!r} is not a board with entries")
                return None, None
            first = sentences(b["description"])[0]
            return first, {"kind": "board", "board": key, "href": f"/best/{key}", "source": "curated"}
        if kind == "world":
            w = cat.worlds.get(key)
            if w is None or not w.get("blurb"):
                self.fail(where, f"world: {key!r} is not a world with a blurb")
                return None, None
            return w["blurb"], {"kind": "world", "world": key, "href": f"/roam/{key}", "source": "curated"}
        return None, None

    def number(self, where: str, ref, molecule: str | None) -> dict | None:
        if not isinstance(ref, dict) or len(ref) != 1:
            self.fail(where, f"a number names exactly one of amount, strength, sweetness, got {ref!r}")
            return None
        cat = self.cat
        if "amount" in ref:
            lst = ref["amount"]["list"]
            slug = ref["amount"].get("molecule", molecule)
            row, info = _list_row(cat, lst, slug)
            note = (row or {}).get("note")
            if row is None or not note:
                self.fail(where, f"amount: {slug} has no amount on the {lst} list")
                return None
            text = note.replace("~", "about ")
            self.shown_strings.append((where, text))
            return {"text": text, "kind": "editorial", "list": info, "molecule": slug,
                    "source": "curated"}
        if "strength" in ref:
            label = ref["strength"]["label"]
            slug = ref["strength"].get("molecule", molecule)
            row = self._active(where, label, slug)
            if row is None:
                return None
            if not row.get("strength"):
                self.fail(where, f"strength: {label}'s label states no strength for {slug}")
                return None
            self.shown_strings.append((where, row["strength"]))
            return {"text": row["strength"], "per": row.get("strength_per"), "kind": "label",
                    "product": label, "molecule": slug, "source": "dailymed"}
        if "sweetness" in ref:
            slug = ref["sweetness"]
            m = cat.mol.get(slug) or {}
            v = m.get("relative_sweetness")
            if v is None:
                self.fail(where, f"sweetness: {slug} has no sourced relative sweetness")
                return None
            text = f"{v:g} × sugar"
            return {"text": text, "value": v, "kind": "measured", "molecule": slug,
                    "source": m.get("relative_sweetness_source")}
        self.fail(where, f"unknown number {ref!r}")
        return None

    def _active(self, where, label, slug):
        p = self.cat.products.get(label)
        if p is None or (p.get("source") or {}).get("type") != "dailymed":
            self.fail(where, f"{label!r} is not a DailyMed label page")
            return None
        rows = [r for r in p["molecules"] if r["slug"] == slug and r["role"] == "active"]
        if not rows:
            self.fail(where, f"{p['name']}'s label no longer lists {slug} as an active ingredient")
            return None
        return rows[0]

    def mark(self, where: str, ref, slug: str) -> tuple[dict | None, dict | None]:
        """The presence mark a list's own seed holds for this molecule (phase 1), with the list."""
        if ref is None:
            return None, None
        if not isinstance(ref, dict) or "list" not in ref:
            self.fail(where, f"mark must be {{list: <slug>}}, got {ref!r}")
            return None, None
        row, info = _list_row(self.cat, ref["list"], slug)
        if info is None:
            self.fail(where, f"mark: {ref['list']!r} is not a product page or a curated list")
            return None, None
        if row is None:
            self.fail(where, f"mark: the {info['name']} list no longer carries {slug}")
            return None, info
        presence = row.get("presence")
        if not presence:
            self.fail(where, f"mark: {slug} on the {info['name']} list has no presence mark")
        return presence, info

    def label(self, where: str, ref) -> dict | None:
        """A label row: what the label states for one active, its purpose and strength."""
        lab, slug = ref.get("label"), ref.get("molecule")
        row = self._active(where, lab, slug)
        if row is None:
            return None
        p = self.cat.products[lab]
        for s in (row.get("purpose"), row.get("strength")):
            if s:
                self.shown_strings.append((where, s))
        return {"product": lab, "name": p["name"], "href": f"/whats-in/{lab}", "molecule": slug,
                "listed_as": row.get("listed_as"), "purpose": row.get("purpose"),
                "strength": row.get("strength"), "strength_per": row.get("strength_per"),
                "presence": row.get("presence"), "source": "dailymed", "setid": (p.get("source") or {}).get("setid")}

    def target(self, where: str, ref) -> dict | None:
        if not isinstance(ref, dict):
            self.fail(where, f"a link target must be a mapping, got {ref!r}")
            return None
        kinds = [k for k in TARGET_KINDS if k in ref]
        if len(kinds) != 1:
            self.fail(where, f"a link target names exactly one of {TARGET_KINDS}, got {sorted(ref)}")
            return None
        kind, key = kinds[0], ref[kinds[0]]
        cat = self.cat
        if kind == "molecule" and key in cat.mol:
            return {"kind": kind, "slug": key, "href": f"/m/{key}", "label": cat.mol[key]["title"]}
        if kind == "pair" and key in cat.cmp:
            a, b = cat.cmp[key]["a"], cat.cmp[key]["b"]
            return {"kind": kind, "slug": key, "href": f"/vs/{key}",
                    "label": f"{cat.mol[a]['title']} vs {cat.mol[b]['title']}"}
        if kind == "product" and key in cat.products:
            return {"kind": kind, "slug": key, "href": f"/whats-in/{key}", "label": cat.products[key]["name"]}
        if kind == "product_pair" and key in cat.pairs:
            p = cat.pairs[key]
            return {"kind": kind, "slug": key, "href": f"/whats-in/{key}",
                    "label": f"{cat.products[p['a']]['name']} vs {cat.products[p['b']]['name']}"}
        if kind == "hub" and key in cat.all_hubs:
            return {"kind": kind, "slug": key, "href": f"/in/{key}", "label": cat.all_hubs[key]["name"]}
        if kind == "board" and (cat.boards.get(key) or {}).get("entries"):
            return {"kind": kind, "slug": key, "href": f"/best/{key}", "label": cat.boards[key]["title"]}
        if kind == "world" and key in cat.worlds:
            return {"kind": kind, "slug": key, "href": f"/roam/{key}", "label": cat.worlds[key].get("title")}
        self.fail(where, f"{kind} {key!r} has no live page")
        return None

    # ── requires ────────────────────────────────────────────────────────────
    def requires(self, where: str, facts) -> list[str]:
        out = []
        for fact in facts or []:
            if not isinstance(fact, dict) or len(fact) != 1 or next(iter(fact)) not in REQUIRE_KINDS:
                self.fail(where, f"requires: {fact!r} is not one of {REQUIRE_KINDS}")
                continue
            kind, arg = next(iter(fact.items()))
            ok, said = self._holds(where, kind, arg)
            if not ok:
                self.fail(where, f"requires {kind}: {said}")
            out.append(said)
        return out

    def _holds(self, where, kind, arg) -> tuple[bool, str]:
        cat = self.cat
        if kind in ("lists", "not_lists"):
            p = cat.products.get(arg["product"])
            if p is None:
                return False, f"{arg['product']!r} is not a product page"
            rows = [r for r in p["molecules"] if r["slug"] == arg["molecule"]
                    and ("role" not in arg or r["role"] == arg["role"])]
            if "purpose_has" in arg:
                rows = [r for r in rows if arg["purpose_has"].lower() in (r.get("purpose") or "").lower()]
            role = f" as {arg['role']}" if "role" in arg else ""
            purpose = f" for {arg['purpose_has']!r}" if "purpose_has" in arg else ""
            if kind == "lists":
                return bool(rows), f"{p['name']} lists {arg['molecule']}{role}{purpose}"
            return not rows, f"{p['name']} does not list {arg['molecule']}{role}"
        if kind == "in_list":
            row, info = _list_row(cat, arg["list"], arg["molecule"])
            name = info["name"] if info else arg["list"]
            return row is not None, f"the {name} list carries {arg['molecule']}"
        if kind == "page":
            t = self.target(where, arg)
            return t is not None, f"{(t or {}).get('href', arg)} is a live page"
        if kind == "formula_delta":
            a, b = cat.mol.get(arg["a"]), cat.mol.get(arg["b"])
            if not a or not b:
                return False, f"{arg['a']} and {arg['b']} are not both catalog molecules"
            fa, fb = _formula_counts(a.get("molecular_formula")), _formula_counts(b.get("molecular_formula"))
            delta = {el: fa.get(el, 0) - fb.get(el, 0) for el in set(fa) | set(fb)}
            delta = {el: n for el, n in delta.items() if n}
            return delta == _formula_counts(arg["delta"]), \
                f"{a['molecular_formula']} minus {b['molecular_formula']} is {arg['delta']}"
        if kind == "sweetness_at_least":
            v = (cat.mol.get(arg["molecule"]) or {}).get("relative_sweetness")
            return v is not None and v >= arg["value"], f"{arg['molecule']} is at least {arg['value']} × sugar"
        if kind == "says":
            t = self.text(where, arg["ref"])
            words = arg["words"]
            return bool(t) and words in t["text"], f"the referenced line says {words!r}"
        return False, f"unknown requirement {kind}"


def _check_strings(c: _Compiler, claim_problems: list[str]) -> None:
    for where, text in c.shown_strings:
        if DASH.search(text):
            c.fail(where, f"an em or en dash: {text!r}")
        if ADVICE.search(text):
            c.fail(where, f"an advice or dosing word ({ADVICE.search(text).group(0)!r}): {text!r}")
        low = text.lower()
        for phrase in COMPLETENESS:
            if phrase in low:
                c.fail(where, f"a completeness phrase ({phrase!r}): {text!r}")
        if "ld50" in low:
            c.fail(where, f"an LD50 on a door: {text!r}")
        if "inferred" in low:
            c.fail(where, f"'inferred' on a door: {text!r}")
        if "hangover" in low and HANGOVER_WORDING not in low:
            c.fail(where, f"a hangover line must say {HANGOVER_WORDING!r}: {text!r}")
    for where, text in c.new_strings:
        for pat in NEW_WRITING_ADVICE:
            if re.search(pat, text, re.IGNORECASE):
                c.fail(where, f"new writing reads as advice or dosing (/{pat}/): {text!r}")
    c.problems.extend(claim_problems)


def _stop(c: _Compiler, n: int, s: dict, counts_shown: list[str]) -> dict:
    where = f"stop {n}"
    out: dict = {"n": n, "key": s.get("key") or f"s{n}"}
    out["heading"] = c.new(f"{where} heading", s.get("heading"), "heading")
    lead = s.get("molecule")
    if lead is not None and lead not in c.cat.mol:
        c.fail(where, f"{lead!r} is not a catalog molecule")
        lead = None
    nav = s.get("nav")
    out["nav"] = c.new(f"{where} nav", nav, "nav") if nav else (
        {"text": c.cat.mol[lead]["title"], "new": False, "ref": {"kind": "title", "molecule": lead}} if lead else None)
    if out["nav"] is None:
        c.fail(where, "a stop with no lead molecule needs a nav label")
    out["molecule"] = _mol_ref(c.cat, lead) if lead else None
    if lead:
        counts_shown.append(lead)
        out["presence"], out["presence_list"] = c.mark(f"{where} mark", s.get("mark"), lead)
        if s.get("mark") is None:
            out["presence"], out["presence_list"] = None, None
            out["presence_absent"] = c.new(f"{where} unmarked", s.get("unmarked"), None) if s.get("unmarked") else None
            if not s.get("unmarked"):
                c.fail(where, "a lead molecule with no mark must say why in `unmarked` (shown in Sources and notes)")
        out["text"] = c.text(f"{where} text", s.get("text"))
        out["number"] = c.number(f"{where} number", s["number"], lead) if s.get("number") else None
    out["labels"] = [x for x in (c.label(f"{where} label", r) for r in s.get("labels") or []) if x]
    items = []
    for i, it in enumerate(s.get("items") or [], 1):
        iw = f"{where} item {i}"
        slug = it.get("molecule")
        if slug not in c.cat.mol:
            c.fail(iw, f"{slug!r} is not a catalog molecule")
            continue
        counts_shown.append(slug)
        item = {"molecule": _mol_ref(c.cat, slug)}
        item["presence"], item["presence_list"] = c.mark(f"{iw} mark", it.get("mark"), slug)
        if it.get("mark") is None:
            c.fail(iw, "an item takes its mark from a list (mark: {list: ...})")
        item["number"] = c.number(f"{iw} number", it["number"], slug) if it.get("number") else None
        item["text"] = c.text(f"{iw} text", it["text"]) if it.get("text") else None
        comp = it.get("companion")
        if comp is not None:
            if comp not in c.cat.mol:
                c.fail(iw, f"companion {comp!r} is not a catalog molecule")
            else:
                item["companion"] = _mol_ref(c.cat, comp)
                item["companion_presence"], item["companion_list"] = c.mark(f"{iw} companion mark",
                                                                            it.get("mark"), comp)
                counts_shown.append(comp)
        items.append(item)
    out["items"] = items
    more = []
    for i, r in enumerate(s.get("more") or [], 1):
        mw = f"{where} read more {i}"
        if isinstance(r, dict) and "subheading" in r:
            more.append({"subheading": c.new(mw, r["subheading"], "subheading")})
        elif isinstance(r, dict) and "aside" in r:
            a = r["aside"]
            slug = a.get("molecule")
            if slug not in c.cat.mol:
                c.fail(mw, f"aside {slug!r} is not a catalog molecule")
                continue
            counts_shown.append(slug)
            pres, lst = c.mark(f"{mw} aside mark", a.get("mark"), slug)
            more.append({"aside": {"molecule": _mol_ref(c.cat, slug), "presence": pres, "presence_list": lst,
                                   "heading": c.new(f"{mw} aside heading", a.get("heading"), "subheading"),
                                   "text": c.text(f"{mw} aside text", a.get("text"))}})
        else:
            t = c.text(mw, r)
            if t:
                more.append(t)
    out["more"] = more
    out["links"] = [x for x in (c.target(f"{where} link", t) for t in s.get("links") or []) if x]
    out["requires"] = c.requires(where, s.get("requires"))
    if not lead and not items and not out["labels"]:
        c.fail(where, "a stop shows a lead molecule, items or label rows")
    return out


def compile_door(cat: _Catalog, slug: str, seed: dict, claim_problems: list[str] | None = None) -> tuple[dict, list[str], list[tuple[str, str]]]:
    """One door. Returns (compiled door, problems, new writing as (where, text))."""
    c = _Compiler(cat, slug)
    if seed.get("slug") != slug:
        c.fail("slug", f"the seed's slug {seed.get('slug')!r} is not its file name {slug!r}")
    page = seed.get("page") or {}
    group = page.get("group")
    product = page.get("product")
    if bool(group) == bool(product):
        c.fail("page", "a door is on exactly one of an existing product page or a new group")
    live = bool(page.get("live", product is not None))
    if group and group != slug:
        c.fail("page", f"a group page's slug is the door's slug ({slug}), not {group!r}")
    if group and group not in GROUPS:
        c.fail("page", f"{group!r} is not one of the planned group pages {GROUPS}")
    if group and group in cat.products:
        c.fail("page", f"/whats-in/{group} is already a product page")
    if product and product not in cat.products:
        c.fail("page", f"/whats-in/{product} is not a product page")
    door: dict = {"slug": slug, "order": DOOR_ORDER.index(slug) + 1 if slug in DOOR_ORDER else None,
                  "kind": "group" if group else "product", "live": live,
                  "href": f"/whats-in/{slug}", "confidence": "from_source", "source": "curated"}
    if door["order"] is None:
        c.fail("slug", f"{slug!r} is not one of the six doors {DOOR_ORDER}")
    door["name"] = c.new("name", seed.get("name"), None)
    card = seed.get("card") or {}
    door["card"] = {"line": c.new("card line", card.get("line"), "card.line"),
                    "go": c.new("card go", card.get("go"), "card.go"),
                    "requires": c.requires("card", card.get("requires"))}
    interim = None
    if not live:
        interim = c.target("interim", seed.get("interim")) if seed.get("interim") else None
        if interim is None:
            c.fail("interim", "a dark door names the existing page its home card links to until it is live")
    elif seed.get("interim"):
        c.fail("interim", "a live door links to its own page; interim is for a dark door")
    door["interim"] = interim
    door["card"]["href"] = door["href"] if live else (interim or {}).get("href")
    if group:
        door["page_title"] = c.new("page_title", seed.get("page_title"), "page_title")
        door["description"] = c.new("description", seed.get("description"), "description")
    door["title"] = c.new("title", seed.get("title"), "title")
    # The lede may count a list from the data: {count:coffee}.
    counts = {lst: len(_list_members(cat, lst) or []) for lst in re.findall(r"\{count:([a-z0-9-]+)\}", seed.get("lede") or "")
              if _list_members(cat, lst) is not None}
    lede = seed.get("lede")
    door["lede"] = c.new("lede", c.fill(" ".join((lede or "").split()), counts) if lede else lede, "lede")
    door["requires"] = c.requires("title and lede", seed.get("requires"))

    shown: list[str] = []
    door["stops"] = [_stop(c, n, s, shown) for n, s in enumerate(seed.get("stops") or [], 1)]
    if not 3 <= len(door["stops"]) <= 6:
        c.fail("stops", f"{len(door['stops'])} stops, a chain has 3 to 6")

    # "Also on the list": the list's other molecules, each with its own why-it-matters line (not
    # pinned: it is the list page's own content, shown there today) and its mark from the list. An
    # in-place door reads its page's list; a group names the member list each comes from.
    also = []
    for entry in seed.get("also") or []:
        slug_, lst = (entry, product) if isinstance(entry, str) else (entry.get("molecule"), entry.get("list"))
        if slug_ not in cat.mol:
            c.fail("also", f"{slug_!r} is not a catalog molecule")
            continue
        if not lst:
            c.fail("also", f"{slug_}: a group's also entry names the member list it is on")
            continue
        pres, info = c.mark(f"also {slug_}", {"list": lst}, slug_)
        also.append({"molecule": _mol_ref(cat, slug_), "presence": pres, "presence_list": info,
                     "text": c.text(f"also {slug_}", {"why": slug_}, pinned=False)})
    door["also"] = also

    nexts = []
    for i, w in enumerate(seed.get("where_next") or [], 1):
        ww = f"where next {i}"
        t = c.target(ww, w.get("to"))
        item = {"to": t, "go": c.new(f"{ww} go", w.get("go"), "where_next.go")}
        if w.get("molecule"):
            if w["molecule"] in cat.mol:
                item["molecule"] = _mol_ref(cat, w["molecule"])
            else:
                c.fail(ww, f"{w['molecule']!r} is not a catalog molecule")
        if w.get("pair_drawing"):
            item["pair_drawing"] = w["pair_drawing"]
        if w.get("text"):
            item["text"] = c.text(f"{ww} text", w["text"])
        if w.get("line"):
            item["line"] = c.new(f"{ww} line", w["line"], "where_next.line")
        if not item.get("text") and not item.get("line"):
            c.fail(ww, "a Where next card carries a referenced text or a line")
        item["requires"] = c.requires(ww, w.get("requires"))
        nexts.append(item)
    if len(nexts) != 2:
        c.fail("where next", f"{len(nexts)} cards, the page has two")
    door["where_next"] = nexts

    members = []
    for m in seed.get("members") or []:
        t = c.target("members", m)
        if t:
            members.append(t)
    if group and not members:
        c.fail("members", "a group lists the label pages and lists it gathers")
    if product and members:
        c.fail("members", "an in-place door gathers nothing; members are for a group")
    door["members"] = members

    chain = list(dict.fromkeys(shown))
    door["molecules"] = list(dict.fromkeys(chain + [a["molecule"]["slug"] for a in also]))
    if product and product in cat.products:
        listed = [r["slug"] for r in cat.products[product]["molecules"]]
        missing = [s for s in listed if s not in door["molecules"]]
        extra = [s for s in [a["molecule"]["slug"] for a in also] if s not in listed]
        if missing:
            c.fail("also", f"the {cat.products[product]['name']} list carries {missing}, which this door does not show: "
                           f"add them to a stop or to also, so the upgraded page loses nothing")
        if extra:
            c.fail("also", f"{extra} are not on the {cat.products[product]['name']} list")
    if group:
        member_lists = [m["slug"] for m in members if m["kind"] in ("product", "hub")]
        for a in also:
            s = a["molecule"]["slug"]
            if not any(_list_row(cat, lst, s)[0] for lst in member_lists):
                c.fail("also", f"{s} is on none of the group's member lists")
        if len(chain) < MIN_MOLECULES:
            c.fail("molecules", f"a group passes the {MIN_MOLECULES}-molecule gate; its chain holds {len(chain)}")
    door["steps"] = [{"n": s["n"], "href": f"#s{s['n']}", "nav": s["nav"]} for s in door["stops"]]
    _check_strings(c, claim_problems or [])
    return door, c.problems, c.new_strings


def compile_doors(molecules: list[dict], comparisons: dict, boards: dict, products: list[dict] | None,
                  product_pairs: list[dict] | None, worlds: list[dict] | None = None,
                  seeds: dict[str, dict] | None = None) -> dict:
    """Every door, checked; raises ``DoorError`` naming every problem. Returns doors.json's content."""
    from . import claims
    seeds = load_seeds() if seeds is None else seeds
    if not seeds:
        return {"doors": []}
    if worlds is None:
        from .relationships import load_worlds
        worlds = load_worlds()
    cat = _Catalog(molecules, comparisons, boards, products, product_pairs, worlds)
    claim_problems = [p for p in claims.line_problems() if p.startswith("door ")]
    doors, problems = [], []
    for slug in sorted(seeds, key=lambda s: DOOR_ORDER.index(s) if s in DOOR_ORDER else 99):
        door, probs, _ = compile_door(cat, slug, seeds[slug], [p for p in claim_problems if p.startswith(f"door {slug}.")])
        doors.append(door)
        problems += probs
    if set(seeds) != set(DOOR_ORDER):
        problems.append(f"doors: the seeds are {sorted(seeds)}, the plan's six are {sorted(DOOR_ORDER)}")
    # Titles, card lines, page titles and descriptions are each unique across the doors; a group's
    # description is unique against every molecule description too.
    for field in ("title", "lede", "page_title", "description"):
        seen: dict[str, str] = {}
        for d in doors:
            t = ((d.get(field) or {}) or {}).get("text")
            if t:
                if t.lower() in seen:
                    problems.append(f"doors: {d['slug']} and {seen[t.lower()]} share a {field}")
                seen[t.lower()] = d["slug"]
    lines = [(d["slug"], (d["card"]["line"] or {}).get("text")) for d in doors]
    if len({t for _, t in lines if t}) != len([t for _, t in lines if t]):
        problems.append("doors: two card lines are the same")
    descs = {(m.get("description") or "").lower() for m in molecules}
    names = {p["name"].lower() for p in (products or [])}
    for d in doors:
        if d["kind"] == "group":
            if ((d.get("description") or {}).get("text") or "").lower() in descs:
                problems.append(f"doors: {d['slug']}'s description repeats a molecule page's")
            if (d["name"] or {}).get("text", "").lower() in names:
                problems.append(f"doors: {d['slug']}'s name is a product page's name")
    if problems:
        raise DoorError("door seeds do not compile (sources/seeds/doors/):\n  " + "\n  ".join(problems))
    return {"doors": doors}


def door_strings(seeds: dict[str, dict] | None = None) -> list[tuple[str, str]]:
    """The new writing in every door seed as (key, text), for the claim rule's corpus (kind ``door``)."""
    seeds = load_seeds() if seeds is None else seeds
    out: list[tuple[str, str]] = []

    def add(key, v):
        if isinstance(v, str) and v.strip():
            out.append((key, " ".join(v.split())))

    for slug, s in seeds.items():
        add(f"{slug}.name", s.get("name"))
        add(f"{slug}.title", s.get("title"))
        add(f"{slug}.lede", s.get("lede"))
        add(f"{slug}.page_title", s.get("page_title"))
        add(f"{slug}.description", s.get("description"))
        add(f"{slug}.card.line", (s.get("card") or {}).get("line"))
        add(f"{slug}.card.go", (s.get("card") or {}).get("go"))
        for n, st in enumerate(s.get("stops") or [], 1):
            add(f"{slug}.stop{n}.heading", st.get("heading"))
            add(f"{slug}.stop{n}.nav", st.get("nav"))
            add(f"{slug}.stop{n}.unmarked", st.get("unmarked"))
            for i, r in enumerate(st.get("more") or [], 1):
                if isinstance(r, dict):
                    add(f"{slug}.stop{n}.more{i}", r.get("subheading"))
                    add(f"{slug}.stop{n}.more{i}.aside", (r.get("aside") or {}).get("heading"))
        for i, w in enumerate(s.get("where_next") or [], 1):
            add(f"{slug}.next{i}.go", w.get("go"))
            add(f"{slug}.next{i}.line", w.get("line"))
    return out


# ── What it does (the molecule page's section 3, phase 8) ────────────────────
def compile_what_it_does(molecules: list[dict], comparisons_seed: dict[str, dict],
                         entries: dict[str, dict] | None = None) -> dict[str, dict]:
    """{slug: {sentences: [...], illustration}} from what_it_does.yaml, every sentence a pinned
    reference to a comparison paragraph. ``comparisons_seed`` is ``relationships.load_comparisons()``
    (keyed ``a/b``). Raises DoorError naming every problem."""
    entries = load_what_it_does() if entries is None else entries
    by_slug = {m["slug"]: m for m in molecules}
    texts = {k.replace("/", "-vs-"): v.get("text") for k, v in comparisons_seed.items()}
    problems, out = [], {}
    for slug, e in entries.items():
        if slug not in by_slug:
            problems.append(f"what_it_does {slug}: not a catalog molecule")
            continue
        sents = []
        for i, ref in enumerate(e.get("sentences") or [], 1):
            pair, starts = ref.get("pair"), ref.get("starts")
            if pair not in texts:
                problems.append(f"what_it_does {slug} sentence {i}: {pair!r} has no comparison")
                continue
            a, b = pair.split("-vs-", 1) if "-vs-" in pair else (None, None)
            hits = [s for s in sentences(texts[pair]) if starts and s.startswith(starts)]
            if len(hits) != 1:
                problems.append(f"what_it_does {slug} sentence {i}: no single sentence of {pair} starts {starts!r}")
                continue
            text = hits[0]
            if ref.get("pin") != pin(text):
                problems.append(f"what_it_does {slug} sentence {i}: the quoted sentence is new or changed "
                                f"(pin {ref.get('pin')!r}, text now {pin(text)}): {text!r}")
            if slug not in (a, b) and slug.lower() not in text.lower():
                problems.append(f"what_it_does {slug} sentence {i}: neither from {slug}'s own comparison nor naming it")
            for bad, rx in (("dash", DASH), ("advice", ADVICE)):
                if rx.search(text):
                    problems.append(f"what_it_does {slug} sentence {i}: {bad} in {text!r}")
            if "ld50" in text.lower():
                problems.append(f"what_it_does {slug} sentence {i}: an LD50 is not a mechanism: {text!r}")
            sents.append({"text": text, "pair": pair, "starts": starts, "href": f"/vs/{pair}"})
        if not sents:
            problems.append(f"what_it_does {slug}: no sentences")
        ill = e.get("illustration")
        if ill is not None and ill not in ILLUSTRATIONS:
            problems.append(f"what_it_does {slug}: illustration {ill!r} is not one of {ILLUSTRATIONS}")
        out[slug] = {"sentences": sents, "illustration": ill, "confidence": "from_source", "source": "curated"}
    if problems:
        raise DoorError("what_it_does.yaml does not compile:\n  " + "\n  ".join(problems))
    return out


def attach_what_it_does(molecules: list[dict], comparisons_seed: dict[str, dict]) -> int:
    """Stamp ``what_it_does`` on each record with an entry; a record with none carries no field."""
    compiled = compile_what_it_does(molecules, comparisons_seed)
    for m in molecules:
        m.pop("what_it_does", None)
        if m["slug"] in compiled:
            m["what_it_does"] = compiled[m["slug"]]
    return len(compiled)
