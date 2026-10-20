"""Molecules in the news (moleculefinder_etl/news.py, .github/workflows/news.yml).

A live-news test cannot be re-run, so the matcher is pinned by a fixture of synthetic headlines,
each stating what it must match; the job is then run end to end against that fixture with the
network switched off. The rest pins what leaves the job: names, dates and counts, never coverage.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from moleculefinder_etl import news

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "news-headlines.txt"
WORKFLOW = REPO / ".github" / "workflows" / "news.yml"
MOLECULES = news.load_molecules()
INDEX = news.build_index(MOLECULES)
SLUGS = {m["slug"] for m in MOLECULES}
CASES = news.parse_fixture(FIXTURE.read_text())
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
FEED_KEYS = {"slug", "name", "first_seen", "last_seen", "hits"}


# ── the matcher, against the fixture ─────────────────────────────────────────
def test_the_fixture_has_forty_shapes_each_with_an_expectation():
    assert len(CASES) >= 40, len(CASES)
    assert [h for h, exp in CASES if exp is None] == []
    assert sum(1 for _, exp in CASES if exp == []) >= 15        # plenty that must match nothing


def test_every_slug_the_fixture_expects_is_in_the_catalogue():
    assert sorted({s for _, exp in CASES for s in exp or []} - SLUGS) == []


@pytest.mark.parametrize("headline, expected", CASES, ids=[h[:60] for h, _ in CASES])
def test_fixture_headline(headline, expected):
    assert news.match_headline(news.strip_source(headline), INDEX) == sorted(expected)


def test_common_words_never_match_on_their_own():
    for word in ("iron", "lead", "salt", "water", "gold", "silver", "mercury", "chrome", "carbon"):
        assert word not in INDEX["terms"], word
        assert news.match_headline(f"{word.title()} is everywhere this week", INDEX) == [], word


def test_raw_pubchem_synonyms_are_never_names():
    """Lead's PubChem list carries "Glover", monosodium glutamate's "Accent"; aspartame's brand
    "Equal" is an everyday word. None of them may match."""
    for word in ("glover", "accent", "equal", "artist", "celeste", "nocturne", "epa", "msg"):
        assert word not in INDEX["terms"], word


def test_every_curated_name_points_at_a_real_molecule():
    """A renamed slug must fail here, not silently stop matching."""
    assert sorted(set(news.ALIASES) - SLUGS) == []
    assert sorted(set(news.CONTEXT) - SLUGS) == []
    for key in news.QUALIFIED:
        assert key in SLUGS or any(news.normalize(m["title"]) == key for m in MOLECULES), key


# ── what leaves the job: names only ──────────────────────────────────────────
def _found(slug, hits, first, last):
    return {"slug": slug, "name": INDEX["names"][slug], "hits": hits, "first_seen": first,
            "last_seen": last, "headlines": ["a headline that must never be written"]}


def test_a_row_keeps_its_first_seen_and_only_entrants_are_pinged():
    found = [_found("caffeine", 3, NOW - timedelta(days=2), NOW), _found("melatonin", 1, NOW, NOW)]
    existing = [{"slug": "caffeine", "first_seen": "2026-10-10T00:00:00Z", "last_seen": "2026-10-19T00:00:00Z"}]
    rows, entrants = news.plan_write(found, existing, NOW)
    by = {r["slug"]: r for r in rows}
    assert by["caffeine"]["first_seen"] == "2026-10-10T00:00:00Z"
    assert by["caffeine"]["last_seen"] == "2026-10-20T12:00:00Z" and by["caffeine"]["hits"] == 3
    assert [m["slug"] for m in entrants] == ["melatonin"]                 # caffeine was already listed
    for r in rows:
        assert set(r) == {"slug", "name", "first_seen", "last_seen", "hits", "updated_at"}


def test_a_molecule_back_after_a_week_away_is_an_entrant_again():
    existing = [{"slug": "caffeine", "first_seen": "2026-09-01T00:00:00Z", "last_seen": "2026-10-01T00:00:00Z"}]
    _, entrants = news.plan_write([_found("caffeine", 1, NOW, NOW)], existing, NOW)
    assert [m["slug"] for m in entrants] == ["caffeine"]


def test_the_feed_carries_names_dates_and_counts_and_nothing_else():
    rows = [
        {"slug": "caffeine", "name": "Caffeine", "first_seen": "2026-10-14T03:00:00Z", "last_seen": "2026-10-20T01:00:00Z", "hits": 9},
        {"slug": "melatonin", "name": "Melatonin", "first_seen": "2026-10-19T00:00:00Z", "last_seen": "2026-10-19T00:00:00Z", "hits": 9},
        {"slug": "aspartame", "name": "Aspartame", "first_seen": "2026-10-01T00:00:00Z", "last_seen": "2026-10-10T00:00:00Z", "hits": 40},
        {"slug": "carfentanil", "name": "Carfentanil", "first_seen": "2026-10-19T00:00:00Z", "last_seen": "2026-10-19T00:00:00Z", "hits": 5},
    ]
    feed = news.build_feed(rows, SLUGS, NOW)
    assert set(feed) == {"generated_at", "window_days", "molecules"} and feed["window_days"] == 7
    assert [m["slug"] for m in feed["molecules"]] == ["caffeine", "melatonin"]    # aged out; not in the catalogue
    assert feed["molecules"][0] == {"slug": "caffeine", "name": "Caffeine", "first_seen": "2026-10-14",
                                    "last_seen": "2026-10-20", "hits": 9}
    assert all(set(m) == FEED_KEYS for m in feed["molecules"])


# ── the fetch ────────────────────────────────────────────────────────────────
def test_a_full_batch_is_split_until_the_busy_name_stands_alone():
    asked = []

    def get(url):
        q = urllib.parse.unquote(url.split("q=")[1].split("&")[0]).rsplit(" when:", 1)[0]
        asked.append(q)
        busy = "fentanyl" in q.split(" OR ")
        return [{"title": f"{q} {i}", "link": f"{q}/{i}", "source": "", "pubDate": ""}
                for i in range(100 if busy else 3)]

    _, failed, made = news.fetch(["fentanyl OR caffeine OR melatonin OR aspartame"], 7, pause=0, get=get)
    assert failed == 0 and "caffeine OR melatonin" in " | ".join(asked)
    assert "fentanyl" in asked                           # isolated, and a lone full name is not split
    assert not any(q.startswith("fentanyl OR") and q != "fentanyl OR caffeine" for q in asked[1:])
    _, _, made = news.fetch(["a OR b OR c OR d OR fentanyl"] * 10, 7, pause=0, budget=5, get=get)
    assert made == 5                                     # the budget holds


def test_the_four_runs_start_from_different_batches():
    qs = [f"q{i}" for i in range(8)]
    starts = {news.rotate(qs, slot)[0] for slot in range(4)}
    assert starts == {"q0", "q2", "q4", "q6"} and sorted(news.rotate(qs, 3)) == sorted(qs)


# ── the job, end to end, on fixed headlines ──────────────────────────────────
def test_the_job_runs_against_the_fixture_offline_and_writes_nothing(monkeypatch, capsys):
    def no_network(*a, **k):
        raise AssertionError("the fixture run touched the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-key")       # set, and still nothing written
    assert news.main(["--fixture", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    feed = json.loads(out[out.index("{\n"):out.rindex("}") + 1])
    expected = {s for _, exp in CASES for s in exp or []}
    assert {m["slug"] for m in feed["molecules"]} == expected
    assert all(set(m) == FEED_KEYS for m in feed["molecules"])
    # No coverage leaves the job: not a headline, not an outlet.
    printed = json.dumps(feed)
    assert "Example News" not in printed and "Caffeine Weekly" not in printed
    for headline, _ in CASES:
        assert news.strip_source(headline) not in out
    assert "nothing written, nothing submitted" in out


def test_headlines_are_never_printed_on_github(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(SystemExit, match="local audit only"):
        news.main(["--fixture", str(FIXTURE), "--show-headlines"])


def test_the_job_needs_nothing_but_the_standard_library():
    """The cron runs it on the runner's bare Python, with no install."""
    heavy = "{'requests','yaml','rdkit','dotenv','supabase','pyarrow','tenacity'}"
    code = (f"import sys; sys.path.insert(0, {str(REPO)!r}); import moleculefinder_etl.news; "
            f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {heavy}))")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


# ── the workflow ─────────────────────────────────────────────────────────────
def test_the_cron_is_six_hourly_installs_nothing_and_never_prints_headlines():
    wf = yaml.safe_load(WORKFLOW.read_text())
    on = wf[True] if True in wf else wf["on"]
    assert on["schedule"] == [{"cron": "50 */6 * * *"}] and "workflow_dispatch" in on
    steps = wf["jobs"]["news"]["steps"]
    runs = " ".join(s.get("run", "") for s in steps)
    assert "python3 -m moleculefinder_etl.news" in runs
    assert "pip install" not in runs and "--show-headlines" not in runs
    assert "git push" not in runs and "git commit" not in runs              # it publishes no data
    assert wf["jobs"]["alarm"]["if"] == "failure()" and wf["concurrency"]["cancel-in-progress"] is False
    assert wf["permissions"] == {"contents": "read"}


def test_the_weekly_loop_does_not_know_the_news_job_exists():
    etl = (REPO / ".github" / "workflows" / "etl.yml").read_text()
    assert "news" not in etl.replace("newsletter", "")
