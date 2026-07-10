import pytest
from moleculefinder_etl.sources.registry import assert_not_blocked, BlockedSourceError, source_rows


def test_blocked_sources_raise():
    for bad in ("foodb", "drugbank", "chembl"):
        with pytest.raises(BlockedSourceError):
            assert_not_blocked(bad)


def test_clean_sources_ok():
    assert_not_blocked("pubchem")
    assert_not_blocked("wikidata")


def test_source_rows_have_keys():
    rows = source_rows()
    assert all("key" in r and "license" in r for r in rows)
