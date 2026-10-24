"""The FDA's UNII table (trust run 3, 2026-10-24): sources/fda_unii.py.

Pinned here: the parser reads the records member by name and the four columns by header, keeps
the compact row shape, drops a malformed UNII or a non-integer PubChem id without dropping the
row, and refuses an edition that lacks a column or the records file; the Table indexes by code,
CID and InChIKey; the cache is a dated envelope the fetch stage warms once; the source is
registered public domain and displayable; and PubChem's code reader keeps bare codes.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

import pytest

from moleculefinder_etl.sources import cache, fda_unii, pubchem, registry

HEADER = ["UNII", "DISPLAY_NAME", "RN", "EC", "NCIT", "RXCUI", "PUBCHEM", "SMSID", "EPA_CompTox",
          "CATALOGUE_OF_LIFE", "ITIS", "NCBI", "PLANTS", "POWO", "GRIN", "MPNS", "INN_ID", "USAN_ID",
          "DAILYMED", "MF", "INCHIKEY", "SMILES", "INGREDIENT_TYPE", "UTF8_DISPLAY_NAME", "SUBSTANCE_TYPE"]


def _row(unii, name, pubchem="", inchikey="", mf="", kind="chemical"):
    cells = {"UNII": unii, "DISPLAY_NAME": name, "PUBCHEM": pubchem, "INCHIKEY": inchikey, "MF": mf,
             "INGREDIENT_TYPE": "INGREDIENT SUBSTANCE", "SUBSTANCE_TYPE": kind}
    return "\t".join(cells.get(h, "") for h in HEADER)


def _zip(rows, header=HEADER, member="UNII_Records_4Aug2026.txt", extra=("READ ME UNII Lists.txt",)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if member:
            z.writestr(member, "﻿" + "\t".join(header) + "\r\n" + "\r\n".join(rows) + "\r\n")
        for name in extra:
            z.writestr(name, "The enclosed lists are in tab-delimited text format.\n")
    return buf.getvalue()


ROWS = [_row("3G6A5W338E", "CAFFEINE", "2519", "RYYVLZVUVIJVGH-UHFFFAOYSA-N", "C8H10N4O2"),
        _row("OYN3CCI6QE", "TIRZEPATIDE", kind="protein"),
        _row("4VON5FNS3C", "SODIUM METABISULFITE", "656671", "HRZFUMHJMZEROT-UHFFFAOYSA-L"),
        _row("0129526470", "A TEN-DIGIT UNII", "12", "AAAAAAAAAAAAAA-BBBBBBBBBB-N"),
        _row("BADCODE", "NOT A UNII", "1"),
        _row("Q9J4K2N7L1", "A CAS NUMBER IN THE PUBCHEM COLUMN", "3057514-75-4", "not-an-inchikey", kind=""),
        _row("9G5L16BK6N", "CORN SYRUP", "5282499", kind="structurallyDiverse")]


def test_parse_reads_the_five_columns_by_name_and_keeps_the_compact_row_shape():
    data = fda_unii.parse(_zip(ROWS))
    assert data["file"] == "UNII_Records_4Aug2026.txt"
    assert data["rows"] == [
        ["3G6A5W338E", "CAFFEINE", 2519, "RYYVLZVUVIJVGH-UHFFFAOYSA-N", "chemical"],
        ["OYN3CCI6QE", "TIRZEPATIDE", None, None, "protein"],
        ["4VON5FNS3C", "SODIUM METABISULFITE", 656671, "HRZFUMHJMZEROT-UHFFFAOYSA-L", "chemical"],
        ["0129526470", "A TEN-DIGIT UNII", 12, "AAAAAAAAAAAAAA-BBBBBBBBBB-N", "chemical"],
        ["Q9J4K2N7L1", "A CAS NUMBER IN THE PUBCHEM COLUMN", None, None, ""],   # kept, the two fields dropped
        ["9G5L16BK6N", "CORN SYRUP", 5282499, None, "structurallyDiverse"],
    ]                                                                        # BADCODE skipped
    assert json.loads(json.dumps(data)) == data                              # plain JSON for the cache


def test_parse_reads_the_columns_wherever_the_header_puts_them():
    header = ["INCHIKEY", "UNII", "SUBSTANCE_TYPE", "PUBCHEM", "DISPLAY_NAME"]
    rows = ["RYYVLZVUVIJVGH-UHFFFAOYSA-N\t3G6A5W338E\tchemical\t2519\tCAFFEINE"]
    assert fda_unii.parse(_zip(rows, header))["rows"] == [["3G6A5W338E", "CAFFEINE", 2519, "RYYVLZVUVIJVGH-UHFFFAOYSA-N", "chemical"]]


def test_parse_refuses_a_renamed_column_or_a_zip_without_the_records_file():
    header = [h if h != "PUBCHEM" else "PUBCHEM_CID" for h in HEADER]
    with pytest.raises(fda_unii.FdaUniiFormatError, match="PUBCHEM"):
        fda_unii.parse(_zip(ROWS, header))
    with pytest.raises(fda_unii.FdaUniiFormatError, match="UNII_Records"):
        fda_unii.parse(_zip(ROWS, member=None))
    with pytest.raises(fda_unii.FdaUniiFormatError, match="UNII_Records"):
        fda_unii.parse(_zip(ROWS, extra=("READ ME UNII Lists.txt", "sub/UNII_Records_1Jan2020.txt")))


def test_table_indexes_by_code_cid_and_inchikey_and_knows_a_source_defined_substance():
    t = fda_unii.Table(fda_unii.parse(_zip(ROWS)))
    assert len(t) == 6 and "3G6A5W338E" in t and "BADCODE" not in t
    assert t.cid("3G6A5W338E") == 2519 and t.inchikey("3G6A5W338E") == "RYYVLZVUVIJVGH-UHFFFAOYSA-N"
    assert t.name("OYN3CCI6QE") == "TIRZEPATIDE" and t.cid("OYN3CCI6QE") is None
    assert t.by_cid[656671] == ["4VON5FNS3C"]
    assert t.by_inchikey["HRZFUMHJMZEROT-UHFFFAOYSA-L"] == ["4VON5FNS3C"]
    assert t.row("nope") is None and t.cid(None) is None and t.name("") is None
    # Corn syrup is defined by its source; the FDA's PubChem CID for it is a reference, not an identity.
    assert t.row("9G5L16BK6N").kind == "structurallyDiverse" and not t.defined_by_structure("9G5L16BK6N")
    assert t.defined_by_structure("3G6A5W338E") and t.defined_by_structure("OYN3CCI6QE")
    assert t.defined_by_structure("Q9J4K2N7L1") and t.defined_by_structure("not-in-the-table")


def test_warm_fetches_once_into_a_dated_envelope_and_then_reads_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fda_unii, "CACHE_PATH", tmp_path / "fda" / "unii-records-v1.json")
    calls = []

    def fetch():
        calls.append(1)
        return _zip(ROWS)
    t = fda_unii.warm(fetch)
    assert len(t) == 6 and calls == [1]
    raw = json.loads(fda_unii.CACHE_PATH.read_text())
    assert raw[cache.ENVELOPE_KEY] == cache.ENVELOPE_VERSION and raw["fetched_at"]
    assert raw["value"]["file"] == "UNII_Records_4Aug2026.txt"
    t2 = fda_unii.warm(lambda: pytest.fail("fetched again"))
    assert t2.file == t.file and calls == [1]
    assert fda_unii.cached().cid("3G6A5W338E") == 2519
    # Expired: a miss (the weekly refresh re-reads it); a pinned build never expires it.
    assert fda_unii.cached(max_age_days=0) is None
    monkeypatch.setenv("MFETL_INPUTS", "pinned")
    assert fda_unii.cached(max_age_days=0) is not None


def test_the_source_is_registered_public_domain_and_displayable():
    assert registry.licence_class("fda_unii") == "public_domain"
    assert registry.may_display("fda_unii")
    assert registry.SOURCES["fda_unii"]["license_url"].startswith("https://www.fda.gov/")
    assert registry.SHORT_NAMES["fda_unii"] == "FDA UNII"
    registry.assert_not_blocked(fda_unii.SOURCE_KEY)


def test_pubchem_keeps_bare_and_prefixed_codes_and_split_tells_them_apart():
    pattern = pubchem._UNII
    assert pattern.match("UNII-3G6A5W338E") and pattern.match("OYN3CCI6QE") and pattern.match("0129526470")
    assert not pattern.match("UNII-SHORT") and not pattern.match("3g6a5w338e") and not pattern.match("Caffeine")
    assert pubchem.split_unii("UNII-3G6A5W338E") == ("3G6A5W338E", False)
    assert pubchem.split_unii("OYN3CCI6QE") == ("OYN3CCI6QE", True)
    assert re.fullmatch(r"https://pubchem\.ncbi\.nlm\.nih\.gov/rest/pug", pubchem.PUBCHEM_REST)
