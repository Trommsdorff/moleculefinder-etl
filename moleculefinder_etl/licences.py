"""Licence records for every medicine, read from the regulators' own public data (growth plan run B2).

Run B's "Who licenses X as a medicine?" answer reads a molecule's ``approval`` record. Six medicines
had one, written by hand under a ruling (``sources/seeds/approvals.yaml``). This module gives every
prescription and OTC medicine a record from a regulator's own register, in this order:

1. **Drugs@FDA** (the FDA's downloadable data files; US government work, public domain): a product
   that is marketed today (status Prescription or Over-the-counter; Discontinued and tentative
   approvals do not count).
2. **The EMA's medicines data** (its public JSON of centrally authorised medicines): a human
   medicine whose status is Authorised. The marketing authorisation itself is a European Commission
   decision on the EMA's assessment, so the record names the Commission as the regulator.
3. **The MHRA products database** (products.mhra.gov.uk) where neither applies: a product listed
   there, read by hand from the site's public substance pages into ``licences_mhra.yaml``.

Never news, never Wikipedia. A medicine found in none of the three gets no record and is listed by
name in the run's report; nothing is guessed. The six hand-ruled records stay as they are and win
over anything here.

``mfetl licences`` downloads the registers, matches, and writes ``sources/seeds/licences.yaml``
(committed, like every curated seed), each record carrying its register, its source URL and the date
the register was read. ``mfetl all`` only READS that file (relationships.attach_licences), so the
weekly run and a pinned rebuild make no new upstream request; a refresh is a deliberate
``mfetl licences`` run whose diff is reviewed like any seed change.

Matching is by active ingredient, exactly: the ingredient is one of the molecule's names (title,
preferred name, Wikipedia title, Wikidata label and aliases), or that name followed only by salt,
ester or hydrate words ("SERTRALINE HYDROCHLORIDE", "TESTOSTERONE CYPIONATE"). A product made of a
single ingredient is preferred; a combination counts only when no single-ingredient product exists.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import re
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import DATA, SEEDS_DIR, SNAPSHOTS

log = logging.getLogger("mfetl.licences")

LICENCES_YAML = SEEDS_DIR / "licences.yaml"
CACHE_DIR = DATA / "regulators"          # gitignored; the downloaded registers, deleted after a run

MEDICINE_BUCKETS = ("prescription-medicine", "otc-medicine")

# ── The three registers ──────────────────────────────────────────────────────────────────────
FDA_ZIP_URL = "https://www.fda.gov/media/89850/download"
FDA_PAGE = "https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files"
FDA_OVERVIEW = "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={appl}"
EMA_JSON_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json"
EMA_PAGE = "https://www.ema.europa.eu/en/medicines/download-medicine-data"
MHRA_SUBSTANCE = "https://products.mhra.gov.uk/substance/?substance={name}"

FDA = "US Food and Drug Administration"
EC = "European Commission"
MHRA = "Medicines and Healthcare products Regulatory Agency"
REGISTER_FDA = "Drugs@FDA"
REGISTER_EMA = "European Medicines Agency"
REGISTER_MHRA = "MHRA Products"


# Words that may follow an ingredient name and still name the same active moiety: salts, esters,
# hydrates. "ESCITALOPRAM OXALATE" is not citalopram (the name must match from the first word).
SALT_WORDS = frozenset(["hydrochloride", "dihydrochloride", "trihydrochloride", "hcl", "hydrobromide", "hydroiodide", "sulfate", "sulphate", "bisulfate", "hemisulfate", "sodium", "disodium", "trisodium", "potassium", "dipotassium", "calcium", "magnesium", "zinc", "lithium", "aluminum", "aluminium", "ammonium", "meglumine", "tromethamine", "lysine", "arginine", "choline", "diethylamine", "olamine", "erbumine", "maleate", "dimaleate", "mesylate", "mesilate", "dimesylate", "besylate", "besilate", "tosylate", "tosilate", "napsylate", "napadisilate", "edisylate", "esylate", "isethionate", "tartrate", "bitartrate", "hemitartrate", "citrate", "dihydrogen", "hydrogen", "phosphate", "diphosphate", "fumarate", "hemifumarate", "succinate", "acetate", "diacetate", "oxalate", "hyclate", "propionate", "dipropionate", "valerate", "furoate", "butyrate", "bromide", "chloride", "iodide", "nitrate", "lactate", "gluconate", "glucoheptonate", "pamoate", "embonate", "palmitate", "decanoate", "enanthate", "cypionate", "undecanoate", "stearate", "benzoate", "salicylate", "carbonate", "bicarbonate", "hydroxide", "oxide", "xinafoate", "trifenatate", "pivalate", "acetonide", "sodium-succinate", "hemisuccinate", "etabonate", "aceponate", "medoxomil", "axetil", "cilexetil", "proxetil", "pivoxil", "mofetil", "hippurate", "mandelate", "subsalicylate", "monohydrate", "dihydrate", "trihydrate", "tetrahydrate", "pentahydrate", "sesquihydrate", "hemihydrate", "hydrate", "anhydrous", "micronized", "micronised", "hemipentahydrate", "polistirex", "resinate", "tannate", "saccharate", "monosodium", "dibasic", "monobasic", "sodium-phosphate", "hyclate", "monohydrochloride"])

_SPLIT_INGREDIENTS = re.compile(r"\s*(?:;|/|\+|,|\band\b)\s*", re.IGNORECASE)


def norm(name: str) -> str:
    """A name as compared: casefolded, hyphens and dashes as spaces, whitespace collapsed."""
    s = (name or "").casefold().replace("’", "'")
    s = re.sub(r"[‐-―-]", " ", s)
    s = re.sub(r"[^\w' ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def ingredient_matches(ingredient: str, names: set[str]) -> bool:
    """``ingredient`` (one active substance) is one of ``names`` (normalised), alone or followed
    only by salt/ester/hydrate words."""
    ing = norm(ingredient)
    if not ing:
        return False
    if ing in names:
        return True
    words = ing.split()
    for cut in range(len(words) - 1, 0, -1):
        if " ".join(words[:cut]) in names and all(w in SALT_WORDS for w in words[cut:]):
            return True
    return False


def split_ingredients(text: str) -> list[str]:
    return [p for p in (s.strip() for s in _SPLIT_INGREDIENTS.split(text or "")) if p]


# Release and form suffixes stay in capitals when a register's name is re-cased: "Effexor XR".
_KEEP_CAPS = frozenset(["xr", "er", "sr", "la", "xl", "cr", "dr", "ir", "es", "ec", "cd", "lr", "mr", "ds", "ac", "hb", "otc", "iv", "hfa", "odt", "tts", "pf", "rtu", "hct"])


def _title_case(s: str) -> str:
    """Registers spell product names in capitals ("ZOLOFT"); a sentence reads them as names."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    if s != s.upper():
        return s

    def word(m: re.Match) -> str:
        w = m.group(0)
        return w.upper() if w.casefold() in _KEEP_CAPS else w.capitalize()
    return re.sub(r"[A-Za-z][A-Za-z']*", word, s.lower())


