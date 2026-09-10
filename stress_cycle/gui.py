"""PyQt5 GUI for stress cycle measurements."""

import time
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .b1500_controller import B1500Controller
from .measurement_engine import StressMeasurementEngine
from .models import CycleConfig, StressConfig, SweepConfig, TestPhase
from .thorlabs_power_meter import ThorlabsPowerMeterController
from .worker_thread import ResourceRefreshWorker, TestWorker
class StressMeasurementCycleGUI(QMainWindow):
    """Main GUI for stress-measurement cycling tests"""
    
    def __init__(self):
        super().__init__()
        self.b1500 = B1500Controller()
        self.power_meter = ThorlabsPowerMeterController()
        self.worker = None
        self.resource_worker = None
        
        self.setWindowTitle("B1500 Stress-Measurement Cycling Test")
        self.setMinimumSize(1500, 950)
        
        # Plot data
        self.meas_voltages = []
        self.meas_currents = []
        self.meas_powers = []
        self.meas_cycles = []
        
        self.stress_times = []
        self.stress_currents = []
        self.stress_powers = []
        
        self.summary_cycles = []
        self.summary_peak_currents = []
        self.summary_peak_powers = []
        
        self.setup_ui()

        # Plot throttling: accumulate data and redraw at most every 400 ms
        # to prevent canvas.draw() calls from blocking the Qt event loop.
        self._meas_dirty = False
        self._stress_dirty = False
        self._degradation_dirty = False
        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(400)
        self._plot_timer.timeout.connect(self._flush_plot_updates)
        self._plot_timer.start()

        self.refresh_resources()
    
    def setup_ui(self):
        """Setup the GUI layout"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)
        
        # Left panel - controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_panel.setMinimumWidth(440)
        left_panel.setMaximumWidth(520)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setMinimumWidth(460)
        left_scroll.setMaximumWidth(540)
        left_scroll.setWidget(left_panel)
        
        # === Device Connection ===
        device_group = QGroupBox("Device Connection")
        device_layout = QGridLayout(device_group)
        device_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        device_layout.addWidget(QLabel("B1500:"), 0, 0)
        self.combo_b1500 = QComboBox()
        self.combo_b1500.setMinimumWidth(200)
        device_layout.addWidget(self.combo_b1500, 0, 1)
        
        self.btn_connect_b1500 = QPushButton("Connect")
        self.btn_connect_b1500.clicked.connect(self.connect_b1500)
        device_layout.addWidget(self.btn_connect_b1500, 0, 2)
        
        self.label_b1500_status = QLabel("Not connected")
        self.label_b1500_status.setStyleSheet("color: red;")
        device_layout.addWidget(self.label_b1500_status, 1, 0, 1, 3)
        
        device_layout.addWidget(QLabel("Power Meter:"), 2, 0)
        self.combo_power_meter = QComboBox()
        device_layout.addWidget(self.combo_power_meter, 2, 1)
        
        self.btn_connect_pm = QPushButton("Connect")
        self.btn_connect_pm.clicked.connect(self.connect_power_meter)
        device_layout.addWidget(self.btn_connect_pm, 2, 2)
        
        self.label_pm_status = QLabel("Not connected")
        self.label_pm_status.setStyleSheet("color: red;")
        device_layout.addWidget(self.label_pm_status, 3, 0, 1, 3)
        
        self.btn_refresh = QPushButton("Refresh Devices")
        self.btn_refresh.clicked.connect(self.refresh_resources)
        device_layout.addWidget(self.btn_refresh, 4, 0, 1, 3)
        
        left_layout.addWidget(device_group)
        
        # === Measurement Configuration ===
        meas_group = QGroupBox("IV Measurement Configuration")
        meas_layout = QGridLayout(meas_group)
        meas_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        meas_layout.addWidget(QLabel("SMU:"), 0, 0)
        self.spin_smu = QSpinBox()
        self.spin_smu.setRange(1, 10)
        self.spin_smu.setValue(1)
        meas_layout.addWidget(self.spin_smu, 0, 1)
        
        meas_layout.addWidget(QLabel("Mode:"), 0, 2)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["IV (Vâ†’I)", "VI (Iâ†’V)"])
        meas_layout.addWidget(self.combo_mode, 0, 3)
        
        meas_layout.addWidget(QLabel("Start:"), 1, 0)
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setRange(-200, 200)
        self.spin_start.setDecimals(4)
        self.spin_start.setValue(0)
        meas_layout.addWidget(self.spin_start, 1, 1)
        
        meas_layout.addWidget(QLabel("Stop:"), 1, 2)
        self.spin_stop = QDoubleSpinBox()
        self.spin_stop.setRange(-200, 200)
        self.spin_stop.setDecimals(4)
        self.spin_stop.setValue(2.0)
        meas_layout.addWidget(self.spin_stop, 1, 3)
        
        meas_layout.addWidget(QLabel("Steps:"), 2, 0)
        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(2, 1001)
        self.spin_steps.setValue(21)
        meas_layout.addWidget(self.spin_steps, 2, 1)
        
        meas_layout.addWidget(QLabel("Dwell (s):"), 2, 2)
        self.spin_dwell = QDoubleSpinBox()
        self.spin_dwell.setRange(0, 10)
        self.spin_dwell.setDecimals(3)
        self.spin_dwell.setValue(0.1)
        meas_layout.addWidget(self.spin_dwell, 2, 3)
        
        meas_layout.addWidget(QLabel("Compliance:"), 3, 0)
        self.spin_compliance = QDoubleSpinBox()
        self.spin_compliance.setRange(0.0001, 200)
        self.spin_compliance.setDecimals(6)
        self.spin_compliance.setValue(0.1)
        meas_layout.addWidget(self.spin_compliance, 3, 1)
        
        left_layout.addWidget(meas_group)
        
        # === Stress Configuration ===
        stress_group = QGroupBox("Stress Configuration")
        stress_layout = QGridLayout(stress_group)
        stress_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        stress_layout.addWidget(QLabel("Stress Mode:"), 0, 0)
        self.combo_stress_mode = QComboBox()
        self.combo_stress_mode.addItems(["Constant Voltage", "Constant Current"])
        stress_layout.addWidget(self.combo_stress_mode, 0, 1)
        
        stress_layout.addWidget(QLabel("Stress Value:"), 0, 2)
        self.spin_stress_value = QDoubleSpinBox()
        self.spin_stress_value.setRange(-200, 200)
        self.spin_stress_value.setDecimals(4)
        self.spin_stress_value.setValue(2.0)
        self.spin_stress_value.setSuffix(" V")
        stress_layout.addWidget(self.spin_stress_value, 0, 3)
        
        self.combo_stress_mode.currentIndexChanged.connect(self.on_stress_mode_changed)
        
        stress_layout.addWidget(QLabel("Duration (s):"), 1, 0)
        self.spin_stress_duration = QDoubleSpinBox()
        self.spin_stress_duration.setRange(1, 100000)
        self.spin_stress_duration.setDecimals(1)
        self.spin_stress_duration.setValue(60)
        stress_layout.addWidget(self.spin_stress_duration, 1, 1)
        
        stress_layout.addWidget(QLabel("Sample Rate (s):"), 1, 2)
        self.spin_stress_interval = QDoubleSpinBox()
        self.spin_stress_interval.setRange(0.1, 60)
        self.spin_stress_interval.setDecimals(2)
        self.spin_stress_interval.setValue(1.0)
        stress_layout.addWidget(self.spin_stress_interval, 1, 3)
        
        stress_layout.addWidget(QLabel("Stress Compliance:"), 2, 0)
        self.spin_stress_compliance = QDoubleSpinBox()
        self.spin_stress_compliance.setRange(0.0001, 200)
        self.spin_stress_compliance.setDecimals(6)
        self.spin_stress_compliance.setValue(0.1)
        stress_layout.addWidget(self.spin_stress_compliance, 2, 1)
        
        left_layout.addWidget(stress_group)
        
        # === Cycle Configuration ===
        cycle_group = QGroupBox("Cycle Configuration")
        cycle_layout = QGridLayout(cycle_group)
        cycle_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        cycle_layout.addWidget(QLabel("Number of Cycles:"), 0, 0)
        self.spin_num_cycles = QSpinBox()
        self.spin_num_cycles.setRange(1, 10000)
        self.spin_num_cycles.setValue(10)
        cycle_layout.addWidget(self.spin_num_cycles, 0, 1)
        
        self.check_initial_meas = QCheckBox("Initial Measurement (Baseline)")
        self.check_initial_meas.setChecked(True)
        cycle_layout.addWidget(self.check_initial_meas, 0, 2, 1, 2)
        
        left_layout.addWidget(cycle_group)
        
        # === Power Meter Config ===
        pm_group = QGroupBox("Power Meter")
        pm_layout = QGridLayout(pm_group)
        pm_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        self.check_enable_pm = QCheckBox("Enable Power Measurement")
        self.check_enable_pm.setChecked(True)
        pm_layout.addWidget(self.check_enable_pm, 0, 0, 1, 2)
        
        pm_layout.addWidget(QLabel("Wavelength (nm):"), 1, 0)
        self.spin_wavelength = QDoubleSpinBox()
        self.spin_wavelength.setRange(200, 2000)
        self.spin_wavelength.setValue(850)
        pm_layout.addWidget(self.spin_wavelength, 1, 1)
        
        left_layout.addWidget(pm_group)
        
        # === Output Configuration ===
        output_group = QGroupBox("Output")
        output_layout = QGridLayout(output_group)
        output_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        
        output_layout.addWidget(QLabel("Folder:"), 0, 0)
        self.edit_folder = QLineEdit(str(Path(__file__).parent / "results"))
        output_layout.addWidget(self.edit_folder, 0, 1)
        
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self.browse_folder)
        output_layout.addWidget(self.btn_browse, 0, 2)
        
        output_layout.addWidget(QLabel("Device Name:"), 1, 0)
        self.edit_device_name = QLineEdit("Device_001")
        output_layout.addWidget(self.edit_device_name, 1, 1, 1, 2)
        
        self.check_autosave = QCheckBox("Autosave Data")
        self.check_autosave.setChecked(True)
        output_layout.addWidget(self.check_autosave, 2, 0, 1, 3)
        
        left_layout.addWidget(output_group)
        
        # === Control Buttons ===
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("â–¶ Start Test")
        self.btn_start.setMinimumHeight(45)
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_test)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("â–  Stop")
        self.btn_stop.setMinimumHeight(45)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("font-size: 14px;")
        self.btn_stop.clicked.connect(self.stop_test)
        btn_layout.addWidget(self.btn_stop)
        
        left_layout.addLayout(btn_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)
        
        # Status label
        self.label_phase = QLabel("Phase: IDLE")
        self.label_phase.setStyleSheet("font-weight: bold; font-size: 12px;")
        left_layout.addWidget(self.label_phase)
        
        # Log
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        left_layout.addWidget(log_group)
        
        left_layout.addStretch()
        main_layout.addWidget(left_scroll)
        
        # === Right Panel - Plots ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Create tabs for different views
        self.tab_widget = QTabWidget()
        
        # Tab 1: Live Plots
        plot_tab = QWidget()
        plot_layout = QVBoxLayout(plot_tab)
        
        self.figure = Figure(figsize=(12, 9))
        self.canvas = FigureCanvas(self.figure)
        
        # Create 2x2 subplot grid
        self.ax_iv = self.figure.add_subplot(2, 2, 1)
        self.ax_iv.set_xlabel("Voltage (V)")
        self.ax_iv.set_ylabel("Current (A)")
        self.ax_iv.set_title("I-V Characteristic")
        self.ax_iv.grid(True, alpha=0.3)
        
        self.ax_li = self.figure.add_subplot(2, 2, 2)
        self.ax_li.set_xlabel("Current (A)")
        self.ax_li.set_ylabel("Optical Power (W)")
        self.ax_li.set_title("L-I Characteristic")
        self.ax_li.grid(True, alpha=0.3)
        
        self.ax_stress = self.figure.add_subplot(2, 2, 3)
        self.ax_stress.set_xlabel("Time (s)")
        self.ax_stress.set_ylabel("Current (A) / Power (W)")
        self.ax_stress.set_title("Stress Monitoring")
        self.ax_stress.grid(True, alpha=0.3)
        
        self.ax_degradation = self.figure.add_subplot(2, 2, 4)
        self.ax_degradation.set_xlabel("Cycle")
        self.ax_degradation.set_ylabel("Peak Values")
        self.ax_degradation.set_title("Degradation Tracking")
        self.ax_degradation.grid(True, alpha=0.3)
        
        self.figure.tight_layout()

        # Pre-create twin axes for stress/degradation plots so updates never
        # need to call ax.clear() + twinx() (which leaks axes and is slow).
        self.ax_stress_twin = self.ax_stress.twinx()
        self.ax_stress.set_ylabel("Current (A)", color='blue')
        self.ax_stress.tick_params(axis='y', labelcolor='blue')
        self.ax_stress_twin.set_ylabel("Optical Power (W)", color='red')
        self.ax_stress_twin.tick_params(axis='y', labelcolor='red')

        self.ax_degradation_twin = self.ax_degradation.twinx()
        self.ax_degradation.set_ylabel("Peak Current (A)", color='blue')
        self.ax_degradation.tick_params(axis='y', labelcolor='blue')
        self.ax_degradation_twin.set_ylabel("Peak Power (W)", color='red')
        self.ax_degradation_twin.tick_params(axis='y', labelcolor='red')

        # Pre-create Line2D objects; updates call set_data() instead of re-plotting.
        self._line_stress_current, = self.ax_stress.plot([], [], 'b-', linewidth=1, label='Current')
        self._line_stress_power, = self.ax_stress_twin.plot([], [], 'r-', linewidth=1, label='Power')
        self.ax_stress.legend([self._line_stress_current, self._line_stress_power],
                              ['Current', 'Power'], loc='upper right')

        self._line_deg_current, = self.ax_degradation.plot([], [], 'bo-', markersize=6, label='Peak Current')
        self._line_deg_power, = self.ax_degradation_twin.plot([], [], 'rs-', markersize=6, label='Peak Power')
        self.ax_degradation.legend([self._line_deg_current, self._line_deg_power],
                                   ['Peak Current', 'Peak Power'], loc='upper right')

        plot_layout.addWidget(self.canvas)
        
        self.tab_widget.addTab(plot_tab, "Live Plots")
        
        # Tab 2: Summary Table
        table_tab = QWidget()
        table_layout = QVBoxLayout(table_tab)
        
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels([
            "Cycle", "Timestamp", "Peak Current (A)", "Peak Power (W)",
            "Threshold V", "Series R (Î©)"
        ])
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_layout.addWidget(self.summary_table)
        
        self.tab_widget.addTab(table_tab, "Cycle Summary")
        
        right_layout.addWidget(self.tab_widget)
        main_layout.addWidget(right_panel, stretch=2)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def log(self, message: str):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def refresh_resources(self):
        if self.resource_worker and self.resource_worker.isRunning():
            self.status_bar.showMessage("Device scan already in progress...")
            return

        self.combo_b1500.clear()
        self.combo_power_meter.clear()

        self.btn_refresh.setEnabled(False)
        self.status_bar.showMessage("Scanning VISA resources...")

        self.resource_worker = ResourceRefreshWorker(self.b1500.list_all_resources)
        self.resource_worker.resources_ready.connect(self.on_resources_refreshed)
        self.resource_worker.refresh_failed.connect(self.on_resource_refresh_failed)
        self.resource_worker.finished.connect(self.on_resource_refresh_finished)
        self.resource_worker.start()

    def on_resources_refreshed(self, all_resources: List[str]):
        gpib_resources = [r for r in all_resources if "GPIB" in r.upper()]
        usb_resources = [r for r in all_resources if "USB" in r.upper()]

        self.combo_b1500.addItems(gpib_resources)
        self.combo_power_meter.addItems(usb_resources)

        message = f"Found {len(gpib_resources)} GPIB and {len(usb_resources)} USB resources"
        self.status_bar.showMessage(message)
        self.log(message)

    def on_resource_refresh_failed(self, error_message: str):
        self.status_bar.showMessage("Device scan failed")
        self.log(f"Device scan failed: {error_message}")

    def on_resource_refresh_finished(self):
        self.btn_refresh.setEnabled(True)
        self.resource_worker = None
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.edit_folder.setText(folder)
    
    def on_stress_mode_changed(self, index: int):
        if index == 0:
            self.spin_stress_value.setSuffix(" V")
        else:
            self.spin_stress_value.setSuffix(" A")
    
    def connect_b1500(self):
        if self.b1500.connected:
            self.b1500.disconnect()
            self.label_b1500_status.setText("Not connected")
            self.label_b1500_status.setStyleSheet("color: red;")
            self.btn_connect_b1500.setText("Connect")
            self.log("B1500 disconnected")
        else:
            resource = self.combo_b1500.currentText()
            if not resource:
                QMessageBox.warning(self, "Error", "No B1500 resource selected")
                return
            
            success, msg = self.b1500.connect(resource)
            if success:
                self.label_b1500_status.setText(f"Connected: {self.b1500.idn[:40]}...")
                self.label_b1500_status.setStyleSheet("color: green;")
                self.btn_connect_b1500.setText("Disconnect")
                self.log(f"B1500 connected: {self.b1500.idn}")
            else:
                QMessageBox.warning(self, "Connection Failed", msg)
    
    def connect_power_meter(self):
        if self.power_meter.connected:
            self.power_meter.disconnect()
            self.label_pm_status.setText("Not connected")
            self.label_pm_status.setStyleSheet("color: red;")
            self.btn_connect_pm.setText("Connect")
            self.log("Power meter disconnected")
        else:
            resource = self.combo_power_meter.currentText()
            if not resource:
                QMessageBox.warning(self, "Error", "No power meter resource selected")
                return
            
            success, msg = self.power_meter.connect(resource)
            if success:
                self.label_pm_status.setText(f"Connected: {self.power_meter.idn[:40]}...")
                self.label_pm_status.setStyleSheet("color: green;")
                self.btn_connect_pm.setText("Disconnect")
                self.log(f"Power meter connected: {self.power_meter.idn}")
            else:
                QMessageBox.warning(self, "Connection Failed", msg)
    
    def get_config(self) -> CycleConfig:
        mode = "iv" if self.combo_mode.currentIndex() == 0 else "vi"
        stress_mode = "voltage" if self.combo_stress_mode.currentIndex() == 0 else "current"
        
        return CycleConfig(
            sweep=SweepConfig(
                smu=self.spin_smu.value(),
                mode=mode,
                start=self.spin_start.value(),
                stop=self.spin_stop.value(),
                steps=self.spin_steps.value(),
                dwell_s=self.spin_dwell.value(),
                compliance=self.spin_compliance.value()
            ),
            stress=StressConfig(
                mode=stress_mode,
                value=self.spin_stress_value.value(),
                duration_s=self.spin_stress_duration.value(),
                sample_interval_s=self.spin_stress_interval.value(),
                compliance=self.spin_stress_compliance.value()
            ),
            num_cycles=self.spin_num_cycles.value(),
            initial_measurement=self.check_initial_meas.isChecked(),
            enable_power_meter=self.check_enable_pm.isChecked(),
            power_wavelength_nm=self.spin_wavelength.value(),
            output_folder=self.edit_folder.text(),
            device_name=self.edit_device_name.text(),
            autosave=self.check_autosave.isChecked()
        )
    
    def start_test(self):
        if not self.b1500.connected and not self.power_meter.connected:
            QMessageBox.warning(self, "Error", "No devices connected")
            return
        
        # Clear data
        self.meas_voltages = []
        self.meas_currents = []
        self.meas_powers = []
        self.meas_cycles = []
        self.stress_times = []
        self.stress_currents = []
        self.stress_powers = []
        self.summary_cycles = []
        self.summary_peak_currents = []
        self.summary_peak_powers = []
        
        self.summary_table.setRowCount(0)
        self.update_plots()
        
        config = self.get_config()
        engine = StressMeasurementEngine(self.b1500, self.power_meter, config)
        
        self.worker = TestWorker(engine)
        self.worker.measurement_point.connect(self.on_measurement_point)
        self.worker.stress_point.connect(self.on_stress_point)
        self.worker.phase_change.connect(self.on_phase_change)
        self.worker.cycle_complete.connect(self.on_cycle_complete)
        self.worker.progress.connect(self.on_progress)
        self.worker.log_message.connect(self.log)
        self.worker.finished_signal.connect(self.on_test_complete)
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        
        self.worker.start()
    
    def stop_test(self):
        if self.worker and self.worker.engine:
            self.worker.engine.stop()
            self.log("Stop requested...")
    
    def on_measurement_point(self, point: MeasurementPoint):
        self.meas_voltages.append(point.voltage)
        self.meas_currents.append(point.current)
        self.meas_powers.append(point.optical_power)
        self.meas_cycles.append(point.cycle)
        self._meas_dirty = True
    
    def on_stress_point(self, point: StressPoint):
        self.stress_times.append(point.elapsed_s)
        self.stress_currents.append(point.current)
        self.stress_powers.append(point.optical_power)
        self._stress_dirty = True
    
    def on_phase_change(self, phase: TestPhase):
        phase_colors = {
            TestPhase.IDLE: "gray",
            TestPhase.MEASUREMENT: "blue",
            TestPhase.STRESS: "orange",
            TestPhase.COMPLETED: "green",
            TestPhase.STOPPED: "red"
        }
        color = phase_colors.get(phase, "black")
        self.label_phase.setText(f"Phase: {phase.value.upper()}")
        self.label_phase.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {color};")
        
        # Clear stress data when entering stress phase
        if phase == TestPhase.STRESS:
            self.stress_times = []
            self.stress_currents = []
            self.stress_powers = []
            self._line_stress_current.set_data([], [])
            self._line_stress_power.set_data([], [])
            self._stress_dirty = False
    
    def on_cycle_complete(self, cycle: int):
        # Add to summary table
        if self.worker and self.worker.engine.cycle_summaries:
            summary = self.worker.engine.cycle_summaries[-1]
            
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
            self.summary_table.setItem(row, 0, QTableWidgetItem(str(summary.cycle)))
            self.summary_table.setItem(row, 1, QTableWidgetItem(summary.timestamp[:19]))
            self.summary_table.setItem(row, 2, QTableWidgetItem(f"{summary.peak_current:.4e}"))
            self.summary_table.setItem(row, 3, QTableWidgetItem(f"{summary.peak_power:.4e}"))
            self.summary_table.setItem(row, 4, QTableWidgetItem(f"{summary.threshold_voltage:.4f}"))
            self.summary_table.setItem(row, 5, QTableWidgetItem(f"{summary.series_resistance:.2f}"))
            
            self.summary_cycles.append(summary.cycle)
            self.summary_peak_currents.append(summary.peak_current)
            self.summary_peak_powers.append(summary.peak_power)
            self._degradation_dirty = True
    
    def on_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_bar.showMessage(f"Cycle {current}/{total}")
    
    def on_test_complete(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_bar.showMessage("Test complete")
        self.log("=" * 50)
        self.log("TEST COMPLETED")
    
    def _flush_plot_updates(self):
        """Timer callback: flush all dirty plot updates at most every 400 ms.
        Calling canvas.draw_idle() once here instead of draw() inside each
        handler prevents the Qt event loop from being blocked by Matplotlib."""
        needs_draw = False
        if self._meas_dirty:
            self._meas_dirty = False
            self.update_measurement_plots()
            needs_draw = True
        if self._stress_dirty:
            self._stress_dirty = False
            self.update_stress_plot()
            needs_draw = True
        if self._degradation_dirty:
            self._degradation_dirty = False
            self.update_degradation_plot()
            needs_draw = True
        if needs_draw:
            self.canvas.draw_idle()

    def update_measurement_plots(self):
        if not self.meas_voltages:
            return
        
        # Get current cycle data
        current_cycle = self.meas_cycles[-1] if self.meas_cycles else 0
        cycle_mask = [c == current_cycle for c in self.meas_cycles]
        
        v_cycle = [v for v, m in zip(self.meas_voltages, cycle_mask) if m]
        i_cycle = [i for i, m in zip(self.meas_currents, cycle_mask) if m]
        p_cycle = [p for p, m in zip(self.meas_powers, cycle_mask) if m]
        
        # IV plot
        self.ax_iv.clear()
        self.ax_iv.plot(v_cycle, i_cycle, 'b.-', linewidth=1, markersize=3)
        self.ax_iv.set_xlabel("Voltage (V)")
        self.ax_iv.set_ylabel("Current (A)")
        self.ax_iv.set_title(f"I-V Characteristic (Cycle {current_cycle})")
        self.ax_iv.grid(True, alpha=0.3)
        
        # LI plot
        self.ax_li.clear()
        self.ax_li.plot(i_cycle, p_cycle, 'r.-', linewidth=1, markersize=3)
        self.ax_li.set_xlabel("Current (A)")
        self.ax_li.set_ylabel("Optical Power (W)")
        self.ax_li.set_title(f"L-I Characteristic (Cycle {current_cycle})")
        self.ax_li.grid(True, alpha=0.3)
        # draw_idle() is called once by _flush_plot_updates after all dirty plots are updated
    
    def update_stress_plot(self):
        if not self.stress_times:
            return
        
        self._line_stress_current.set_data(self.stress_times, self.stress_currents)
        self._line_stress_power.set_data(self.stress_times, self.stress_powers)
        self.ax_stress.relim()
        self.ax_stress.autoscale_view()
        self.ax_stress_twin.relim()
        self.ax_stress_twin.autoscale_view()
        self.ax_stress.set_title(f"Stress Monitoring ({len(self.stress_times)} samples)")
    
    def update_degradation_plot(self):
        if not self.summary_cycles:
            return
        
        self._line_deg_current.set_data(self.summary_cycles, self.summary_peak_currents)
        self._line_deg_power.set_data(self.summary_cycles, self.summary_peak_powers)
        self.ax_degradation.relim()
        self.ax_degradation.autoscale_view()
        self.ax_degradation_twin.relim()
        self.ax_degradation_twin.autoscale_view()
    
    def update_plots(self):
        """Full reset of all plots. Called once at the start of each test run."""
        self.ax_iv.clear()
        self.ax_iv.set_xlabel("Voltage (V)")
        self.ax_iv.set_ylabel("Current (A)")
        self.ax_iv.set_title("I-V Characteristic")
        self.ax_iv.grid(True, alpha=0.3)
        
        self.ax_li.clear()
        self.ax_li.set_xlabel("Current (A)")
        self.ax_li.set_ylabel("Optical Power (W)")
        self.ax_li.set_title("L-I Characteristic")
        self.ax_li.grid(True, alpha=0.3)
        
        # Reset stress lines without clearing the pre-created twin axis
        self._line_stress_current.set_data([], [])
        self._line_stress_power.set_data([], [])
        self.ax_stress.set_title("Stress Monitoring")
        self.ax_stress.relim()
        self.ax_stress.autoscale_view()
        self.ax_stress_twin.relim()
        self.ax_stress_twin.autoscale_view()
        
        # Reset degradation lines without clearing the pre-created twin axis
        self._line_deg_current.set_data([], [])
        self._line_deg_power.set_data([], [])
        self.ax_degradation.set_title("Degradation Tracking")
        self.ax_degradation.relim()
        self.ax_degradation.autoscale_view()
        self.ax_degradation_twin.relim()
        self.ax_degradation_twin.autoscale_view()
        
        self._meas_dirty = False
        self._stress_dirty = False
        self._degradation_dirty = False
        
        self.figure.tight_layout()
        self.canvas.draw_idle()
    
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.stop_test()
            self.worker.wait(2000)
        
        self.b1500.disconnect()
        self.power_meter.disconnect()
        event.accept()



