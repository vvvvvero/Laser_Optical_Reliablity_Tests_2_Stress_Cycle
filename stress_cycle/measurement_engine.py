"""Core stress-measurement cycling engine."""

import csv
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np

from .models import CycleConfig, CycleSummary, MeasurementPoint, StressPoint, TestPhase
class StressMeasurementEngine:
    """Engine for running stress-measurement cycling tests"""
    
    def __init__(self, b1500: B1500Controller, power_meter: ThorlabsPowerMeterController,
                 config: CycleConfig):
        self.b1500 = b1500
        self.power_meter = power_meter
        self.config = config
        
        # Data storage
        self.measurement_data: List[MeasurementPoint] = []
        self.stress_data: List[StressPoint] = []
        self.cycle_summaries: List[CycleSummary] = []
        
        # State
        self.running = False
        self.stop_requested = False
        self.current_phase = TestPhase.IDLE
        self.current_cycle = 0
        
        # Callbacks
        self.on_measurement_point = None
        self.on_stress_point = None
        self.on_phase_change = None
        self.on_cycle_complete = None
        self.on_progress = None
        self.on_log = None
        
        # Output paths
        self.session_folder: Optional[Path] = None
    
    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg = f"[{timestamp}] {message}"
        print(msg)
        if self.on_log:
            self.on_log(msg)
    
    def set_phase(self, phase: TestPhase):
        self.current_phase = phase
        if self.on_phase_change:
            self.on_phase_change(phase)
    
    def run(self) -> Tuple[List[MeasurementPoint], List[StressPoint]]:
        """Run the complete stress-measurement cycle test"""
        self.running = True
        self.stop_requested = False
        self.measurement_data = []
        self.stress_data = []
        self.cycle_summaries = []
        
        # Create session folder
        self._create_session_folder()
        
        # Configure power meter
        if self.power_meter.connected and self.config.enable_power_meter:
            self.power_meter.configure(wavelength_nm=self.config.power_wavelength_nm)
            self.log(f"Power meter configured: Î»={self.config.power_wavelength_nm}nm")
        
        # Configure B1500
        if self.b1500.connected:
            try:
                self.b1500.configure_for_sweep(
                    self.config.sweep.smu,
                    self.config.sweep.mode,
                    self.config.sweep.compliance
                )
                self.log("B1500 configured")
            except Exception as e:
                self.log(f"B1500 configuration error: {e}")
                self.running = False
                return self.measurement_data, self.stress_data
        
        total_cycles = self.config.num_cycles
        self.log(f"Starting stress-measurement cycling test: {total_cycles} cycles")
        self.log(f"Stress: {self.config.stress.value}{'V' if self.config.stress.mode == 'voltage' else 'A'} "
                f"for {self.config.stress.duration_s}s")
        
        try:
            # Initial measurement (cycle 0)
            if self.config.initial_measurement:
                self.current_cycle = 0
                self._run_measurement_phase()
                if self.stop_requested:
                    return self.measurement_data, self.stress_data
            
            # Main cycling loop
            for cycle in range(1, total_cycles + 1):
                if self.stop_requested:
                    self.log("Test stopped by user")
                    break
                
                self.current_cycle = cycle
                self.log(f"\n{'='*50}")
                self.log(f"CYCLE {cycle}/{total_cycles}")
                self.log(f"{'='*50}")
                
                # Stress phase
                self._run_stress_phase()
                if self.stop_requested:
                    break
                
                # Measurement phase
                self._run_measurement_phase()
                
                # Progress callback
                if self.on_progress:
                    self.on_progress(cycle, total_cycles)
                
                # Cycle complete callback
                if self.on_cycle_complete:
                    self.on_cycle_complete(cycle)
            
            # Turn off output
            if self.b1500.connected:
                self.b1500.output_off(self.config.sweep.smu)
            
            # Save final summary
            self._save_summary()
            
            self.set_phase(TestPhase.COMPLETED if not self.stop_requested else TestPhase.STOPPED)
            self.log(f"\nTest complete. {len(self.measurement_data)} measurement points, "
                    f"{len(self.stress_data)} stress points recorded.")
            
        except Exception as e:
            self.log(f"Test error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False
        
        return self.measurement_data, self.stress_data
    
    def _run_measurement_phase(self):
        """Run IV + power measurement sweep"""
        self.set_phase(TestPhase.MEASUREMENT)
        self.log(f"Starting measurement phase (Cycle {self.current_cycle})")
        
        cfg = self.config.sweep
        setpoints = cfg.setpoints
        cycle_data = []
        
        for idx, setpoint in enumerate(setpoints):
            if self.stop_requested:
                break
            
            timestamp = time.time()
            
            # IV measurement
            if self.b1500.connected:
                voltage, current = self.b1500.set_bias_and_measure(
                    cfg.smu, setpoint, cfg.mode, cfg.compliance, cfg.dwell_s
                )
            else:
                voltage = setpoint if cfg.mode == "iv" else 0.0
                current = 0.0 if cfg.mode == "iv" else setpoint
            
            # Optical power
            if self.power_meter.connected and self.config.enable_power_meter:
                power, status = self.power_meter.measure_power()
            else:
                power = 0.0
                status = "No power meter"
            
            point = MeasurementPoint(
                cycle=self.current_cycle,
                point_index=idx,
                timestamp=timestamp,
                setpoint=setpoint,
                voltage=voltage,
                current=current,
                optical_power=power,
                status=status
            )
            
            self.measurement_data.append(point)
            cycle_data.append(point)
            
            if self.on_measurement_point:
                self.on_measurement_point(point)
        
        # Save measurement data for this cycle
        self._save_measurement_cycle(cycle_data)
        
        # Calculate cycle summary
        if cycle_data:
            summary = self._calculate_summary(cycle_data)
            self.cycle_summaries.append(summary)
        
        self.log(f"Measurement phase complete: {len(cycle_data)} points")
    
    def _run_stress_phase(self):
        """Run stress phase with monitoring"""
        self.set_phase(TestPhase.STRESS)
        
        cfg = self.config.stress
        self.log(f"Starting stress phase: {cfg.value}{'V' if cfg.mode == 'voltage' else 'A'} "
                f"for {cfg.duration_s}s")
        
        start_time = time.time()
        end_time = start_time + cfg.duration_s
        cycle_stress_data = []
        
        # Configure B1500 for stress
        if self.b1500.connected:
            try:
                smu = self.config.sweep.smu
                with self.b1500.lock:
                    if cfg.mode == "voltage":
                        self.b1500.inst.write(f"DV {smu},0,{cfg.value},{cfg.compliance}")
                    else:
                        self.b1500.inst.write(f"DI {smu},0,{cfg.value},{cfg.compliance}")
            except Exception as e:
                self.log(f"Stress setup error: {e}")
                return
        
        sample_count = 0
        while time.time() < end_time and not self.stop_requested:
            timestamp = time.time()
            elapsed = timestamp - start_time
            
            # Monitor current/voltage
            if self.b1500.connected:
                voltage, current = self.b1500.set_bias_and_measure(
                    self.config.sweep.smu, cfg.value, cfg.mode, 
                    cfg.compliance, dwell_s=0.01
                )
            else:
                voltage = cfg.value if cfg.mode == "voltage" else 0.0
                current = 0.0 if cfg.mode == "voltage" else cfg.value
            
            # Monitor optical power
            if self.power_meter.connected and self.config.enable_power_meter:
                power, status = self.power_meter.measure_power()
            else:
                power = 0.0
                status = "No power meter"
            
            point = StressPoint(
                cycle=self.current_cycle,
                timestamp=timestamp,
                elapsed_s=elapsed,
                voltage=voltage,
                current=current,
                optical_power=power,
                status=status
            )
            
            self.stress_data.append(point)
            cycle_stress_data.append(point)
            sample_count += 1
            
            if self.on_stress_point:
                self.on_stress_point(point)
            
            # Log every 10 seconds
            if sample_count % max(1, int(10 / cfg.sample_interval_s)) == 0:
                self.log(f"  Stress: {elapsed:.1f}s, I={current:.4e}A, P={power:.4e}W")
            
            # Wait for next sample
            next_sample_time = start_time + sample_count * cfg.sample_interval_s
            sleep_time = next_sample_time - time.time()
            if sleep_time > 0:
                time.sleep(min(sleep_time, 0.5))  # Check stop every 0.5s max
        
        # Save stress data for this cycle
        self._save_stress_cycle(cycle_stress_data)
        
        self.log(f"Stress phase complete: {len(cycle_stress_data)} samples, "
                f"duration: {time.time() - start_time:.1f}s")
    
    def _calculate_summary(self, data: List[MeasurementPoint]) -> CycleSummary:
        """Calculate summary parameters from measurement data"""
        voltages = [p.voltage for p in data]
        currents = [p.current for p in data]
        powers = [p.optical_power for p in data]
        
        peak_current = max(currents) if currents else 0.0
        peak_power = max(powers) if powers else 0.0
        
        # Estimate threshold voltage (where current > 1ÂµA)
        threshold_v = 0.0
        for v, i in zip(voltages, currents):
            if abs(i) > 1e-6:
                threshold_v = v
                break
        
        # Estimate series resistance from slope in high-current region
        series_r = 0.0
        if len(voltages) > 5:
            try:
                # Use last 30% of data for linear fit
                n_fit = max(3, len(voltages) // 3)
                v_fit = np.array(voltages[-n_fit:])
                i_fit = np.array(currents[-n_fit:])
                if np.std(i_fit) > 0:
                    slope, _ = np.polyfit(i_fit, v_fit, 1)
                    series_r = abs(slope)
            except:
                pass
        
        return CycleSummary(
            cycle=self.current_cycle,
            timestamp=datetime.now().isoformat(),
            peak_current=peak_current,
            peak_power=peak_power,
            threshold_voltage=threshold_v,
            series_resistance=series_r
        )
    
    def _create_session_folder(self):
        """Create session folder for output files"""
        base_path = Path(self.config.output_folder)
        if not base_path.is_absolute():
            base_path = Path(__file__).parent / self.config.output_folder
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_folder = base_path / f"{self.config.device_name}_stress_test_{timestamp}"
        self.session_folder.mkdir(parents=True, exist_ok=True)
        self.log(f"Session folder: {self.session_folder}")
    
    def _save_measurement_cycle(self, data: List[MeasurementPoint]):
        """Save measurement data for a cycle"""
        if not data or not self.config.autosave or not self.session_folder:
            return
        
        filename = f"measurement_cycle_{self.current_cycle:03d}.csv"
        filepath = self.session_folder / filename
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Point", "Timestamp", "Setpoint", "Voltage_V", 
                "Current_A", "Optical_Power_W", "Status"
            ])
            for p in data:
                writer.writerow([
                    p.point_index,
                    datetime.fromtimestamp(p.timestamp).isoformat(),
                    f"{p.setpoint:.6e}",
                    f"{p.voltage:.6e}",
                    f"{p.current:.6e}",
                    f"{p.optical_power:.6e}",
                    p.status
                ])
    
    def _save_stress_cycle(self, data: List[StressPoint]):
        """Save stress data for a cycle"""
        if not data or not self.config.autosave or not self.session_folder:
            return
        
        filename = f"stress_cycle_{self.current_cycle:03d}.csv"
        filepath = self.session_folder / filename
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Elapsed_s", "Voltage_V", 
                "Current_A", "Optical_Power_W", "Status"
            ])
            for p in data:
                writer.writerow([
                    datetime.fromtimestamp(p.timestamp).isoformat(),
                    f"{p.elapsed_s:.3f}",
                    f"{p.voltage:.6e}",
                    f"{p.current:.6e}",
                    f"{p.optical_power:.6e}",
                    p.status
                ])
    
    def _save_summary(self):
        """Save cycle summaries"""
        if not self.cycle_summaries or not self.session_folder:
            return
        
        filepath = self.session_folder / "cycle_summary.csv"
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Cycle", "Timestamp", "Peak_Current_A", "Peak_Power_W",
                "Threshold_V", "Series_Resistance_Ohm"
            ])
            for s in self.cycle_summaries:
                writer.writerow([
                    s.cycle, s.timestamp, f"{s.peak_current:.6e}",
                    f"{s.peak_power:.6e}", f"{s.threshold_voltage:.4f}",
                    f"{s.series_resistance:.4f}"
                ])
        
        self.log(f"Summary saved to: {filepath}")
    
    def stop(self):
        """Request stop of test"""
        self.stop_requested = True



