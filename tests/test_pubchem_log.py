"""The fetch stage's PubChem POSTs leave a line each in the log (2026-09-23).

The Sep 21 cold run fetched every synonym list and property row from PubChem, green, and its
log could not say what PubChem's throttle read or whether any POST had been sent twice. Each
batched POST now logs its X-Throttling-Control header, and every retry logs a warning, so the next
cold run answers both from the log. Driven through the real retry decorator with real
`requests.Response` objects; only the network and the back-off sleep are replaced.
"""
from __future__ import annotations

import json
import logging

import pytest
import requests

from moleculefinder_etl.config import PUBCHEM_BATCH
from moleculefinder_etl.sources import pubchem

GREEN = ("Request Count status: Green (0%), Request Time status: Green (0%), "
         "Service status: Green (20%)")


def _response(status: int, payload: dict | None = None, throttle: str | None = GREEN) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/synonyms/JSON"
    r._content = json.dumps(payload or {}).encode()
    if throttle is not None:
        r.headers["X-Throttling-Control"] = throttle
    return r


def _synonyms_payload(cids):
    return {"InformationList": {"Information": [{"CID": c, "Synonym": [f"name-{c}"]} for c in cids]}}


def _properties_payload(cids):
    return {"PropertyTable": {"Properties": [{"CID": c} for c in cids]}}


@pytest.fixture
def posts(monkeypatch):
    """Replace the network with a queue of responses; record every POST's CID list."""
    sent: list[list[int]] = []
    queue: list = []

    def fake_post(url, data, headers, timeout):
        cids = [int(c) for c in data.removeprefix("cid=").split(",")]
        sent.append(cids)
        make = queue.pop(0)
        return make(cids)

    monkeypatch.setattr(pubchem._session, "post", fake_post)
    monkeypatch.setattr(pubchem, "_throttle", lambda: None)
    for fn in (pubchem.synonyms, pubchem.properties):
        monkeypatch.setattr(fn.retry, "sleep", lambda seconds: None)
    return sent, queue


def _post_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("pubchem POST")]


def test_each_post_logs_the_throttle_header_once(posts, caplog):
    sent, queue = posts
    queue.append(lambda cids: _response(200, _synonyms_payload(cids)))
    with caplog.at_level(logging.INFO, logger="mfetl.pubchem"):
        out = pubchem.synonyms([2244, 2519, 5429])
    assert out == {2244: ["name-2244"], 2519: ["name-2519"], 5429: ["name-5429"]}
    lines = _post_lines(caplog)
    assert len(lines) == 1 == len(sent)
    assert lines[0].startswith("pubchem POST synonyms: 3 CIDs from 2244, HTTP 200 in ")
    assert lines[0].endswith(f"X-Throttling-Control: {GREEN}")


def test_a_multi_batch_fetch_logs_one_line_per_post(posts, caplog):
    sent, queue = posts
    cids = list(range(1, PUBCHEM_BATCH + 21))                 # two POSTs: 150, then 20
    queue.extend([lambda c: _response(200, _properties_payload(c))] * 2)
    with caplog.at_level(logging.INFO, logger="mfetl.pubchem"):
        assert len(pubchem.properties(cids)) == len(cids)
    lines = _post_lines(caplog)
    assert [len(s) for s in sent] == [PUBCHEM_BATCH, 20]
    assert [line.split(": ", 1)[1].split(",")[0] for line in lines] == \
        [f"{PUBCHEM_BATCH} CIDs from 1", f"20 CIDs from {PUBCHEM_BATCH + 1}"]


def test_a_retried_post_shows_twice_with_the_retry_between(posts, caplog):
    """A 503 then a 200: two POST lines for the same batch and a warning naming the retry."""
    sent, queue = posts
    queue.append(lambda c: _response(503, throttle="Request Count status: Yellow (60%)"))
    queue.append(lambda c: _response(200, _synonyms_payload(c)))
    with caplog.at_level(logging.INFO, logger="mfetl.pubchem"):
        pubchem.synonyms([2519])
    lines = _post_lines(caplog)
    assert len(lines) == 2 == len(sent)
    assert "HTTP 503" in lines[0] and lines[0].endswith("Request Count status: Yellow (60%)")
    assert "HTTP 200" in lines[1]
    retries = [r for r in caplog.records if r.levelno == logging.WARNING and "Retrying" in r.getMessage()]
    assert len(retries) == 1 and "synonyms" in retries[0].getMessage()


def test_an_absent_header_is_said_to_be_absent(posts, caplog):
    sent, queue = posts
    queue.append(lambda c: _response(200, _synonyms_payload(c), throttle=None))
    with caplog.at_level(logging.INFO, logger="mfetl.pubchem"):
        pubchem.synonyms([2519])
    assert _post_lines(caplog)[0].endswith("X-Throttling-Control: (absent)")


def test_a_404_batch_is_logged_before_it_is_skipped(posts, caplog):
    sent, queue = posts
    queue.append(lambda c: _response(404))
    with caplog.at_level(logging.INFO, logger="mfetl.pubchem"):
        assert pubchem.synonyms([999999999]) == {}
    assert "HTTP 404" in _post_lines(caplog)[0]
