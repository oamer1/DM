import logging
import os
import subprocess
import sys
from typing import List

from PyQt5.QtCore import QAbstractTableModel, Qt, QVariant
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QTableView,
    QHeaderView,
)

from .ui.WTGGUI import Ui_Dialog
from . import wtf_gui
import log

LOGGER = log.getLogger(__name__)


class AppWindow(QDialog, Ui_Dialog):
    """
    Implement and inherit UI file
    """

    def __init__(self):
        super().__init__()

        # Set up UI file
        self.setupUi(self)

        self.setup_tableview()
        self.on_selection_changed()

        # On start show module Status
        self.show_module_status()

        # Open log file Btn
        self.toolButton.clicked.connect(self.open_recent_logfile)

        # logTextBox
        log_box = log.GUILogHandler(self.textBrowser_2)
        LOGGER.addHandler(log_box)

        # Show module status
        self.pushButton.clicked.connect(self.show_module_status)

        # Populate workspace
        self.pushButton_4.clicked.connect(self.populate_workspace)

        # Populate module button
        self.pushButton_5.clicked.connect(self.populate_module)

        # Restore module button
        self.pushButton_3.clicked.connect(self.restore_module)

        # Update module button
        self.pushButton_2.clicked.connect(self.update_module)

        # ws_name text browser
        self.textBrowser_3.setText(self.get_ws_name())

    @property
    def selected_mod(self):
        """Return selected module name"""
        row = self.tableView.selectionModel().selectedRows()
        index = row[0].row()
        return self.model._data[index][0]

    def get_ws_name(self):
        """Return ws_name string"""

        if "PROJ_USER_WORK" not in os.environ:
            return ""

        proj_user_env_var = os.environ["PROJ_USER_WORK"]
        ws_name = proj_user_env_var.partition("/work/")[-1]
        return ws_name

    def show_module_status(self):
        rows = wtf_gui.wtf_status()
        self.model = TableModel(rows)
        self.tableView.setModel(self.model)
        self.tableView.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.on_selection_changed()
        selectionModel = self.tableView.selectionModel()
        selectionModel.selectionChanged.connect(self.on_selection_changed)

    def populate_workspace(self):
        LOGGER.info(f"Populate workspace.")
        wtf_gui.pop_workspace()

    def open_recent_logfile(self):
        """open most recent logfile"""
        log_dir = log.LOG_FILE_DIR
        log_files = []
        log_files.extend(log_dir.glob("*.log"))
        log_files.extend(log_dir.glob("*.log.*[1-9]"))

        if not log_files:
            LOGGER.info("No log files found logging directory.")
            return None

        latest_log = max(log_files, key=lambda x: x.stat().st_ctime)
        LOGGER.info(f"Open log file {latest_log}")
        try:
            subprocess.call(("xdg-open", latest_log))
        except Exception:
            LOGGER.error("Could not open file.", exc_info=True)

    def setup_tableview(self):
        """
        Set up and tailor tableview from UI
        """
        self.tableView.setVerticalScrollBar(self.verticalScrollBar)
        self.tableView.setHorizontalScrollBar(self.horizontalScrollBar)
        # Selection by row not cells
        self.tableView.setSelectionBehavior(QTableView.SelectRows)
        # Show grid
        self.tableView.setShowGrid(True)
        self.tableView.resizeColumnsToContents()

        # Selection is by single row only
        self.tableView.setSelectionMode(QAbstractItemView.SingleSelection)
        # Fit columns to view
        self.tableView.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def populate_module(self):
        LOGGER.info(f"Populate {self.selected_mod} module.")
        wtf_gui.pop_module(self.selected_mod)

    def restore_module(self):
        LOGGER.info(f"Restore {self.selected_mod} module.")
        wtf_gui.restore_module([self.selected_mod])

    def update_module(self):
        LOGGER.info(f"Update {self.selected_mod} module.")
        wtf_gui.update([self.selected_mod])

    def on_selection_changed(self):
        """
        Disable buttons on left until a row is selected
        """
        enabled = False
        data_on = self.tableView.selectionModel()
        if data_on and data_on.selectedRows():
            enabled = True

        # enabled = bool(self.tableView.selectionModel().selectedRows())
        self.pushButton_2.setEnabled(enabled)
        self.pushButton_3.setEnabled(enabled)
        self.pushButton_5.setEnabled(enabled)


class TableModel(QAbstractTableModel):
    """
    Table model for table view
    """

    def __init__(self, data):
        super(TableModel, self).__init__()
        self._data = data
        self._header = ["Module Instance", "Workspace", "baseline", "Relpath", "Status"]
        self._index = list(range(1, len(self._data) + 1))

    def data(self, index, role):
        if role == Qt.DisplayRole:
            i = index.row()
            j = index.column()
            return self._data[i][j]
        elif role == Qt.TextAlignmentRole:
            # Center align text in cells
            return Qt.AlignCenter
        return QVariant()

    def rowCount(self, index):
        # The length of the outer list.
        return len(self._data)

    def columnCount(self, index):
        # The following takes the first sub-list, and returns
        # All rows are equal length
        return len(self._data[0])

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            # Header
            if orientation == Qt.Horizontal:
                return self._header[section]
            # index vertical header
            if orientation == Qt.Vertical:
                return self._index[section]
        return QVariant()


def trigger_GUI() -> None:
    app = QApplication(sys.argv)
    w = AppWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    trigger_GUI()
