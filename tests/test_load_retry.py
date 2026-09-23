"""The load sends a child-row DELETE again when the gateway drops it, three attempts in all (2026-09-14).

The weekly run of 2026-09-14 (34838019124) failed in stage 3 on one request of about 1,100: the
synonym DELETE for molecule 3 came back `504 {"message":"Gateway Timeout"}` from the proxy in front of
PostgREST, and neither the loader nor the client retried it (postgrest's own retry covers a GET
answered 503 or 520, nothing else). These replay that answer through the real postgrest client, so
the error the retry sees is the one the run saw.
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest
from postgrest import SyncPostgrestClient
from postgrest.exceptions import APIError

from moleculefinder_etl.load import supabase_loader

CAFFEINE = {"cid": 2519, "slug": "caffeine", "title": "Caffeine", "synonyms": ["caffeine", "guaranine"]}


def _gateway_timeout(request):          # the 2026-09-14 answer, verbatim
    return httpx.Response(504, json={"message": "Gateway Timeout"})


def _dropped(request):                  # the connection fails before any status arrives
    raise httpx.ReadTimeout("timed out", request=request)


def _foreign_key_violation(request):    # PostgREST's own error: the database did answer
    return httpx.Response(409, json={"code": "23503", "message": "violates foreign key constraint",
                                     "details": None, "hint": None})


def _ok(request):
    return httpx.Response(200, json=[])


def _client(handler) -> SyncPostgrestClient:
    """The real PostgREST client, answered by `handler` instead of the network."""
    return SyncPostgrestClient("https://project.supabase.co/rest/v1",
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _delete_answered(*answers):
    """Molecule 3's synonym DELETE, whose attempts get `answers` in turn."""
    sent: list[httpx.Request] = []

    def handler(request):
        sent.append(request)
        return answers[len(sent) - 1](request)

    return _client(handler).table("synonym").delete().eq("molecule_id", 3), sent


def _database(*, deletes, insert=None):
    """Enough of PostgREST for `load_all`: reads find no rows, upserts echo their rows back with ids,
    and the synonym DELETEs and INSERT get the answers given."""
    sent: list[tuple[str, str]] = []
    deletes = iter(deletes)

    def handler(request):
        sent.append((request.method, request.url.path))
        if request.method == "DELETE":
            return next(deletes)(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        if insert is not None and request.url.path.endswith("/synonym"):
            return insert(request)
        rows = json.loads(request.content)
        return httpx.Response(201, json=[{**r, "id": i + 1} for i, r in enumerate(rows)])

    return _client(handler), sent


@pytest.fixture
def waits(monkeypatch):
    """The pauses between attempts, recorded instead of slept."""
    waited: list[float] = []
    monkeypatch.setattr(supabase_loader._execute_idempotent.retry, "sleep", waited.append)
    return waited


def test_a_gateway_timeout_is_sent_again_and_logged(waits, caplog):
    query, sent = _delete_answered(_gateway_timeout, _gateway_timeout, _ok)
    with caplog.at_level(logging.WARNING, logger="mfetl"):
        supabase_loader._execute_idempotent(query)
    assert [(r.method, r.url.path, r.url.params["molecule_id"]) for r in sent] == \
        [("DELETE", "/rest/v1/synonym", "eq.3")] * 3
    assert waits == [5, 10]
    assert [r.getMessage() for r in caplog.records if "retrying" in r.getMessage()][0].startswith(
        "  supabase: attempt 1 of 3 failed")
    assert sum("retrying" in r.getMessage() for r in caplog.records) == 2


def test_the_third_timeout_fails_the_run_with_the_gateways_own_error(waits):
    query, sent = _delete_answered(_gateway_timeout, _gateway_timeout, _gateway_timeout)
    with pytest.raises(APIError) as err:
        supabase_loader._execute_idempotent(query)
    assert str(err.value.code) == "504" and "Gateway Timeout" in err.value.details
    assert len(sent) == 3 and waits == [5, 10]


def test_a_database_error_is_not_sent_again(waits):
    query, sent = _delete_answered(_foreign_key_violation)
    with pytest.raises(APIError, match="23503"):
        supabase_loader._execute_idempotent(query)
    assert len(sent) == 1 and waits == []


def test_a_dropped_connection_is_sent_again(waits):
    query, sent = _delete_answered(_dropped, _ok)
    supabase_loader._execute_idempotent(query)
    assert len(sent) == 2 and waits == [5]


def test_the_load_sends_the_timed_out_delete_again_and_the_insert_once(waits):
    client, sent = _database(deletes=[_gateway_timeout, _ok])
    counts = supabase_loader.load_all(client, [CAFFEINE])
    assert counts["synonym"] == 2
    assert sent.count(("DELETE", "/rest/v1/synonym")) == 2
    assert sent.count(("POST", "/rest/v1/synonym")) == 1
    assert waits == [5]


def test_a_timed_out_insert_is_not_sent_again(waits):
    """A gateway timeout does not say whether the rows landed; a second INSERT could store them twice."""
    client, sent = _database(deletes=[_ok], insert=_gateway_timeout)
    with pytest.raises(APIError):
        supabase_loader.load_all(client, [CAFFEINE])
    assert sent.count(("POST", "/rest/v1/synonym")) == 1
    assert waits == []
