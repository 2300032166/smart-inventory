import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.routes import advisor


def make_candidate(sku, urgency, days_remaining, confidence):
    return (
        {"sku": sku, "name": f"Product {sku}"},
        {},
        {"urgency": urgency, "days_remaining": days_remaining, "confidence_score": confidence},
        {},
        0,
        0,
    )


def test_select_ai_candidates_prioritizes_urgent_and_limits_batch_size():
    candidates = [
        make_candidate("SKU1", "normal", 10, 0.75),
        make_candidate("SKU2", "urgent", 3, 0.95),
        make_candidate("SKU3", "normal", 2, 0.80),
        make_candidate("SKU4", "urgent", 1, 0.90),
    ]

    selected = advisor._select_ai_candidates(candidates, {"max_ai_items": 3})

    assert len(selected) == 3
    assert selected[0][0]["sku"] == "SKU4"
    assert selected[1][0]["sku"] == "SKU2"
    assert selected[2][0]["sku"] == "SKU3"
