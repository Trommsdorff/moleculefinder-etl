import pytest
from moleculefinder_etl.transform.confidence import label_for, FROM_SOURCE, COMPUTED, INFERRED


def test_labels():
    assert label_for("formula") == FROM_SOURCE
    assert label_for("decay") == COMPUTED
    assert label_for("rodent_to_human") == INFERRED


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        label_for("nonsense")
