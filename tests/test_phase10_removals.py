"""Phase 10 (everyday chemistry plan): the dose, blood alcohol and still-in-the-system hooks stop, and the
Deadliest and Safest boards are no longer written. What used to read a hook reads the curated property."""
from __future__ import annotations

from moleculefinder_etl.transform import claims


def _nicotine(half_life):
    return {"slug": "nicotine", "hooks": [{"type": "structure", "params": {}}],
            "properties": [{"key": "half_life_hours", "value_num": half_life}]}


def test_the_nicotine_claim_reads_the_half_life_property():
    assert claims._nicotine({"nicotine": _nicotine(2.0)}, {}) is None
    assert "not about two hours" in claims._nicotine({"nicotine": _nicotine(6.0)}, {})
    assert "not about two hours" in claims._nicotine({"nicotine": {"slug": "nicotine", "properties": []}}, {})
