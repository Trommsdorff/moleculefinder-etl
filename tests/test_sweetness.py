"""Every sweetness the site shows has a named source (SEO run 1, 2026-10-28).

The Sweetest board said sucralose leads at 600 times sugar because only eight molecules carried
a value, while lugduname's own line said 200,000. Values now live in one seed,
sources/seeds/sweetness.yaml, each with a source the registry allows to be displayed and the
source's own words; the board ranks them, and every entry names its source. A molecule's
why-it-matters line that quotes a multiple must agree with the value it sits beside.
"""
from __future__ import annotations

import json
import re

import pytest
import yaml

from moleculefinder_etl.config import CURATED_DIR, SNAPSHOTS
from moleculefinder_etl.sources import registry
from moleculefinder_etl.transform import leaderboards
from moleculefinder_etl.transform import relationships as rel


def _rec(slug, **over):
    return {"slug": slug, "properties": [], "hooks": [{"type": "structure"}, {"type": "similar"}],
            "curated": {}, **over}


def _seed(monkeypatch, data):
    monkeypatch.setattr(rel, "load_sweetness", lambda: data)


_HSDB = {"value": 0.6, "source": "hsdb", "cite": "HSDB, Taste", "says": "approx 60% as sweet as sugar"}


def test_a_value_lands_with_its_source_property_and_hook(monkeypatch):
    _seed(monkeypatch, {"sorbitol": _HSDB})
    rec = _rec("sorbitol")
    rel.attach_sweetness([rec])
    assert rec["relative_sweetness"] == 0.6 and rec["relative_sweetness_source"] == "hsdb"
    assert rec["properties"] == [{"key": "relative_sweetness", "value_num": 0.6, "value_text": None,
                                  "unit": "x sugar", "confidence": "from_source", "source": "hsdb"}]
    assert [h["type"] for h in rec["hooks"]] == ["sweetness", "structure", "similar"]
    assert rec["hooks"][0]["params"] == {"x_sugar": 0.6}
    assert rec["curated"]["relative_sweetness"] == 0.6


@pytest.mark.parametrize("data, expected", [
    ({"nosuch": _HSDB}, "unknown slug"),
    ({"sorbitol": {**_HSDB, "source": "t3db"}}, "may be displayed"),
    ({"sorbitol": {**_HSDB, "source": "nosuchsource"}}, "may be displayed"),
    ({"sorbitol": {**_HSDB, "value": 0}}, "positive number"),
    ({"sorbitol": {**_HSDB, "value": "0.6"}}, "positive number"),
    ({"sorbitol": {k: v for k, v in _HSDB.items() if k != "says"}}, "missing ['says']"),
    ({"sorbitol": {**_HSDB, "note": "x"}}, "unknown field(s) ['note']"),
    ({"sucrose": {**_HSDB, "value": 1.1}}, "reference point"),
])
def test_the_seed_is_fenced(monkeypatch, data, expected):
    _seed(monkeypatch, data)
    with pytest.raises(SystemExit, match=re.escape(expected)):
        rel.attach_sweetness([_rec("sorbitol"), _rec("sucrose")])


def test_no_overlay_carries_a_sweetness_any_more():
    """One home per value: a figure in an overlay would be a second, uncited one."""
    carrying = [p.name for p in sorted(CURATED_DIR.glob("*.yaml"))
                if "relative_sweetness" in (yaml.safe_load(p.read_text()) or {})]
    assert carrying == []


def test_every_seed_entry_names_a_displayable_source_in_its_own_words():
    data = rel.load_sweetness()
    assert len(data) >= 20
    for slug, e in data.items():
        assert registry.may_display(e["source"]), slug
        assert e["cite"].strip() and e["says"].strip(), slug


def test_the_board_ranks_the_highest_value_first_and_names_every_source():
    mols = [{"cid": i, "slug": s, "title": s.title(), "relative_sweetness": v, "relative_sweetness_source": "hsdb"}
            for i, (s, v) in enumerate([("a", 1), ("b", 230000), ("c", 0.6)])]
    board = leaderboards.rank("sweetest", mols)
    assert [e["slug"] for e in board["entries"]] == ["b", "a", "c"]
    assert all(e["source"] == "hsdb" for e in board["entries"])


# ── the committed snapshot ───────────────────────────────────────────────────
_BOARD = SNAPSHOTS / "leaderboards" / "sweetest.json"


@pytest.mark.skipif(not _BOARD.exists(), reason="no snapshot exported yet")
def test_the_committed_board_carries_a_source_on_every_entry_and_leads_with_the_highest():
    board = json.loads(_BOARD.read_text())
    entries = board["entries"]
    assert len(entries) >= 20
    assert all(registry.may_display(e.get("source")) for e in entries), \
        [e["slug"] for e in entries if not registry.may_display(e.get("source"))]
    assert entries[0]["value_num"] == max(e["value_num"] for e in entries)
    seed = rel.load_sweetness()
    assert {e["slug"] for e in entries} == set(seed)
    assert board["description"].startswith(f"{entries[0]['title']} is the sweetest")


# "around 250 times sweeter", "about 70 percent as sweet", "roughly 200,000 times sweeter".
_MULTIPLE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(times|percent)\s+(?:as\s+)?sweet", re.IGNORECASE)


@pytest.mark.skipif(not _BOARD.exists(), reason="no snapshot exported yet")
def test_a_line_that_quotes_a_multiple_agrees_with_the_value_beside_it():
    """The sourced value wins: a why-it-matters line or editorial that quotes a sweetness must say
    the number the page shows (a percent as its fraction)."""
    bad = []
    for slug in rel.load_sweetness():
        m = json.loads((SNAPSHOTS / "molecules" / f"{slug}.json").read_text())
        texts = [(m.get("why_it_matters") or {}).get("text") or ""]
        texts += [b.get("body_md") or "" for b in m.get("content_blocks") or [] if b.get("block_type") == "editorial"]
        for t in texts:
            for num, unit in ((float(n.replace(",", "")), u.lower()) for n, u, *_ in _MULTIPLE.findall(t)):
                quoted = num / 100 if unit == "percent" else num
                if abs(quoted - m["relative_sweetness"]) > 1e-9:
                    bad.append(f"{slug}: says {num:g} {unit}, the value is {m['relative_sweetness']}")
    assert bad == []
