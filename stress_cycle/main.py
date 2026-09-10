"""Main entry point for stress cycle GUI."""

import argparse
import sys

from PyQt5.QtWidgets import QApplication

from .gui import StressMeasurementCycleGUI


def main():
    parser = argparse.ArgumentParser(
        description="B1500 + Power Meter Stress-Measurement Cycling Test"
    )
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode (not implemented)")

    args = parser.parse_args()

    if args.cli:
        print("CLI mode not implemented yet. Please use GUI mode.")
        return

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = StressMeasurementCycleGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
