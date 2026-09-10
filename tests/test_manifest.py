import json
import sys
from pathlib import Path


def test_session_manifest_written(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from stress_cycle import (
        B1500Controller,
        ThorlabsPowerMeterController,
        StressMeasurementEngine,
        CycleConfig,
        SweepConfig,
        StressConfig,
    )

    # Disconnected controllers trigger safe simulation branches in engine.run().
    b1500 = B1500Controller()
    pm = ThorlabsPowerMeterController()

    cfg = CycleConfig(
        sweep=SweepConfig(start=0.0, stop=0.1, steps=3, dwell_s=0.0),
        stress=StressConfig(mode="voltage", value=0.1, duration_s=0.02, sample_interval_s=0.02),
        num_cycles=1,
        initial_measurement=False,
        output_folder=str(tmp_path),
        device_name="TST",
        device_id="TST",
        autosave=True,
    )

    engine = StressMeasurementEngine(b1500, pm, cfg)
    engine.run()

    sessions = list(Path(tmp_path).glob("TST_stress_test_*/session_manifest.json"))
    assert sessions, "session_manifest.json was not generated"

    data = json.loads(sessions[0].read_text(encoding="utf-8"))
    assert data["protocol_name"] == "stress_cycle"
    assert data["schema_version"] == "series-v1"
