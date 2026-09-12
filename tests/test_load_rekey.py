"""The load re-keys a molecule whose slug the catalog moved to a new CID (2026-09-12).

Iodine's catalog row was corrected from CID 24841 (hydrogen iodide) to CID 807 (I2). The load
upserts `molecule` on `cid` and `slug` is unique, so the corrected record collided with the row
that still held `iodine`, the load failed, and the weekly loop stopped until a person re-keyed the
row by hand. These pin that the load now does it: before the upsert, and only when it is safe.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from moleculefinder_etl.load import supabase_loader


class _Query:
    """Just enough of the PostgREST builder for the re-key and the first upsert."""

    def __init__(self, client, table):
        self.client, self.table, self.op, self.values, self.filters, self.window = client, table, "select", None, [], None

    def select(self, _columns):
        return self

    def order(self, _column):
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def update(self, values):
        self.op, self.values = "update", values
        return self

    def upsert(self, rows, on_conflict=None):
        self.op, self.values = "upsert", rows
        return self

    def execute(self):
        rows = self.client.rows.setdefault(self.table, [])
        if self.op == "upsert":
            self.client.log.append(("upsert", self.table))
            return SimpleNamespace(data=[{**r, "id": i + 1} for i, r in enumerate(self.values)])
        hit = [r for r in rows if all(r[c] == v for c, v in self.filters)]
        if self.op == "update":
            self.client.log.append(("update", self.table, dict(self.values), list(self.filters)))
            for r in hit:
                r.update(self.values)
            return SimpleNamespace(data=[dict(r) for r in hit])
        if self.window:
            hit = hit[self.window[0]:self.window[1] + 1]
        return SimpleNamespace(data=[dict(r) for r in hit])


class _Client:
    def __init__(self, molecules):
        self.rows = {"molecule": [dict(r) for r in molecules]}
        self.log: list = []

    def table(self, name):
        return _Query(self, name)


def test_a_slug_moved_to_a_new_cid_is_rekeyed_in_place():
    client = _Client([{"id": 1, "cid": 2519, "slug": "caffeine"}, {"id": 809, "cid": 24841, "slug": "iodine"}])
    moves = supabase_loader.rekey_moved_slugs(client, [{"cid": 2519, "slug": "caffeine"}, {"cid": 807, "slug": "iodine"}])
    assert moves == [{"id": 809, "slug": "iodine", "from": 24841, "to": 807}]
    assert client.log == [("update", "molecule", {"cid": 807}, [("id", 809), ("cid", 24841)])]
    assert {r["id"]: r["cid"] for r in client.rows["molecule"]} == {1: 2519, 809: 807}


def test_nothing_is_rekeyed_when_every_slug_keeps_its_cid():
    client = _Client([{"id": 1, "cid": 2519, "slug": "caffeine"}])
    assert supabase_loader.rekey_moved_slugs(client, [{"cid": 2519, "slug": "caffeine"},
                                                      {"cid": 5429, "slug": "theobromine"}]) == []
    assert client.log == []


def test_a_new_cid_another_row_already_holds_fails_loudly():
    client = _Client([{"id": 809, "cid": 24841, "slug": "iodine"}, {"id": 900, "cid": 807, "slug": "diiodine"}])
    with pytest.raises(RuntimeError, match="already belongs to molecule id 900"):
        supabase_loader.rekey_moved_slugs(client, [{"cid": 807, "slug": "iodine"}])
    assert client.log == []


def test_existing_rows_are_read_a_page_at_a_time():
    client = _Client([{"id": i, "cid": i, "slug": f"m{i}"} for i in range(1, 2501)])
    assert len(supabase_loader._molecule_keys(client, page=1000)) == 2500


def test_the_load_rekeys_before_it_upserts_the_molecules(monkeypatch):
    client = _Client([])

    class _Stop(Exception):
        pass

    def rekey(c, rows):
        c.log.append("rekey")
        raise _Stop

    monkeypatch.setattr(supabase_loader, "rekey_moved_slugs", rekey)
    with pytest.raises(_Stop):
        supabase_loader.load_all(client, [])
    assert client.log == [("upsert", "source"), "rekey"]
