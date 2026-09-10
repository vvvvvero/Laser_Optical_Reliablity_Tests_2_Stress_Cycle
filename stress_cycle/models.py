"""Data models and enums for stress cycle measurements."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List
class TestPhase(Enum):
    IDLE = "idle"
    MEASUREMENT = "measurement"
    STRESS = "stress"
    COMPLETED = "completed"
    STOPPED = "stopped"


@dataclass
class SweepConfig:
    """Configuration for IV/VI sweep measurement"""
    smu: int = 1
    mode: str = "iv"  # "iv" or "vi"
    start: float = 0.0
    stop: float = 2.0
    steps: int = 21
    dwell_s: float = 0.1
    compliance: float = 0.1
    
    @property
    def setpoints(self) -> List[float]:
        if self.steps < 2:
            return [self.start]
        return [
            self.start + i * (self.stop - self.start) / (self.steps - 1)
            for i in range(self.steps)
        ]


@dataclass
class StressConfig:
    """Configuration for stress phase"""
    mode: str = "voltage"  # "voltage" or "current"
    value: float = 2.0     # Stress voltage (V) or current (A)
    duration_s: float = 60.0  # Stress duration in seconds
    sample_interval_s: float = 1.0  # Sampling interval during stress
    compliance: float = 0.1  # Compliance limit


@dataclass
class CycleConfig:
    """Configuration for the entire stress-measurement cycle test"""
    # Sweep settings
    sweep: SweepConfig = field(default_factory=SweepConfig)
    
    # Stress settings
    stress: StressConfig = field(default_factory=StressConfig)
    
    # Cycle settings
    num_cycles: int = 10  # Number of stress-measurement cycles
    initial_measurement: bool = True  # Do initial measurement before first stress
    
    # Power meter settings
    enable_power_meter: bool = True
    power_wavelength_nm: float = 850.0
    
    # Output settings
    output_folder: str = "results"
    device_name: str = "Device_001"
    autosave: bool = True


@dataclass
class MeasurementPoint:
    """Single IV measurement point"""
    cycle: int
    point_index: int
    timestamp: float
    setpoint: float
    voltage: float
    current: float
    optical_power: float
    status: str = "OK"


@dataclass
class StressPoint:
    """Single stress monitoring point"""
    cycle: int
    timestamp: float
    elapsed_s: float
    voltage: float
    current: float
    optical_power: float
    status: str = "OK"


@dataclass
class CycleSummary:
    """Summary of a measurement cycle"""
    cycle: int
    timestamp: str
    peak_current: float
    peak_power: float
    threshold_voltage: float  # Estimated from IV
    series_resistance: float  # Estimated from IV slope



