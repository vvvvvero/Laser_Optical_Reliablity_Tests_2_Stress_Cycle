"""QThread workers for stress cycle execution and resource refresh."""

from typing import Callable, List

from PyQt5.QtCore import QThread, pyqtSignal

from .measurement_engine import StressMeasurementEngine
class TestWorker(QThread):
    """Worker thread for running the stress-measurement test"""
    measurement_point = pyqtSignal(object)
    stress_point = pyqtSignal(object)
    phase_change = pyqtSignal(object)
    cycle_complete = pyqtSignal(int)
    progress = pyqtSignal(int, int)
    log_message = pyqtSignal(str)
    finished_signal = pyqtSignal()
    
    def __init__(self, engine: StressMeasurementEngine):
        super().__init__()
        self.engine = engine
        self.engine.on_measurement_point = lambda p: self.measurement_point.emit(p)
        self.engine.on_stress_point = lambda p: self.stress_point.emit(p)
        self.engine.on_phase_change = lambda p: self.phase_change.emit(p)
        self.engine.on_cycle_complete = lambda c: self.cycle_complete.emit(c)
        self.engine.on_progress = lambda c, t: self.progress.emit(c, t)
        self.engine.on_log = lambda m: self.log_message.emit(m)
    
    def run(self):
        self.engine.run()
        self.finished_signal.emit()


class ResourceRefreshWorker(QThread):
    """Worker thread for enumerating VISA resources without blocking the GUI."""
    resources_ready = pyqtSignal(object)
    refresh_failed = pyqtSignal(str)

    def __init__(self, fetch_resources: Callable[[], List[str]]):
        super().__init__()
        self.fetch_resources = fetch_resources

    def run(self):
        try:
            resources = self.fetch_resources()
            self.resources_ready.emit(resources)
        except Exception as exc:
            self.refresh_failed.emit(str(exc))



