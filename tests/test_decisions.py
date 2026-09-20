from src.services.apis.decisions import apply_threshold


def test_apply_threshold_bands():
    assert apply_threshold(0.90) == "auto"
    assert apply_threshold(0.70) == "review"
    assert apply_threshold(0.50) == "fallback"