@dataclass
class Candidate:
    register: str
    regulator: str
    application: str
    product: str | None
    authorised: str | None
    holder: str | None
    source: str
    basis: str
    single: bool                  # one active ingredient; False = the molecule is part of a combination
    rank: tuple = field(default_factory=tuple)


# ── Drugs@FDA ────────────────────────────────────────────────────────────────────────────────
def _read_tsv(zf: zipfile.ZipFile, member: str) -> list[dict]:
    raw = zf.read(member).decode("cp1252", errors="replace")
    return list(csv.DictReader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE))


def parse_fda(zip_path: Path) -> list[dict]:
    """One row per product marketed today: application, type, sponsor, drug name, ingredients,
    marketing status and the application's original approval date."""
    with zipfile.ZipFile(zip_path) as zf:
        apps = {r["ApplNo"]: r for r in _read_tsv(zf, "Applications.txt")}
        status_names = {r["MarketingStatusID"]: r["MarketingStatusDescription"].strip()
                        for r in _read_tsv(zf, "MarketingStatus_Lookup.txt")}
        status = {(r["ApplNo"], r["ProductNo"]): status_names.get(r["MarketingStatusID"], "")
                  for r in _read_tsv(zf, "MarketingStatus.txt")}
        orig: dict[str, str] = {}
        for r in _read_tsv(zf, "Submissions.txt"):
            if r["SubmissionType"] == "ORIG" and r["SubmissionStatus"] == "AP" and r["SubmissionStatusDate"]:
                d = r["SubmissionStatusDate"][:10]
                if r["ApplNo"] not in orig or d < orig[r["ApplNo"]]:
                    orig[r["ApplNo"]] = d
        out = []
        for r in _read_tsv(zf, "Products.txt"):
            st = status.get((r["ApplNo"], r["ProductNo"]), "")
            if st not in ("Prescription", "Over-the-counter"):
                continue
            app = apps.get(r["ApplNo"], {})
            out.append({
                "appl_no": r["ApplNo"], "appl_type": (app.get("ApplType") or "").strip(),
                "sponsor": (app.get("SponsorName") or "").strip(), "drug_name": r["DrugName"].strip(),
                "ingredients": split_ingredients(r["ActiveIngredient"]), "status": st,
                "form": r["Form"].strip(), "orig_date": orig.get(r["ApplNo"]),
            })
    return out


