"""Molecules in the news (moleculefinder_etl/news.py, .github/workflows/news.yml).

A live-news test cannot be re-run, so the matcher is pinned by a fixture of synthetic headlines,
each stating what it must match; the job is then run end to end against that fixture with the
network switched off. The rest pins what leaves the job: names, dates and counts, never coverage.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
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
    assert set(feed) == {"generated_at", "window_days", "ranked_by", "molecules"} and feed["window_days"] == 7
    assert feed["ranked_by"] == "count"
    assert [m["slug"] for m in feed["molecules"]] == ["caffeine", "melatonin"]    # aged out; not in the catalogue
    assert feed["molecules"][0] == {"slug": "caffeine", "name": "Caffeine", "first_seen": "2026-10-14",
                                    "last_seen": "2026-10-20", "hits": 9}
    assert all(set(m) == FEED_KEYS for m in feed["molecules"])


# ── the order: a spike outranks a steady high count ──────────────────────────
AUDIT_FIELDS = ("headline", "outlet", "url", "query", "story")


def _matches(slug, per_week, weeks_ago, tag=""):
    """``per_week`` distinct headlines naming ``slug`` in the week ``weeks_ago`` weeks back (0 =
    this week), spread over that week."""
    start = NOW - timedelta(days=7 * (weeks_ago + 1))
    return [{"slug": slug, "story": f"https://news.example/{slug}/{weeks_ago}/{i}{tag}",
             "headline": f"Synthetic {slug} headline {weeks_ago}/{i}", "outlet": "Example News",
             "url": f"https://news.example/{slug}/{weeks_ago}/{i}{tag}?oc=5", "query": slug,
             "published_at": start + timedelta(hours=1 + i * (166 / max(per_week, 1)))}
            for i in range(per_week)]


# A fixed five weeks: fentanyl steady at ~150 a week; acetaminophen at 5 a week, then a recall week
# of 40; melatonin new this week with 3 and no history at all.
HISTORY = [*(m for w in range(1, 5) for m in _matches("fentanyl", 150, w)), *_matches("fentanyl", 152, 0),
           *(m for w in range(1, 5) for m in _matches("acetaminophen", 5, w)), *_matches("acetaminophen", 40, 0),
           *_matches("melatonin", 3, 0)]


def _feed_from(history, spike):
    found = news.tally(history, INDEX["names"], NOW)
    rows, _ = news.plan_write(found, [], NOW)
    return news.build_feed(rows, SLUGS, NOW, spike)


def test_a_recall_sized_spike_outranks_a_steady_high_count():
    spike = news.spikes(HISTORY, NOW)
    assert spike["acetaminophen"] == 40 / 5 and round(spike["fentanyl"], 2) == round(152 / 150, 2)
    assert spike["melatonin"] == 3 / news.SPIKE_FLOOR                     # no history: the floor, not a zero
    feed = _feed_from(HISTORY, spike)
    assert feed["ranked_by"] == "spike"
    assert [m["slug"] for m in feed["molecules"]] == ["acetaminophen", "melatonin", "fentanyl"]
    # The counts the badge shows are this week's, whatever the order.
    assert {m["slug"]: m["hits"] for m in feed["molecules"]} == {"acetaminophen": 40, "melatonin": 3, "fentanyl": 152}


def test_without_four_weeks_of_history_the_order_is_the_raw_count():
    assert news.has_history(None, NOW) is False
    assert news.has_history(NOW - timedelta(days=27), NOW) is False
    assert news.has_history(NOW - timedelta(days=28), NOW) is True
    feed = _feed_from(HISTORY, None)
    assert feed["ranked_by"] == "count"
    assert [m["slug"] for m in feed["molecules"]] == ["fentanyl", "acetaminophen", "melatonin"]


def test_a_headline_found_by_two_runs_counts_once():
    twice = HISTORY + _matches("acetaminophen", 40, 0)                    # the same 40 stories again
    assert news.spikes(twice, NOW)["acetaminophen"] == 40 / 5
    assert {m["slug"]: m["hits"] for m in news.tally(twice, INDEX["names"], NOW)}["acetaminophen"] == 40


# ── the audit trail is private ───────────────────────────────────────────────
def test_the_audit_trail_goes_to_the_private_table_and_nowhere_else(monkeypatch, capsys):
    """write() against a fake PostgREST and Storage: the headline, outlet, link and query reach
    molecule_news_match and nothing else: not molecule_news, not the public JSON, not the log."""
    sent = []
    oldest = (NOW - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fake(method, url, key, body=None, headers=None, quiet=False):
        sent.append((method, url, body, quiet))
        if method == "GET" and "select=found_at" in url:
            return json.dumps([{"found_at": oldest}]).encode()
        if method == "GET" and news.MATCH_TABLE in url:
            if "offset=0" not in url:
                return b"[]"
            return json.dumps([{"slug": r["slug"], "story": r["story"], "published_at": news.iso(r["published_at"])}
                               for r in HISTORY]).encode()
        return b"[]"
    monkeypatch.setattr(news, "_request", fake)
    this_run = [r for r in HISTORY if r["published_at"] >= NOW - timedelta(days=7)][:50]
    entrants, feed = news.write(this_run, INDEX["names"], SLUGS, "https://example.invalid", "k", NOW)
    log = capsys.readouterr().out

    to_matches = [s for s in sent if s[0] == "POST" and f"/{news.MATCH_TABLE}?" in s[1]]
    assert len(to_matches) == 1 and to_matches[0][3] is True                # quiet: errors withhold the body
    assert all(set(AUDIT_FIELDS[:4]) <= set(r) for r in to_matches[0][2])
    assert all(quiet for m, url, _, quiet in sent if news.MATCH_TABLE in url)
    public_rows = next(s[2] for s in sent if s[0] == "POST" and f"/{news.TABLE}?" in s[1])
    assert all(set(r) == {"slug", "name", "first_seen", "last_seen", "hits", "updated_at"} for r in public_rows)
    upload = next(s[2] for s in sent if "/storage/v1/object/" in s[1])
    public = json.loads(upload)
    assert public == feed and public["ranked_by"] == "spike"
    assert all(set(m) == FEED_KEYS for m in public["molecules"])
    text = upload.decode() + json.dumps(public_rows) + log      # everything public, and the log
    for field in AUDIT_FIELDS:
        assert f'"{field}"' not in upload.decode() and f'"{field}"' not in json.dumps(public_rows)
    for r in this_run:
        assert r["headline"] not in text and r["url"] not in text and "Example News" not in text
    assert {m["slug"] for m in entrants} == {"acetaminophen", "fentanyl", "melatonin"}     # none listed before


def test_an_error_from_the_private_table_never_echoes_a_row(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, __import__("io").BytesIO(
            b'{"message":"Failing row contains (caffeine, Synthetic caffeine headline, Example News)"}'))
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        news._request("POST", "https://example.invalid/rest/v1/molecule_news_match?on_conflict=slug,story",
                      "k", [{}], quiet=True)
    assert "Synthetic" not in str(exc.value) and "HTTP 400" in str(exc.value)


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
