"""Basic programmatic usage for stress cycle measurements."""

from stress_cycle import (
    B1500Controller,
    ThorlabsPowerMeterController,
    StressMeasurementEngine,
    CycleConfig,
    SweepConfig,
    StressConfig,
)


b1500 = B1500Controller()
pm = ThorlabsPowerMeterController()

cfg = CycleConfig(
    sweep=SweepConfig(smu=1, mode="iv", start=0.0, stop=2.0, steps=21),
    stress=StressConfig(mode="voltage", value=2.0, duration_s=60.0, sample_interval_s=1.0),
    num_cycles=10,
    device_name="Device_001",
)

engine = StressMeasurementEngine(b1500, pm, cfg)
engine.on_log = print

# Connect instruments before running.
# b1500.connect("GPIB0::16::INSTR")
# pm.connect("USB0::0x1313::0x8078::...")
# measurement_data, stress_data = engine.run()
