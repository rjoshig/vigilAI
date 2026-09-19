"""Package smoke test — keeps the suite green before Phase 2 lands real modules."""

import greenlight_ai


def test_version_is_set() -> None:
    assert greenlight_ai.__version__