def fda_candidates(names: set[str], products: list[dict]) -> list[Candidate]:
    seen: dict[str, Candidate] = {}
    prior_name: dict[str, str] = {}
    for p in products:
        if not any(ingredient_matches(i, names) for i in p["ingredients"]):
            continue
        single = len(p["ingredients"]) == 1
        appl = f"{p['appl_type']} {p['appl_no']}".strip()
        prior = seen.get(appl)
        if prior and (prior.single and not single or prior.single == single
                      and len(prior_name[appl]) <= len(p["drug_name"])):
            continue                            # keep the application's plainest product name
        prior_name[appl] = p["drug_name"]
        product = _title_case(p["drug_name"])
        if any(ingredient_matches(w, names) for w in split_ingredients(product)):
            product = None                      # a generic sold under its own ingredient name
        seen[appl] = Candidate(
            register=REGISTER_FDA, regulator=FDA, application=appl, product=product,
            authorised=p["orig_date"], holder=_title_case(p["sponsor"]) or None,
            source=FDA_OVERVIEW.format(appl=p["appl_no"]),
            basis=f"Marketed today ({p['status'].lower()}) under {appl} in the Drugs@FDA data files.",
            single=single,
            # single ingredient first, then the original application (NDA/BLA before ANDA), then
            # the oldest approval, then the application number: deterministic.
            rank=(not single, p["appl_type"] == "ANDA", p["orig_date"] or "9999", p["appl_no"]),
        )
    return sorted(seen.values(), key=lambda c: c.rank)


