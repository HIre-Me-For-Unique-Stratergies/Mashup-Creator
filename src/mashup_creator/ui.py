
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

from . import security
from . import constants as c
from .creator import CreationJob
from .worker import RenderWorker
from .utils import list_files, probe_duration, open_in_file_explorer


class VideoSlotBlock(QtWidgets.QFrame):
    clicked = QtCore.pyqtSignal(int)

    def __init__(self, slot_index: int):
        super().__init__()
        self.slot_index = slot_index
        self.path: Optional[Path] = None
        self.setObjectName("videoSlot")
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(132, 150)
        self.setMaximumHeight(164)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.title_label = QtWidgets.QLabel(f"Slot {slot_index + 1}")
        self.title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("color: #24163c; font-weight: 800;")
        layout.addWidget(self.title_label)

        self.thumbnail_label = QtWidgets.QLabel("Empty")
        self.thumbnail_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setFixedHeight(74)
        self.thumbnail_label.setMinimumWidth(112)
        self.thumbnail_label.setStyleSheet(
            "background: #24163c; color: #ffffff; border-radius: 6px; font-weight: 800;"
        )
        layout.addWidget(self.thumbnail_label)

        self.name_label = QtWidgets.QLabel("No video")
        self.name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.name_label.setFixedHeight(30)
        self.name_label.setStyleSheet("color: #473064; font-size: 10px; font-weight: 700;")
        layout.addWidget(self.name_label)

        self.set_selected(False)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(self.slot_index)
        super().mousePressEvent(event)

    def set_video(self, path: Optional[Path], thumbnail_path: Optional[Path], selected: bool) -> None:
        self.path = path
        if path is None:
            self.thumbnail_label.setPixmap(QtGui.QPixmap())
            self.thumbnail_label.setText("Empty")
            self.name_label.setText("No video")
            self.setToolTip("")
        else:
            pixmap = QtGui.QPixmap(str(thumbnail_path)) if thumbnail_path else QtGui.QPixmap()
            if pixmap.isNull():
                self.thumbnail_label.setPixmap(QtGui.QPixmap())
                self.thumbnail_label.setText("Preview unavailable")
            else:
                scaled = pixmap.scaled(
                    self.thumbnail_label.size(),
                    QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                self.thumbnail_label.setText("")
                self.thumbnail_label.setPixmap(scaled)
            metrics = QtGui.QFontMetrics(self.name_label.font())
            self.name_label.setText(metrics.elidedText(path.name, QtCore.Qt.TextElideMode.ElideMiddle, 112))
            self.setToolTip(str(path))
        self.set_selected(selected)

    def set_selected(self, selected: bool) -> None:
        border = "#7b4dff" if selected else "#e0d5ff"
        background = "#f7f1ff" if selected else "#ffffff"
        self.setStyleSheet(
            f"QFrame#videoSlot {{ background: {background}; border: 2px solid {border}; border-radius: 8px; }}"
        )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(c.APP_NAME)
        self._apply_window_size()
        self._apply_icon()

        self.settings_path = c.CONFIG_DIR / "settings.json"
        self.log_messages = []
        self.error_messages = []
        self.last_job_info = {}
        self.latest_output_file: Optional[Path] = None

        self.worker_thread: Optional[QtCore.QThread] = None
        self.worker: Optional[RenderWorker] = None
        self.batch_stop_flag = threading.Event()
        self.job_start_time = None
        self.render_start_time = None
        self.rendering = False
        self.cleanup_pending = False
        self.close_requested = False

        self._init_state()
        self._build_ui()
        self._load_settings()
        self._refresh_lists()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick_timer)
        self.timer.start(250)

    def _apply_window_size(self):
        self.resize(1180, 780)
        self.setMinimumSize(1100, 740)
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            self.move(rect.center() - self.rect().center())

    def _apply_icon(self):
        if c.ICON_ICO_PATH.exists():
            self.setWindowIcon(QtGui.QIcon(str(c.ICON_ICO_PATH)))
        elif c.ICON_PATH.exists():
            self.setWindowIcon(QtGui.QIcon(str(c.ICON_PATH)))

    def _init_state(self):
        self.render_speed = "ultrafast"
        self.downscale = True
        self.sfx_volume = 1.35
        self.batch_count = 1
        self.hw_encode = False
        self.auto_create = True
        self.video_source_dir = str(c.VIDEO_DIR)
        self.include_video_subfolders = False

    def _theme(self) -> str:
        return """
        QMainWindow { background: #6d42e8; }
        QWidget { font-size: 13px; }
        QLabel { color: #ffffff; font-weight: 600; }
        QFrame#header { background: #7b4dff; border: 1px solid #9b82ff; border-radius: 8px; }
        QFrame#modeBox { background: #f7f1ff; border: 1px solid #e0d5ff; border-radius: 8px; }
        QWidget#sidePanel { background: #f7f1ff; border: 1px solid #e0d5ff; border-radius: 8px; }
        QScrollArea { background: transparent; border: none; }
        QLabel#subtitle { color: #efe9ff; font-size: 12px; font-weight: 600; }
        QGroupBox QLabel { color: #24163c; font-weight: 600; }
        QGroupBox QCheckBox, QGroupBox QRadioButton { color: #24163c; font-weight: 600; }
        QGroupBox { color: #24163c; background: #ffffff; border: 1px solid #e0d5ff; border-radius: 8px; margin-top: 14px; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #ffffff; font-size: 14px; font-weight: 800; }
        QGroupBox#createBox::title, QGroupBox#outputBox::title { color: #7b4dff; }
        QTextEdit { background: #ffffff; color: #24163c; border: 1px solid #e0d5ff; border-radius: 8px; }
        QProgressBar { border: 1px solid #e0d5ff; border-radius: 6px; text-align: center; background: #ffffff; min-height: 14px; max-height: 14px; }
        QProgressBar::chunk { background-color: #2fbf71; border-radius: 6px; }
        QPushButton { background: #ffffff; color: #24163c; border: 1px solid #e0d5ff; border-radius: 6px; padding: 8px 12px; font-weight: 700; }
        QPushButton:hover { background: #f3ebff; }
        QPushButton:disabled { background: #f5f2fb; color: #9b90ac; }
        QPushButton#accent { background: #7b4dff; color: #ffffff; border: 1px solid #7b4dff; }
        QPushButton#accent:hover { background: #5a35cc; }
        QPushButton#accent_alt { background: #ff6fb1; color: #ffffff; border: 1px solid #ff6fb1; }
        QPushButton#accent_alt:hover { background: #e6589a; }
        QSpinBox, QDoubleSpinBox { background: #ffffff; color: #24163c; border: 1px solid #e0d5ff; border-radius: 6px; padding: 6px 8px; }
        QMenuBar { background: #5a35cc; color: #ffffff; border-bottom: 1px solid #8b6cff; }
        QMenuBar::item:selected { background: #7b4dff; }
        QMenu { background: #ffffff; color: #24163c; border: 1px solid #e0d5ff; }
        QMenu::item:selected { background: #f3ebff; }
        QScrollBar:vertical { background: #f3ebff; width: 12px; margin: 2px; border-radius: 6px; }
        QScrollBar::handle:vertical { background: #7b4dff; min-height: 24px; border-radius: 6px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        QScrollBar:horizontal { background: #f3ebff; height: 12px; margin: 2px; border-radius: 6px; }
        QScrollBar::handle:horizontal { background: #7b4dff; min-width: 24px; border-radius: 6px; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
        """
    def _build_ui(self):
        self.setStyleSheet(self._theme())

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QtWidgets.QFrame()
        header.setObjectName("header")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(14)

        title_label = QtWidgets.QLabel()
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        if c.TITLE_IMAGE_PATH.exists():
            pix = QtGui.QPixmap(str(c.TITLE_IMAGE_PATH))
            if not pix.isNull():
                scaled = pix.scaled(
                    360,
                    72,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                title_label.setPixmap(scaled)
            else:
                title_label.setText(c.APP_NAME)
        else:
            title_label.setText(c.APP_NAME)
            title_label.setStyleSheet("font-size: 26px; font-weight: 800; color: #ffffff;")
        header_layout.addWidget(title_label)

        subtitle = QtWidgets.QLabel("Quick random cuts with songs and SFX")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.main_page = QtWidgets.QWidget()
        self.advanced_page = QtWidgets.QWidget()
        self.stack.addWidget(self.main_page)
        self.stack.addWidget(self.advanced_page)

        self._build_main_page()
        self._build_advanced_page()
        self._build_menu()

    def _build_main_page(self):
        main_layout = QtWidgets.QVBoxLayout(self.main_page)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(4, 4, 4, 4)

        workspace = QtWidgets.QHBoxLayout()
        workspace.setSpacing(12)
        main_layout.addLayout(workspace, 1)

        left_panel = QtWidgets.QWidget()
        left_panel.setMinimumWidth(680)
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        workspace.addWidget(left_panel, 1)

        media_box = QtWidgets.QGroupBox("Gameplay Sources")
        media_box.setMinimumHeight(230)
        media_layout = QtWidgets.QVBoxLayout(media_box)
        media_layout.setContentsMargins(14, 18, 14, 14)
        media_layout.setSpacing(12)

        counts_row = QtWidgets.QHBoxLayout()
        counts_row.setSpacing(8)
        self.video_count_lbl = QtWidgets.QLabel("Source videos: 0")
        self.audio_count_lbl = QtWidgets.QLabel("Built-in songs: 0")
        self.sfx_count_lbl = QtWidgets.QLabel("Built-in SFX: 0")
        for label in [self.video_count_lbl, self.audio_count_lbl, self.sfx_count_lbl]:
            label.setStyleSheet(
                "background: #f3ebff; border: 1px solid #e0d5ff; border-radius: 6px; "
                "padding: 5px 8px; color: #473064; font-size: 12px; font-weight: 700;"
            )
            counts_row.addWidget(label)
        counts_row.addStretch()
        media_layout.addLayout(counts_row)

        folder_box = QtWidgets.QFrame()
        folder_box.setObjectName("modeBox")
        folder_box.setMinimumHeight(142)
        folder_layout = QtWidgets.QVBoxLayout(folder_box)
        folder_layout.setContentsMargins(12, 12, 12, 12)
        folder_layout.setSpacing(8)
        folder_title = QtWidgets.QLabel("Video Source Folder")
        folder_title.setStyleSheet("color: #24163c; font-size: 12px; font-weight: 800;")
        folder_layout.addWidget(folder_title)
        self.video_folder_label = QtWidgets.QLabel("")
        self.video_folder_label.setWordWrap(False)
        self.video_folder_label.setMinimumHeight(24)
        self.video_folder_label.setStyleSheet("color: #473064; font-size: 12px; font-weight: 700;")
        folder_layout.addWidget(self.video_folder_label)
        self.chk_include_subfolders = QtWidgets.QCheckBox("Include videos in subfolders")
        self.chk_include_subfolders.setToolTip("When enabled, videos inside folders below the selected folder can be used.")
        self.chk_include_subfolders.stateChanged.connect(self._on_include_subfolders_changed)
        folder_layout.addWidget(self.chk_include_subfolders)
        source_buttons = QtWidgets.QHBoxLayout()
        source_buttons.setSpacing(8)
        self.btn_choose_video_folder = self._btn("Choose Folder", self.choose_video_folder)
        self.btn_open_video_folder = self._btn("Open Folder", self.open_video_folder)
        self.btn_refresh_sources = self._btn("Refresh", self._refresh_lists)
        for btn in [self.btn_choose_video_folder, self.btn_open_video_folder, self.btn_refresh_sources]:
            source_buttons.addWidget(btn)
        folder_layout.addLayout(source_buttons)
        media_layout.addWidget(folder_box)
        left_layout.addWidget(media_box)

        logs_box = QtWidgets.QGroupBox("Activity")
        logs_layout = QtWidgets.QVBoxLayout(logs_box)
        logs_layout.setContentsMargins(14, 18, 14, 14)
        logs_layout.setSpacing(10)
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(160)
        logs_layout.addWidget(self.log_text)
        activity_status = QtWidgets.QFrame()
        activity_status.setObjectName("modeBox")
        activity_status_layout = QtWidgets.QVBoxLayout(activity_status)
        activity_status_layout.setContentsMargins(10, 10, 10, 10)
        activity_status_layout.setSpacing(8)
        self.status_label = QtWidgets.QLabel("Ready.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #24163c; font-weight: 700;")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.timer_label = QtWidgets.QLabel("Time: --:--")
        self.timer_label.setStyleSheet("color: #473064; font-weight: 700;")
        activity_status_layout.addWidget(self.status_label)
        activity_status_layout.addWidget(self.progress)
        activity_status_layout.addWidget(self.timer_label)
        logs_layout.addWidget(activity_status)
        left_layout.addWidget(logs_box, 1)

        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setFixedWidth(340)
        workspace.addWidget(right_scroll)

        right_panel = QtWidgets.QWidget()
        right_panel.setMinimumWidth(320)
        right_panel.setObjectName("sidePanel")
        right_scroll.setWidget(right_panel)
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        create_box = QtWidgets.QGroupBox("Create")
        create_box.setObjectName("createBox")
        create_box.setMinimumHeight(390)
        create_layout = QtWidgets.QVBoxLayout(create_box)
        create_layout.setContentsMargins(14, 18, 14, 14)
        create_layout.setSpacing(10)
        self.btn_start = self._btn("Start", self.start_creation, accent=True)
        self.btn_start.setMinimumHeight(42)
        self.btn_preview = self._btn("Preview 5s", self.start_preview)
        self.btn_preview.setMinimumHeight(36)
        create_layout.addWidget(self.btn_start)
        create_layout.addWidget(self.btn_preview)

        mode_box = QtWidgets.QFrame()
        mode_box.setObjectName("modeBox")
        mode_box.setMinimumHeight(150)
        mode_layout = QtWidgets.QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(12, 12, 12, 12)
        mode_layout.setSpacing(8)
        mode_title = QtWidgets.QLabel("Creation Mode")
        mode_title.setStyleSheet("color: #24163c; font-size: 12px; font-weight: 800;")
        mode_layout.addWidget(mode_title)
        self.chk_auto = QtWidgets.QCheckBox("Keep creating until I press Cancel")
        self.chk_auto.setToolTip("When enabled, Start keeps making videos with no fixed limit.")
        self.chk_auto.stateChanged.connect(self._update_creation_mode_ui)
        mode_layout.addWidget(self.chk_auto)
        batch_row = QtWidgets.QHBoxLayout()
        batch_row.setSpacing(8)
        self.batch_label = QtWidgets.QLabel("Videos to create")
        self.batch_label.setStyleSheet("color: #24163c; font-weight: 700;")
        self.spin_batch = QtWidgets.QSpinBox()
        self.spin_batch.setRange(1, 5)
        self.spin_batch.setToolTip("Used when unlimited auto-create is off.")
        self.spin_batch.valueChanged.connect(self._update_creation_mode_ui)
        batch_row.addWidget(self.batch_label, 1)
        batch_row.addWidget(self.spin_batch)
        mode_layout.addLayout(batch_row)
        self.mode_summary = QtWidgets.QLabel("")
        self.mode_summary.setWordWrap(True)
        self.mode_summary.setMinimumHeight(34)
        self.mode_summary.setStyleSheet("color: #5f4a78; font-size: 11px; font-weight: 700;")
        mode_layout.addWidget(self.mode_summary)
        create_layout.addWidget(mode_box)

        render_controls = QtWidgets.QHBoxLayout()
        render_controls.setSpacing(8)
        self.btn_pause = self._btn("Pause", self.pause_creation)
        self.btn_resume = self._btn("Resume", self.resume_creation)
        self.btn_cancel = self._btn("Cancel", self.cancel_creation, accent_alt=True)
        for btn in [self.btn_pause, self.btn_resume, self.btn_cancel]:
            render_controls.addWidget(btn)
        create_layout.addLayout(render_controls)
        self.btn_advanced = self._btn("Advanced Settings", lambda: self.stack.setCurrentWidget(self.advanced_page))
        create_layout.addWidget(self.btn_advanced)
        right_layout.addWidget(create_box)

        output_box = QtWidgets.QGroupBox("Output")
        output_box.setObjectName("outputBox")
        output_box.setMinimumHeight(175)
        output_layout = QtWidgets.QVBoxLayout(output_box)
        output_layout.setContentsMargins(14, 18, 14, 14)
        output_layout.setSpacing(8)
        self.btn_open_creations = self._btn("Open Creations", lambda: open_in_file_explorer(c.OUTPUTS_DIR))
        self.btn_open_latest = self._btn("Open Latest", self.open_latest)
        self.btn_copy_report = self._btn("Copy Report", self.copy_report)
        for btn in [self.btn_open_creations, self.btn_open_latest, self.btn_copy_report]:
            output_layout.addWidget(btn)
        right_layout.addWidget(output_box)
        right_layout.addStretch()

        self._set_button_state(self.btn_pause, False)
        self._set_button_state(self.btn_resume, False)
        self._set_button_state(self.btn_cancel, False)
        self._set_button_state(self.btn_open_latest, False)

    def _build_advanced_page(self):
        adv_layout = QtWidgets.QVBoxLayout(self.advanced_page)
        adv_layout.setSpacing(14)
        adv_layout.setContentsMargins(10, 10, 10, 10)

        back_btn = self._btn("Back", lambda: self.stack.setCurrentWidget(self.main_page))
        adv_layout.addWidget(back_btn, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        perf = QtWidgets.QGroupBox("Performance")
        p_layout = QtWidgets.QFormLayout(perf)
        p_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        p_layout.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        p_layout.setHorizontalSpacing(12)
        p_layout.setVerticalSpacing(8)
        self.radio_fast = QtWidgets.QRadioButton("Very fast")
        self.radio_ultra = QtWidgets.QRadioButton("Ultra fast")
        p_layout.addRow("Preset", self._hbox([self.radio_fast, self.radio_ultra]))
        self.chk_downscale = QtWidgets.QCheckBox("Export 720x1280 (faster)")
        self.chk_hw = QtWidgets.QCheckBox("Use Intel Quick Sync (if available)")
        p_layout.addRow(self.chk_downscale)
        p_layout.addRow(self.chk_hw)
        grid.addWidget(perf, 0, 0)

        audio = QtWidgets.QGroupBox("Mix")
        a_layout = QtWidgets.QFormLayout(audio)
        a_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        a_layout.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        a_layout.setHorizontalSpacing(12)
        a_layout.setVerticalSpacing(8)
        self.spin_sfx = QtWidgets.QDoubleSpinBox()
        self.spin_sfx.setRange(0.5, 3.0)
        self.spin_sfx.setSingleStep(0.1)
        a_layout.addRow("SFX volume", self.spin_sfx)
        grid.addWidget(audio, 0, 1)

        adv_layout.addLayout(grid)
        adv_layout.addStretch()

    def _btn(self, text: str, handler, accent: bool = False, accent_alt: bool = False) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(text)
        if accent:
            btn.setObjectName("accent")
        if accent_alt:
            btn.setObjectName("accent_alt")
        btn.clicked.connect(handler)
        return btn

    def _hbox(self, widgets):
        w = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        for item in widgets:
            layout.addWidget(item)
        layout.addStretch()
        return w
    def _build_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("File")
        file_menu.addAction("Open Project Folder", lambda: open_in_file_explorer(c.BASE_DIR))
        file_menu.addAction("Open Creations Folder", lambda: open_in_file_explorer(c.OUTPUTS_DIR))
        file_menu.addAction("Open Edit Bank", lambda: open_in_file_explorer(c.EDIT_BANK_DIR))
        file_menu.addAction("Open Source Videos Folder", self.open_video_folder)
        file_menu.addAction("Open Config Folder", lambda: open_in_file_explorer(c.CONFIG_DIR))
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        tools_menu = menu.addMenu("Tools")
        tools_menu.addAction("Advanced Settings", lambda: self.stack.setCurrentWidget(self.advanced_page))
        tools_menu.addAction("Open Settings File", self._open_settings_file)
        tools_menu.addAction("Reset Settings", self._reset_settings)
        tools_menu.addSeparator()
        tools_menu.addAction("Copy Report", self.copy_report)
        tools_menu.addAction("Clear Logs", self._clear_logs)

        help_menu = menu.addMenu("Help")
        help_menu.addAction("How to Use", self._show_how_to)
        help_menu.addAction("System Info", self._show_system_info)
        help_menu.addAction("About", self._show_about)

    def _open_settings_file(self):
        if not self.settings_path.exists():
            self._save_settings()
        open_in_file_explorer(self.settings_path)

    def _reset_settings(self):
        if QtWidgets.QMessageBox.question(self, "Reset Settings", "Reset all settings to defaults?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self.settings_path.exists():
            try:
                self.settings_path.unlink()
            except Exception:
                pass
        self._init_state()
        self._apply_settings_to_ui()
        self._save_settings()
        self._log("Settings reset to defaults.")

    def _show_how_to(self):
        QtWidgets.QMessageBox.information(
            self,
            "How to Use",
            "1) Choose a folder with at least five gameplay videos.\n"
            "2) Each output randomly uses five 5-second clips from five different videos.\n"
            "3) Click Start to create a 25s short, or Preview 5s.\n"
            "4) Songs and SFX are randomly selected from the built-in folders.\n"
            "5) Outputs save to the creations folder.\n"
            "Tip: Enable Auto create for continuous generation.",
        )

    def _show_about(self):
        QtWidgets.QMessageBox.information(self, c.APP_NAME, "Mashup Creator\nShorts generator for fast, punchy edits.")

    def _show_system_info(self):
        info = (
            f"Python: {os.sys.version.split()[0]}\n"
            f"CPU threads: {os.cpu_count()}\n"
            f"Base folder: {c.BASE_DIR}\n"
            f"Output folder: {c.OUTPUTS_DIR}\n"
            f"Config folder: {c.CONFIG_DIR}"
        )
        QtWidgets.QMessageBox.information(self, "System Info", info)

    def _load_settings(self):
        legacy = c.BASE_DIR / "settings.json"
        if legacy.exists() and not self.settings_path.exists():
            try:
                shutil.move(str(legacy), str(self.settings_path))
            except Exception:
                pass
        if not self.settings_path.exists():
            self._apply_settings_to_ui()
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            self._apply_settings_to_ui()
            return
        self.render_speed = data.get("render_speed", "ultrafast")
        self.downscale = bool(data.get("downscale", True))
        self.sfx_volume = float(data.get("sfx_volume", 1.35))
        self.batch_count = int(data.get("batch_count", 1))
        self.hw_encode = bool(data.get("hw_encode", False))
        self.auto_create = bool(data.get("auto_create", True))
        self.video_source_dir = str(data.get("video_source_dir", str(c.VIDEO_DIR)))
        self.include_video_subfolders = bool(data.get("include_video_subfolders", False))
        self._apply_settings_to_ui()

    def _save_settings(self, auto_create: Optional[bool] = None):
        c.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if auto_create is None:
            auto_create = self.chk_auto.isChecked() if hasattr(self, "chk_auto") else self.auto_create
        data = {
            "render_speed": self.render_speed,
            "downscale": self.downscale,
            "sfx_volume": self.sfx_volume,
            "batch_count": self.batch_count,
            "hw_encode": self.hw_encode,
            "auto_create": auto_create,
            "video_source_dir": self.video_source_dir,
            "include_video_subfolders": self.include_video_subfolders,
        }
        try:
            self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _apply_settings_to_ui(self):
        self.radio_fast.setChecked(self.render_speed == "veryfast")
        self.radio_ultra.setChecked(self.render_speed == "ultrafast")
        self.chk_downscale.setChecked(self.downscale)
        self.chk_hw.setChecked(self.hw_encode)
        self.spin_sfx.setValue(self.sfx_volume)
        self.spin_batch.setValue(self.batch_count)
        self.chk_auto.setChecked(self.auto_create)
        self.chk_include_subfolders.setChecked(self.include_video_subfolders)
        self._update_creation_mode_ui()

    def _update_creation_mode_ui(self):
        if not hasattr(self, "chk_auto"):
            return
        unlimited = self.chk_auto.isChecked()
        if hasattr(self, "spin_batch"):
            self.spin_batch.setEnabled(not unlimited)
        if hasattr(self, "batch_label"):
            self.batch_label.setEnabled(not unlimited)
        if hasattr(self, "mode_summary"):
            if unlimited:
                self.mode_summary.setText("Start will keep creating videos until Cancel or Pause is pressed.")
            else:
                count = self.spin_batch.value() if hasattr(self, "spin_batch") else self.batch_count
                self.mode_summary.setText(f"Start will create {count} video(s), then stop.")

    def _log(self, text: str):
        at_bottom = self.log_text.verticalScrollBar().value() >= self.log_text.verticalScrollBar().maximum()
        if self.log_messages and self.log_messages[-1].startswith("Done:") and text:
            self.log_messages.append("")
        self.log_messages.append(text)
        self.log_messages = self.log_messages[-18:]
        self.log_text.setPlainText("\n".join(self.log_messages))
        if at_bottom:
            self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def _log_error(self, text: str):
        at_bottom = self.log_text.verticalScrollBar().value() >= self.log_text.verticalScrollBar().maximum()
        entry = f"ERROR: {text}"
        if self.log_messages and self.log_messages[-1].startswith("Done:"):
            self.log_messages.append("")
        self.log_messages.append(entry)
        self.log_messages = self.log_messages[-18:]
        self.log_text.setPlainText("\n".join(self.log_messages))
        if at_bottom:
            self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def _clear_logs(self):
        self.log_messages = []
        self.error_messages = []
        self.log_text.clear()

    def _set_button_state(self, btn: QtWidgets.QPushButton, enabled: bool):
        btn.setEnabled(enabled)

    def _refresh_lists(self):
        self._update_counts()

    def _update_counts(self):
        source_folder = self._video_source_folder()
        videos = self._list_source_videos()
        auds = len(list_files(c.AUDIO_DIR, c.AUDIO_EXTS))
        sfxs = len(list_files(c.SFX_DIR, c.AUDIO_EXTS))

        folder_text = str(source_folder)
        metrics = QtGui.QFontMetrics(self.video_folder_label.font())
        label_width = max(320, self.video_folder_label.width())
        self.video_folder_label.setText(metrics.elidedText(folder_text, QtCore.Qt.TextElideMode.ElideMiddle, label_width))
        self.video_folder_label.setToolTip(folder_text)
        scope = "including subfolders" if self.include_video_subfolders else "selected folder only"
        self.video_count_lbl.setText(f"Source videos: {len(videos)}")
        self.video_count_lbl.setToolTip(scope)
        self.audio_count_lbl.setText(f"Built-in songs: {auds}")
        self.sfx_count_lbl.setText(f"Built-in SFX: {sfxs}")
        self._update_video_buttons()

    def _video_source_folder(self) -> Path:
        folder = Path(self.video_source_dir).expanduser()
        if not folder.is_absolute():
            folder = c.BASE_DIR / folder
        return folder

    def _list_source_videos(self) -> List[Path]:
        source_folder = self._video_source_folder()
        if not source_folder.exists():
            return []
        if self.include_video_subfolders:
            return sorted(
                p for p in source_folder.rglob("*") if p.is_file() and p.suffix.lower() in c.VIDEO_EXTS
            )
        return list_files(source_folder, c.VIDEO_EXTS)

    def _update_video_buttons(self):
        if not hasattr(self, "btn_choose_video_folder"):
            return
        videos = self._list_source_videos()
        songs = list_files(c.AUDIO_DIR, c.AUDIO_EXTS)
        sfxs = list_files(c.SFX_DIR, c.AUDIO_EXTS)
        is_busy = bool((self.worker_thread and self.worker_thread.isRunning()) or self.job_start_time is not None)
        ready = len(videos) >= c.MAX_SOURCE_VIDEOS and bool(songs) and bool(sfxs)
        self.btn_choose_video_folder.setEnabled(not is_busy)
        self.btn_open_video_folder.setEnabled(not is_busy)
        self.btn_refresh_sources.setEnabled(not is_busy)
        self.btn_start.setEnabled(ready and not is_busy)
        self.btn_preview.setEnabled(ready and not is_busy)

    def _on_include_subfolders_changed(self):
        self.include_video_subfolders = self.chk_include_subfolders.isChecked()
        self._save_settings()
        self._refresh_lists()

    def _tick_timer(self):
        if self.worker_thread and self.worker_thread.isRunning() and self.job_start_time:
            elapsed = max(0.0, time.monotonic() - self.job_start_time)
            if self.rendering and self.render_start_time is not None:
                render_elapsed = max(0.0, time.monotonic() - self.render_start_time)
                self.timer_label.setText(f"Render elapsed: {self._fmt_time(render_elapsed)}")
            else:
                self.timer_label.setText(f"Elapsed: {self._fmt_time(elapsed)}")
        else:
            self.timer_label.setText("Time: --:--")

    def _fmt_time(self, seconds: float) -> str:
        total = int(seconds + 0.5)
        mins = total // 60
        secs = total % 60
        return f"{mins:02d}:{secs:02d}"

    def choose_video_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose gameplay video folder",
            str(self._video_source_folder()),
        )
        if not folder:
            return
        self.video_source_dir = folder
        reply = QtWidgets.QMessageBox.question(
            self,
            "Include Subfolders?",
            "Use videos inside subfolders too?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        self.include_video_subfolders = reply == QtWidgets.QMessageBox.StandardButton.Yes
        self.chk_include_subfolders.setChecked(self.include_video_subfolders)
        self._save_settings()
        self._refresh_lists()
        scope = "including subfolders" if self.include_video_subfolders else "selected folder only"
        self._log(f"Video source folder: {folder} ({scope}).")

    def open_video_folder(self):
        folder = self._video_source_folder()
        folder.mkdir(parents=True, exist_ok=True)
        open_in_file_explorer(folder)

    def _validate_source_video(self, src: Path) -> Tuple[bool, str]:
        ok, msg = security.validate_media_file(src, "video", max_size_mb=65536)
        if not ok:
            return False, msg
        try:
            duration = probe_duration(src)
        except Exception as exc:
            return False, f"Could not read video duration: {exc}"
        if duration is None:
            return False, "Could not read video duration."
        if duration < c.MIN_SOURCE_SECONDS:
            return False, "Gameplay videos must be at least 5 seconds long."
        return True, "OK"

    def _collect_selections(self) -> Tuple[List[Path], List[Path], List[Path]]:
        all_vids = self._list_source_videos()
        all_auds = list_files(c.AUDIO_DIR, c.AUDIO_EXTS)
        all_sfxs = list_files(c.SFX_DIR, c.AUDIO_EXTS)
        return all_vids, all_auds, all_sfxs

    def start_creation(self):
        self._start_jobs(preview=False)

    def start_preview(self):
        self._start_jobs(preview=True)

    def _start_jobs(self, preview: bool):
        if self.worker_thread and self.worker_thread.isRunning():
            QtWidgets.QMessageBox.information(self, "Busy", "A creation is already running.")
            return

        self.render_speed = "veryfast" if self.radio_fast.isChecked() else "ultrafast"
        self.downscale = self.chk_downscale.isChecked()
        self.sfx_volume = self.spin_sfx.value()
        self.batch_count = self.spin_batch.value()
        self.hw_encode = self.chk_hw.isChecked()
        requested_auto_create = self.chk_auto.isChecked()
        self.auto_create = requested_auto_create and not preview
        self._save_settings(auto_create=requested_auto_create)

        vids, songs, sfxs = self._collect_selections()
        if len(vids) < c.MAX_SOURCE_VIDEOS:
            QtWidgets.QMessageBox.critical(
                self,
                "Not Enough Source Videos",
                f"Choose a folder with at least {c.MAX_SOURCE_VIDEOS} gameplay videos. "
                "Each output uses five different videos.",
            )
            return
        if not songs or not sfxs:
            QtWidgets.QMessageBox.critical(
                self,
                "Missing Built-in Media",
                "Built-in songs and SFX must exist in library/audio and library/sfx before creating a mashup.",
            )
            return

        target_w = 720 if self.downscale else 1080
        target_h = 1280 if self.downscale else 1920
        bitrate = "2000k" if self.downscale else "3500k"
        clip_len = 5.0 if preview else 25.0
        job_count = 1 if preview or self.auto_create else min(5, self.batch_count)

        jobs = []
        for _ in range(job_count):
            stamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S-%f")
            base_name = f"{c.APP_NAME.replace(' ', '_')}_{stamp}.mp4"
            out_file = c.OUTPUTS_DIR / base_name
            if out_file.exists():
                suffix = datetime.now().strftime("%f")
                out_file = c.OUTPUTS_DIR / f"{c.APP_NAME.replace(' ', '_')}_{stamp}_{suffix}.mp4"
            jobs.append(
                CreationJob(
                    video_paths=vids,
                    audio_paths=songs,
                    sfx_paths=sfxs,
                    out_file=out_file,
                    render_preset=self.render_speed,
                    target_w=target_w,
                    target_h=target_h,
                    video_bitrate=bitrate,
                    sfx_volume=self.sfx_volume,
                    clip_len=clip_len,
                    hw_encode=self.hw_encode,
                )
            )

        self.last_job_info = {
            "videos_selected": len(vids),
            "video_source_folder": str(self._video_source_folder()),
            "song_pool": len(songs),
            "sfx_count": len(sfxs),
            "render_preset": self.render_speed,
            "downscale": self.downscale,
            "resolution": f"{target_w}x{target_h}",
            "bitrate": bitrate,
            "sfx_volume": self.sfx_volume,
            "batch_count": len(jobs),
            "auto_create": self.auto_create,
            "preview": preview,
            "hw_encode": self.hw_encode,
        }

        self.latest_output_file = None
        self._set_button_state(self.btn_open_latest, False)
        self._set_button_state(self.btn_start, False)
        self._set_button_state(self.btn_preview, False)
        self._set_button_state(self.btn_pause, True)
        self._set_button_state(self.btn_cancel, True)
        self._set_button_state(self.btn_resume, False)
        self._set_button_state(self.btn_choose_video_folder, False)
        self._set_button_state(self.btn_open_video_folder, False)
        self._set_button_state(self.btn_refresh_sources, False)

        self.job_start_time = time.monotonic()
        self.render_start_time = None
        self.rendering = False
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Preparing render...")
        self._log("Preparing render...")

        self.worker_thread = QtCore.QThread()
        self.worker = RenderWorker()
        self.worker.moveToThread(self.worker_thread)
        self.batch_stop_flag.clear()

        self.worker.configure(jobs, self.auto_create, self.batch_stop_flag)
        self.worker.status.connect(self._on_status)
        self.worker.progress.connect(self._on_progress)
        self.worker.error.connect(self._on_error)
        self.worker.done.connect(self._on_done)
        self.worker_thread.finished.connect(self._on_thread_finished)

        self.worker_thread.started.connect(self.worker.run)
        QtCore.QTimer.singleShot(0, self.worker_thread.start)

    def pause_creation(self):
        running_batch = self.worker is not None and len(self.worker.jobs) > 1
        if self.auto_create or running_batch:
            self.batch_stop_flag.set()
            self.status_label.setText("Pause requested (will stop after current video).")
            self._set_button_state(self.btn_pause, False)
            return
        if self.worker:
            self.worker.pause()
        self._set_button_state(self.btn_pause, False)
        self._set_button_state(self.btn_resume, True)

    def resume_creation(self):
        if self.batch_stop_flag.is_set():
            self.status_label.setText("Batch pause queued; resume is not available.")
            return
        if self.worker:
            self.worker.resume()
        self._set_button_state(self.btn_pause, True)
        self._set_button_state(self.btn_resume, False)

    def cancel_creation(self):
        self.batch_stop_flag.set()
        self.latest_output_file = None
        if self.worker:
            self.worker.cancel()
        self.status_label.setText("Cancelling current render and deleting partial output...")
        self._set_button_state(self.btn_pause, False)
        self._set_button_state(self.btn_resume, False)
        self._set_button_state(self.btn_cancel, False)

    def _on_status(self, text: str):
        self.status_label.setText(text)
        self._log(text)
        if text.startswith("Checking FFmpeg") or text.startswith("Picking random scenes"):
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
        if text.startswith("Rendering output"):
            if not self.rendering:
                self.render_start_time = time.monotonic()
                self.progress.setRange(0, 100)
            self.rendering = True
        elif text.startswith("Done:") or text.startswith("Failed:"):
            if self.rendering and self.render_start_time is not None:
                self.render_start_time = None
            self.rendering = False
            self.progress.setRange(0, 100)

    def _on_progress(self, value: int):
        if self.progress.maximum() != 0:
            self.progress.setValue(value)

    def _on_error(self, msg: str):
        self.status_label.setText(f"Failed: {msg}")
        self._log_error(msg)
        QtWidgets.QMessageBox.critical(self, "Creation Failed", msg)
        self._cleanup_worker()

    def _on_done(self, path: str):
        self.latest_output_file = Path(path) if path else None
        self._set_button_state(self.btn_open_latest, True if self.latest_output_file else False)
        if self.latest_output_file:
            self.status_label.setText(f"Done: {self.latest_output_file.name}")
            self._log(f"Done: {self.latest_output_file}")
        self._cleanup_worker()

    def _cleanup_worker(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.cleanup_pending = True
            self.worker_thread.quit()
            return
        self._finalize_cleanup()

    def _on_thread_finished(self):
        if self.cleanup_pending:
            self.cleanup_pending = False
            self._finalize_cleanup()

    def _finalize_cleanup(self):
        self.worker_thread = None
        self.worker = None
        self._set_button_state(self.btn_start, True)
        self._set_button_state(self.btn_preview, True)
        self._set_button_state(self.btn_pause, False)
        self._set_button_state(self.btn_resume, False)
        self._set_button_state(self.btn_cancel, False)
        self.job_start_time = None
        self.render_start_time = None
        self.rendering = False
        self.progress.setRange(0, 100)
        self._refresh_lists()
        if self.close_requested:
            self.close_requested = False
            QtCore.QTimer.singleShot(0, self.close)

    def open_latest(self):
        if self.latest_output_file and self.latest_output_file.exists():
            open_in_file_explorer(self.latest_output_file)
        else:
            QtWidgets.QMessageBox.information(self, "No Latest Output", "No creation output file is available yet.")

    def copy_report(self):
        info_lines = [f"{k}: {v}" for k, v in self.last_job_info.items()]
        report = "\n".join(
            [
                f"{c.APP_NAME} Report",
                f"Time: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
                f"Output: {self.latest_output_file}" if self.latest_output_file else "Output: (none)",
                "",
                "Settings:",
                *info_lines,
                "",
                "Recent log:",
                self.log_text.toPlainText() or "(empty)",
            ]
        )
        QtGui.QGuiApplication.clipboard().setText(report)
        self._log("Report copied to clipboard.")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._save_settings()
        if self.worker_thread and self.worker_thread.isRunning():
            self.close_requested = True
            if self.worker:
                self.worker.cancel()
            self.status_label.setText("Closing after current render step stops...")
            self._set_button_state(self.btn_start, False)
            self._set_button_state(self.btn_preview, False)
            self._set_button_state(self.btn_pause, False)
            self._set_button_state(self.btn_resume, False)
            self._set_button_state(self.btn_cancel, False)
            event.ignore()
            return
        if self.worker:
            self.worker.cancel()
        event.accept()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.WindowStateChange:
            if self.rendering:
                self.progress.setRange(0, 0)
        super().changeEvent(event)

