import pytest
from moleculefinder_etl.transform.confidence import label_for, FROM_SOURCE, COMPUTED


def test_labels():
    assert label_for("formula") == FROM_SOURCE
    assert label_for("scoville") == COMPUTED
    assert label_for("functional_group") == COMPUTED


def test_the_removed_calculators_have_no_rule():
    """Phase 10: the decay, scaled dose, blood alcohol and rodent-to-human rules went with their hooks."""
    for kind in ("decay", "scaled_dose", "bac", "rodent_to_human"):
        with pytest.raises(KeyError):
            label_for(kind)


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        label_for("nonsense")