# ── EMA ──────────────────────────────────────────────────────────────────────────────────────
def _ema_date(s: str) -> str | None:
    try:
        return dt.datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def parse_ema(json_path: Path) -> list[dict]:
    """Human medicines with a current central marketing authorisation."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))["data"]
    out = []
    for r in data:
        if r.get("category") != "Human" or r.get("medicine_status") != "Authorised":
            continue
        subs = split_ingredients(r.get("active_substance") or "")
        inn = split_ingredients(r.get("international_non_proprietary_name_common_name") or "")
        out.append({
            "name": (r.get("name_of_medicine") or "").strip(), "number": (r.get("ema_product_number") or "").strip(),
            "substances": subs, "inn": inn, "generic": r.get("generic") == "Yes",
            "biosimilar": r.get("biosimilar") == "Yes",
            "holder": (r.get("marketing_authorisation_developer_applicant_holder") or "").strip(),
            "authorised": _ema_date(r.get("marketing_authorisation_date") or ""),
            "url": (r.get("medicine_url") or "").strip(),
        })
    return out


def ema_candidates(names: set[str], medicines: list[dict]) -> list[Candidate]:
    out = []
    for m in medicines:
        lists = [m["substances"], m["inn"]]
        if not any(any(ingredient_matches(i, names) for i in lst) for lst in lists):
            continue
        single = max(len(m["substances"]), len(m["inn"])) == 1
        copy = m["generic"] or m["biosimilar"]
        out.append(Candidate(
            register=REGISTER_EMA, regulator=EC, application=m["number"], product=_title_case(m["name"]),
            authorised=m["authorised"], holder=m["holder"] or None, source=m["url"],
            basis=f"Centrally authorised medicine {m['number']}, status Authorised in the EMA's medicines data.",
            single=single,
            rank=(not single, copy, m["authorised"] or "9999", m["number"]),
        ))
    return sorted(out, key=lambda c: c.rank)


# ── MHRA ─────────────────────────────────────────────────────────────────────────────────────
# Read by hand from the site's public substance pages (licences_mhra.yaml says why): the API behind
# the site answered 503 to every request on 2026-10-21, and its fallback search needs a key.
LICENCES_MHRA_YAML = SEEDS_DIR / "licences_mhra.yaml"
_MHRA_FIELDS = {"substance", "product", "combination", "read"}


def load_mhra(path: Path = LICENCES_MHRA_YAML) -> dict[str, Candidate]:
    """{slug: Candidate} from the hand-checked MHRA file. Every entry needs the substance as the
    index spells it and the date read; an unknown field fails."""
    if not path.exists():
        return {}
    out: dict[str, Candidate] = {}
    problems: list[str] = []
    for slug, e in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items():
        e = e or {}
        if set(e) - _MHRA_FIELDS or not e.get("substance") or not e.get("read"):
            problems.append(f"{slug}: needs substance and read, and only {sorted(_MHRA_FIELDS)}")
            continue
        sub = str(e["substance"])
        out[str(slug)] = Candidate(
            register=REGISTER_MHRA, regulator=MHRA, application="", product=e.get("product") or None,
            authorised=None, holder=None,
            source=MHRA_SUBSTANCE.format(name=urllib.parse.quote(sub)),
            basis=f"Listed under {sub} in the MHRA products database (medicines with a UK marketing authorisation).",
            single=not e.get("combination"), rank=(str(e["read"]),))
    if problems:
        raise SystemExit(f"{path.name}: " + "; ".join(problems))
    return out


# ── Names and the medicines ──────────────────────────────────────────────────────────────────
def _primary_names(rec: dict) -> set[str]:
    """The names a record is filed under: title, preferred name, Wikipedia title."""
    return {k for k in (_name_key(n) for n in (rec.get("title"), rec.get("preferred_name"),
                                               rec.get("wikipedia_title"))) if k}


def _name_key(n: str | None) -> str:
    # "Estradiol (medication)" -> "estradiol"; only a TRAILING parenthesis is a note, a leading
    # one is part of the name ("(S)-citalopram" is escitalopram, not citalopram).
    k = norm(re.sub(r"\s*\([^()]*\)\s*$", "", n or ""))
    return k if len(k) >= 4 else ""                       # "THC"-sized names match too much


def medicine_names(rec: dict, canon_row: dict | None, others: set[str] = frozenset()) -> set[str]:
    """The names a register may list this molecule under. Wikidata's label and aliases add the
    other spellings (paracetamol, rifampin, meperidine), but an alias that sits INSIDE the title is
    the parent or the racemate ("citalopram" under escitalopram, "ofloxacin" under levofloxacin),
    and one that is another catalog molecule's own name ("omeprazole") belongs to that molecule:
    neither is used. ``others`` is every other catalog record's primary names."""
    own = _primary_names(rec)
    out = set(own)
    extra = [canon_row.get("wikidata_label"), *(canon_row.get("wikidata_aliases") or [])] if canon_row else []
    for n in extra:
        k = _name_key(n)
        if not k or k in out:
            continue
        if k in others or any(k in t and k != t for t in own):
            continue
        out.add(k)
    return out


def load_catalog(snapshots: Path = SNAPSHOTS) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((snapshots / "molecules").glob("*.json"))]


def medicines_of(catalog: list[dict]) -> list[dict]:
    return [r for r in catalog if r.get("scope_bucket") in MEDICINE_BUCKETS]


def _canon_rows() -> dict[int, dict]:
    import pyarrow.parquet as pq
    return {int(r["cid"]): r for r in pq.read_table(DATA / "seed" / "canon.parquet").to_pylist()}


def record_from(c: Candidate, read: str) -> dict:
    rec = {"regulator": c.regulator, "register": c.register}
    if c.application:
        rec["application"] = c.application
    if c.product:
        rec["product"] = c.product
    if c.authorised:
        rec["authorised"] = c.authorised
    if c.holder:
        rec["holder"] = c.holder
    if not c.single:
        rec["combination"] = True
    rec.update({"basis": c.basis, "source": c.source, "read": read})
    return rec


