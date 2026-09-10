import sys
from pathlib import Path


def test_package_import():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    import stress_cycle  # noqa: F401

    assert hasattr(stress_cycle, "StressMeasurementEngine")
    assert hasattr(stress_cycle, "StressMeasurementCycleGUI")
