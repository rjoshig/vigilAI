"""Package smoke test — keeps the suite green before Phase 2 lands real modules."""

import vigilai


def test_version_is_set() -> None:
    assert vigilai.__version__