def build(medicines: list[dict], canon: dict[int, dict], fda: list[dict], ema: list[dict],
          mhra: dict[str, Candidate] | None = None, read: str | None = None, hand: set[str] = frozenset(),
          catalog: list[dict] | None = None) -> tuple[dict, list[str]]:
    """{slug: record} for every medicine found in a register, and the titles found in none.
    Hand-ruled slugs (approvals.yaml) are skipped: their records stay as they are. ``catalog`` is
    every record (default: the medicines), whose names no other molecule may be matched under."""
    read = read or dt.date.today().isoformat()
    records: dict[str, dict] = {}
    missing: list[str] = []
    catalog = catalog if catalog is not None else medicines
    primary = {r["slug"]: _primary_names(r) for r in catalog}
    for rec in sorted(medicines, key=lambda r: r["slug"]):
        if rec["slug"] in hand:
            continue
        others = set().union(*(v for k, v in primary.items() if k != rec["slug"])) - _primary_names(rec)
        names = medicine_names(rec, canon.get(int(rec["cid"])), others)
        cands = fda_candidates(names, fda) or ema_candidates(names, ema)
        if cands:
            records[rec["slug"]] = record_from(cands[0], read)
        elif (mhra or {}).get(rec["slug"]):
            c = mhra[rec["slug"]]
            records[rec["slug"]] = record_from(c, c.rank[0])      # the date that page was read
        else:
            missing.append(rec["title"])
    return records, missing


HEADER = """\
# Licence records for medicines, from the regulators' own public data (growth plan run B2, 2026-10-21).
# GENERATED by `mfetl licences` (moleculefinder_etl/licences.py); do not edit by hand. Hand rulings
# live in approvals.yaml and win over this file. Each record names its regulator, the register it
# was read from, the register's own page for the authorisation (source) and the date it was read.
#   Drugs@FDA data files (US government work, public domain): {fda}
#   EMA medicines data (reproduction authorised, source acknowledged): {ema}
#   MHRA products database (Open Government Licence v3.0): https://products.mhra.gov.uk/
# Medicines found in none of the three (no record, no licence answer):
{missing}
"""


def write_seed(records: dict, missing: list[str], path: Path = LICENCES_YAML) -> None:
    miss = "\n".join(f"#   {t}" for t in sorted(missing, key=str.casefold)) or "#   (none)"
    body = yaml.safe_dump(records, sort_keys=True, allow_unicode=True, width=1000)
    path.write_text(HEADER.format(fda=FDA_PAGE, ema=EMA_PAGE, missing=miss) + "\n" + body, encoding="utf-8")


def download(cache: Path = CACHE_DIR) -> tuple[Path, Path]:
    import requests
    cache.mkdir(parents=True, exist_ok=True)
    out = []
    for url, name in ((FDA_ZIP_URL, "drugsatfda.zip"), (EMA_JSON_URL, "ema-medicines.json")):
        # fda.gov answers 401 to some browser-like user agents and 200 to a plain client.
        r = requests.get(url, timeout=120, headers={"User-Agent": "curl/8.7.1"})
        r.raise_for_status()
        (cache / name).write_bytes(r.content)
        log.info("licences: read %s (%d bytes)", url, len(r.content))
        out.append(cache / name)
    return out[0], out[1]


def run() -> int:
    """`mfetl licences`: download the registers, match every medicine, write licences.yaml."""
    import shutil

    from .transform import relationships
    fda_zip, ema_json = download()
    try:
        fda, ema = parse_fda(fda_zip), parse_ema(ema_json)
    finally:
        shutil.rmtree(CACHE_DIR, ignore_errors=True)        # disk rule: no copy of a register kept
    hand = set(relationships.load_approvals())
    catalog = load_catalog()
    meds = medicines_of(catalog)
    mhra = load_mhra()
    unknown = sorted(set(mhra) - {m["slug"] for m in meds})
    if unknown:
        raise SystemExit(f"{LICENCES_MHRA_YAML.name}: not a medicine in the catalog: {unknown}")
    records, missing = build(meds, _canon_rows(), fda, ema, mhra, hand=hand, catalog=catalog)
    write_seed(records, missing)
    by: dict[str, int] = {}
    for r in records.values():
        by[r["register"]] = by.get(r["register"], 0) + 1
    log.info("licences: %d medicines, %d hand-ruled, %d records %s, %d in no register",
             len(meds), len(hand & {m["slug"] for m in meds}), len(records), by, len(missing))
    for t in missing:
        log.info("licences: no record: %s", t)
    return 0
