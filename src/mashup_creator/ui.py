
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
from .utils import list_files, probe_duration, safe_copy_into_library, open_in_file_explorer


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
        self.resize(1200, 820)
        self.setMinimumSize(1200, 820)
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
        self.render_speed = "veryfast"
        self.downscale = False
        self.sfx_volume = 1.35
        self.batch_count = 1
        self.hw_encode = False
        self.auto_create = True

    def _theme(self) -> str:
        return """
        QMainWindow { background: #7b4dff; }
        QWidget { font-size: 13px; }
        QLabel { color: #ffffff; font-weight: 600; }
        QGroupBox QLabel { color: #1d1733; font-weight: 600; }
        QGroupBox QCheckBox, QGroupBox QRadioButton { color: #1d1733; font-weight: 600; }
        QGroupBox { color: #1d1733; background: #ffffff; border: 2px solid #e0d5ff; border-radius: 14px; margin-top: 16px; }
        QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; font-size: 15px; font-weight: 800; }
        QListWidget, QTextEdit { background: #ffffff; color: #1d1733; border: 2px solid #e0d5ff; border-radius: 12px; }
        QProgressBar { border: 2px solid #e0d5ff; border-radius: 10px; text-align: center; background: #ffffff; min-height: 12px; max-height: 12px; }
        QProgressBar::chunk { background-color: #2fbf71; border-radius: 10px; }
        QPushButton { background: #ffffff; color: #1d1733; border: 2px solid #e0d5ff; border-radius: 18px; padding: 10px 16px; font-weight: 700; }
        QPushButton:hover { background: #f3ebff; }
        QPushButton#accent { background: #7b4dff; color: #ffffff; }
        QPushButton#accent:hover { background: #5a35cc; }
        QPushButton#accent_alt { background: #ff6fb1; color: #ffffff; }
        QPushButton#accent_alt:hover { background: #e6589a; }
        QSpinBox, QDoubleSpinBox { background: #ffffff; color: #1d1733; border: 2px solid #e0d5ff; border-radius: 10px; padding: 6px 8px; }
        QMenuBar { background: #6d42e8; color: #ffffff; }
        QMenuBar::item:selected { background: #5a35cc; }
        QMenu { background: #ffffff; color: #1d1733; border: 1px solid #e0d5ff; }
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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QtWidgets.QFrame()
        header.setStyleSheet("background: #7b4dff; border-radius: 16px;")
        header_layout = QtWidgets.QVBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 16, 16)

        title_label = QtWidgets.QLabel()
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        if c.TITLE_IMAGE_PATH.exists():
            pix = QtGui.QPixmap(str(c.TITLE_IMAGE_PATH))
            if not pix.isNull():
                scaled = pix.scaled(
                    760,
                    160,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                title_label.setPixmap(scaled)
            else:
                title_label.setText(c.APP_NAME)
        else:
            title_label.setText(c.APP_NAME)
            title_label.setStyleSheet("font-size: 36px; font-weight: 800;")
        header_layout.addWidget(title_label)

        subtitle = QtWidgets.QLabel("Quick, punchy shorts with cinematic motion")
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #efe9ff; font-size: 12px; font-weight: 600;")
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
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(8, 8, 8, 8)

        media_box = QtWidgets.QGroupBox("Gameplay Sources")
        media_layout = QtWidgets.QVBoxLayout(media_box)
        upload_row = QtWidgets.QHBoxLayout()
        self.btn_upload_video = self._btn("Add Video(s)", self.upload_videos)
        self.btn_replace_video = self._btn("Replace Selected", self.replace_selected_video)
        self.btn_remove_video = self._btn("Remove Selected", self.remove_selected_video)
        self.btn_open_video_folder = self._btn("Open Source Folder", lambda: open_in_file_explorer(c.VIDEO_DIR))
        upload_row.addWidget(self.btn_upload_video)
        upload_row.addWidget(self.btn_replace_video)
        upload_row.addWidget(self.btn_remove_video)
        upload_row.addWidget(self.btn_open_video_folder)
        upload_row.addStretch()
        media_layout.addLayout(upload_row)

        self.video_list = QtWidgets.QListWidget()
        self.video_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.video_list.itemSelectionChanged.connect(self._update_video_buttons)
        media_layout.addWidget(self.video_list)

        self.video_count_lbl = QtWidgets.QLabel("Gameplay videos: 0/5")
        self.audio_count_lbl = QtWidgets.QLabel("Built-in songs: 0")
        self.sfx_count_lbl = QtWidgets.QLabel("Built-in SFX: 0")
        counts_row = QtWidgets.QHBoxLayout()
        counts_row.addWidget(self.video_count_lbl)
        counts_row.addWidget(self.audio_count_lbl)
        counts_row.addWidget(self.sfx_count_lbl)
        counts_row.addStretch()
        media_layout.addLayout(counts_row)
        main_layout.addWidget(media_box)

        action_row = QtWidgets.QHBoxLayout()
        create_box = QtWidgets.QGroupBox("Create")
        create_layout = QtWidgets.QHBoxLayout(create_box)
        self.btn_start = self._btn("Start", self.start_creation, accent=True)
        self.btn_preview = self._btn("Preview 5s", self.start_preview, accent_alt=True)
        self.btn_pause = self._btn("Pause", self.pause_creation)
        self.btn_resume = self._btn("Resume", self.resume_creation)
        self.btn_cancel = self._btn("Cancel", self.cancel_creation, accent_alt=True)
        for b in [self.btn_start, self.btn_preview, self.btn_pause, self.btn_resume, self.btn_cancel]:
            create_layout.addWidget(b)
        action_row.addWidget(create_box, 2)

        output_box = QtWidgets.QGroupBox("Output")
        output_layout = QtWidgets.QHBoxLayout(output_box)
        self.btn_open_creations = self._btn("Open Creations", lambda: open_in_file_explorer(c.OUTPUTS_DIR))
        self.btn_open_latest = self._btn("Open Latest", self.open_latest)
        self.btn_copy_report = self._btn("Copy Report", self.copy_report)
        for b in [self.btn_open_creations, self.btn_open_latest, self.btn_copy_report]:
            output_layout.addWidget(b)
        action_row.addWidget(output_box, 2)

        self.btn_advanced = self._btn("Advanced Settings", lambda: self.stack.setCurrentWidget(self.advanced_page))
        action_row.addWidget(self.btn_advanced, 1)
        main_layout.addLayout(action_row)

        status_box = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout(status_box)
        status_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Ready.")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.progress, 2)
        status_layout.addLayout(status_row)
        self.timer_label = QtWidgets.QLabel("Time: --:--")
        status_layout.addWidget(self.timer_label)
        main_layout.addWidget(status_box)

        logs_box = QtWidgets.QGroupBox("Details")
        logs_layout = QtWidgets.QVBoxLayout(logs_box)
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        logs_layout.addWidget(self.log_text)
        main_layout.addWidget(logs_box, 1)

        note = QtWidgets.QLabel(
            "Output: 25s (preview 5s). Add exactly five gameplay videos, 5 minutes to 1 hour each. "
            "Songs and SFX are randomly selected from the built-in library."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #efe9ff; font-size: 10px;")
        main_layout.addWidget(note)

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

        batch = QtWidgets.QGroupBox("Batch / Auto")
        b_layout = QtWidgets.QFormLayout(batch)
        b_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        b_layout.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        b_layout.setHorizontalSpacing(12)
        b_layout.setVerticalSpacing(8)
        self.spin_batch = QtWidgets.QSpinBox()
        self.spin_batch.setRange(1, 5)
        b_layout.addRow("Videos to create", self.spin_batch)
        self.chk_auto = QtWidgets.QCheckBox("Auto create until paused or cancelled")
        b_layout.addRow(self.chk_auto)
        grid.addWidget(batch, 1, 0)

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
        file_menu.addAction("Open Source Videos Folder", lambda: open_in_file_explorer(c.VIDEO_DIR))
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
            "1) Add exactly five gameplay videos.\n"
            "2) Use Replace Selected or Remove Selected to manage the five slots.\n"
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
        self.render_speed = data.get("render_speed", "veryfast")
        self.downscale = bool(data.get("downscale", False))
        self.sfx_volume = float(data.get("sfx_volume", 1.35))
        self.batch_count = int(data.get("batch_count", 1))
        self.hw_encode = bool(data.get("hw_encode", False))
        self.auto_create = bool(data.get("auto_create", True))
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

    def _log(self, text: str):
        at_bottom = self.log_text.verticalScrollBar().value() >= self.log_text.verticalScrollBar().maximum()
        self.log_messages.append(text)
        self.log_messages = self.log_messages[-12:]
        self.log_text.setPlainText("\n".join(self.log_messages))
        if at_bottom:
            self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def _log_error(self, text: str):
        at_bottom = self.log_text.verticalScrollBar().value() >= self.log_text.verticalScrollBar().maximum()
        entry = f"ERROR: {text}"
        self.log_messages.append(entry)
        self.log_messages = self.log_messages[-12:]
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
        videos = list_files(c.VIDEO_DIR, c.VIDEO_EXTS)
        auds = len(list_files(c.AUDIO_DIR, c.AUDIO_EXTS))
        sfxs = len(list_files(c.SFX_DIR, c.AUDIO_EXTS))

        selected = self._selected_video_path()
        self.video_list.clear()
        for idx, path in enumerate(videos, start=1):
            item = QtWidgets.QListWidgetItem(f"{idx}. {path.name}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.video_list.addItem(item)
            if selected and selected == path:
                self.video_list.setCurrentItem(item)

        self.video_count_lbl.setText(f"Gameplay videos: {len(videos)}/{c.MAX_SOURCE_VIDEOS}")
        self.audio_count_lbl.setText(f"Built-in songs: {auds}")
        self.sfx_count_lbl.setText(f"Built-in SFX: {sfxs}")
        self._update_video_buttons()

    def _selected_video_path(self) -> Optional[Path]:
        if not hasattr(self, "video_list"):
            return None
        item = self.video_list.currentItem()
        if not item:
            return None
        value = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return Path(value) if value else None

    def _update_video_buttons(self):
        if not hasattr(self, "btn_upload_video"):
            return
        videos = list_files(c.VIDEO_DIR, c.VIDEO_EXTS)
        songs = list_files(c.AUDIO_DIR, c.AUDIO_EXTS)
        sfxs = list_files(c.SFX_DIR, c.AUDIO_EXTS)
        has_selection = self._selected_video_path() is not None
        is_busy = bool((self.worker_thread and self.worker_thread.isRunning()) or self.job_start_time is not None)
        ready = len(videos) == c.MAX_SOURCE_VIDEOS and bool(songs) and bool(sfxs)
        self.btn_upload_video.setEnabled((len(videos) < c.MAX_SOURCE_VIDEOS) and not is_busy)
        self.btn_replace_video.setEnabled(has_selection and not is_busy)
        self.btn_remove_video.setEnabled(has_selection and not is_busy)
        self.btn_open_video_folder.setEnabled(not is_busy)
        self.btn_start.setEnabled(ready and not is_busy)
        self.btn_preview.setEnabled(ready and not is_busy)

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

    def upload_videos(self):
        existing = list_files(c.VIDEO_DIR, c.VIDEO_EXTS)
        remaining = c.MAX_SOURCE_VIDEOS - len(existing)
        if remaining <= 0:
            QtWidgets.QMessageBox.information(
                self,
                "Five Videos Already Added",
                "Remove or replace a gameplay video before adding another one.",
            )
            return

        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Select gameplay video file(s)")
        if not paths:
            return
        copied = 0
        skipped = 0
        for s in paths[:remaining]:
            src = Path(s)
            ok, msg = self._validate_source_video(src)
            if ok:
                safe_copy_into_library(src, c.VIDEO_DIR)
                copied += 1
            else:
                skipped += 1
                self._log_error(f"{src.name}: {msg}")
        if len(paths) > remaining:
            skipped += len(paths) - remaining
            self._log_error(f"Only {remaining} slot(s) were available.")
        self._refresh_lists()
        self._log(f"Added {copied} gameplay video(s).")
        if skipped:
            self._log_error(f"Skipped {skipped} video file(s).")

    def replace_selected_video(self):
        selected = self._selected_video_path()
        if not selected:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select replacement gameplay video")
        if not path:
            return
        src = Path(path)
        if src.resolve() == selected.resolve():
            self._log("Selected replacement is already in that slot.")
            return

        ok, msg = self._validate_source_video(src)
        if not ok:
            self._log_error(f"{src.name}: {msg}")
            QtWidgets.QMessageBox.critical(self, "Invalid Video", msg)
            return

        new_path = safe_copy_into_library(src, c.VIDEO_DIR)
        try:
            selected.unlink()
        except Exception as exc:
            self._log_error(f"Could not remove old video: {exc}")
        self._refresh_lists()
        self._log(f"Replaced {selected.name} with {new_path.name}.")

    def remove_selected_video(self):
        selected = self._selected_video_path()
        if not selected:
            return
        if QtWidgets.QMessageBox.question(
            self,
            "Remove Video",
            f"Remove {selected.name} from the five gameplay sources?",
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            selected.unlink()
            self._log(f"Removed {selected.name}.")
        except Exception as exc:
            self._log_error(f"Could not remove video: {exc}")
        self._refresh_lists()

    def _validate_source_video(self, src: Path) -> Tuple[bool, str]:
        ok, msg = security.validate_media_file(src, "video", max_size_mb=65536)
        if not ok:
            return False, msg
        try:
            duration = probe_duration(src)
        except Exception as exc:
            return False, f"Could not read duration with ffprobe: {exc}"
        if duration is None:
            return False, "Could not read duration with ffprobe."
        if duration < c.MIN_SOURCE_SECONDS:
            return False, "Gameplay videos must be at least 5 minutes long."
        if duration > c.MAX_SOURCE_SECONDS:
            return False, "Gameplay videos must be no longer than 1 hour."
        return True, "OK"

    def _collect_selections(self) -> Tuple[List[Path], List[Path], List[Path]]:
        all_vids = list_files(c.VIDEO_DIR, c.VIDEO_EXTS)
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
        if len(vids) != c.MAX_SOURCE_VIDEOS:
            QtWidgets.QMessageBox.critical(
                self,
                "Five Videos Required",
                f"Add exactly {c.MAX_SOURCE_VIDEOS} gameplay videos before creating a mashup.",
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
        bitrate = "3000k" if self.downscale else "5000k"
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
        self._set_button_state(self.btn_upload_video, False)
        self._set_button_state(self.btn_replace_video, False)
        self._set_button_state(self.btn_remove_video, False)
        self._set_button_state(self.btn_open_video_folder, False)

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
        if self.worker:
            self.worker.cancel()
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

