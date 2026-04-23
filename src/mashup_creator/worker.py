import threading
import uuid
from dataclasses import replace
from datetime import datetime
from typing import List

from PyQt6 import QtCore

from .creator import Creator, CreationJob


class RenderWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    error = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.creator = Creator(self._emit_status, self._emit_progress)
        self.jobs: List[CreationJob] = []
        self.auto_create = False
        self.batch_stop_flag = threading.Event()

    def configure(self, jobs: List[CreationJob], auto_create: bool, batch_stop_flag: threading.Event):
        self.jobs = jobs
        self.auto_create = auto_create
        self.batch_stop_flag = batch_stop_flag

    def _emit_status(self, text: str):
        self.status.emit(text)

    def _emit_progress(self, value: int):
        self.progress.emit(value)

    @QtCore.pyqtSlot()
    def run(self):
        last_output = ""
        try:
            if not self.jobs:
                self.done.emit("")
                return

            idx = 0
            while True:
                if self.creator._cancel_event.is_set():
                    break
                if idx > 0 and self.batch_stop_flag.is_set():
                    break
                if not self.auto_create and idx >= len(self.jobs):
                    break
                job = self.jobs[idx % len(self.jobs)]
                if self.auto_create and idx > 0:
                    stamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S-%f")
                    suffix = uuid.uuid4().hex[:6]
                    out_name = f"{job.out_file.stem}_{stamp}_{suffix}{job.out_file.suffix}"
                    job = replace(job, out_file=job.out_file.parent / out_name)
                if self.auto_create:
                    self.status.emit(f"Auto create #{idx + 1} starting...")
                elif len(self.jobs) > 1:
                    self.status.emit(f"Batch {idx + 1}/{len(self.jobs)} starting...")
                self.creator.create(job)
                last_output = str(job.out_file)
                idx += 1
            if self.auto_create and not self.creator._cancel_event.is_set():
                self.status.emit("Auto create stopped (paused or cancelled).")
            elif len(self.jobs) > 1 and not self.creator._cancel_event.is_set():
                self.status.emit("Batch complete.")
            self.done.emit(last_output)
        except Exception as e:
            if str(e) == "Cancelled.":
                self.status.emit("Cancelled.")
                self.done.emit(last_output)
            else:
                self.error.emit(str(e))

    def pause(self):
        self.creator.pause()

    def resume(self):
        self.creator.resume()

    def cancel(self):
        self.creator.cancel()
