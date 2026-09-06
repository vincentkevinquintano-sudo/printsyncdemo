"""
printer_manager.py
----------------------------------------------------------------------
The heart of the PrintSync simulation.

This module defines `PrinterManager`, a single object shared by every
user of the hosted app. A module-level object (created once, at the
bottom of this file) survives every Streamlit script "rerun" because
Python only imports a module once per running process. This is what
lets Student A submit a job in one browser tab and Student B see it
appear in the Thread Monitor in a different browser tab: they are all
looking at the same PrinterManager instance.

CONCEPTS DEMONSTRATED HERE
---------------------------------------------------------------------
1. MULTITHREADING   -> every print job runs on its own threading.Thread
2. SYNCHRONIZATION  -> printer_lock (a threading.Lock) protects the
                        printer's "critical section" so only one
                        thread can use a given printer at a time
3. SHARED STATE     -> self.state_lock protects the in-memory
                        dictionaries that the Streamlit UI reads from,
                        since UI reads happen on the Streamlit "main"
                        thread while worker threads write concurrently
----------------------------------------------------------------------
"""

import threading
import time
from datetime import datetime

import csv_manager

# Default number of seconds each simulated print job takes. Using one
# fixed, short duration (instead of pages x speed) makes a live,
# multi-user demo predictable: no matter who submits a job or how many
# pages they type in, everyone waits the same, short amount of time —
# easy to see and easy to explain out loud.
DEFAULT_JOB_DURATION = 3

STATUS_QUEUED = "QUEUED"
STATUS_WAITING = "WAITING"
STATUS_PRINTING = "PRINTING"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
STATUS_DEADLOCKED = "DEADLOCKED"
STATUS_FAILED = "FAILED"


class PrinterManager:
    """Centralized, thread-safe simulation state for PrintSync."""

    def __init__(self):
        # ---- Shared resources (the actual printers) ----------------
        # Each printer has its own Lock plus some metadata describing
        # who currently owns it. The Lock is what actually enforces
        # "only one thread at a time"; the metadata is just for
        # display purposes in the Streamlit UI.
        self.resources = {
            "Printer A": {"lock": threading.Lock(), "owner": None, "requested_by": None},
            "Printer B": {"lock": threading.Lock(), "owner": None, "requested_by": None},
        }

        # Guards the dictionaries below (self.jobs, counters, logs)
        # so the Streamlit "reader" thread and the worker "writer"
        # threads never corrupt each other's view of the data.
        self.state_lock = threading.RLock()

        self.jobs = {}          # job_id -> job dict
        self.job_counter = 0
        self.thread_counter = 0
        self.completed_count = 0
        self.failed_count = 0
        self.deadlock_count = 0

        # Each log entry gets an ever-increasing sequence number so
        # every connected browser can ask "what happened since the
        # last time I checked?" and get exactly the new events —
        # this is what powers the cross-user toast notifications.
        self.memory_logs = []   # list of {"seq", "time", "message"}
        self.log_seq = 0

        self.running = True     # False = "Stop Simulation" was pressed
        self.job_duration = DEFAULT_JOB_DURATION  # seconds per print job

        # Deadlock-mode specific state
        self.deadlock_active = False
        self.deadlock_thread_ids = []      # the two threads involved
        self.deadlock_cancel_events = {}   # thread_id -> threading.Event

        csv_manager.ensure_files()

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def _now(self):
        return datetime.now().strftime("%H:%M:%S")

    def log(self, message: str):
        """Write an event to both the in-memory log (fast, for the UI)
        and the CSV file (persistent, for the record). Every entry
        gets a sequence number so the UI can detect and notify about
        NEW events since the last time it checked."""
        text = csv_manager.log_event(message)
        with self.state_lock:
            self.log_seq += 1
            self.memory_logs.append({"seq": self.log_seq, "time": self._now(), "message": message, "text": text})
            self.memory_logs = self.memory_logs[-300:]

    def _next_job_id(self):
        with self.state_lock:
            self.job_counter += 1
            return f"JOB-{self.job_counter:04d}"

    def _next_thread_name(self):
        with self.state_lock:
            self.thread_counter += 1
            return f"Thread-{self.thread_counter}"

    def _update_job(self, job_id, **fields):
        with self.state_lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(fields)
                csv_manager.save_all_jobs(self.jobs)

    # ------------------------------------------------------------------
    # Public read-only accessors (safe to call from the Streamlit UI)
    # ------------------------------------------------------------------
    def get_jobs(self):
        with self.state_lock:
            # Return newest jobs first for a nicer table
            return list(sorted(self.jobs.values(), key=lambda j: j["job_id"], reverse=True))

    def get_stats(self):
        with self.state_lock:
            active = sum(1 for j in self.jobs.values() if j["status"] == STATUS_PRINTING)
            waiting = sum(1 for j in self.jobs.values() if j["status"] in (STATUS_WAITING, STATUS_QUEUED))
            completed = sum(1 for j in self.jobs.values() if j["status"] == STATUS_COMPLETED)
            failed = sum(1 for j in self.jobs.values() if j["status"] in (STATUS_CANCELLED, STATUS_FAILED))
            return {
                "active_threads": active,
                "waiting_threads": waiting,
                "completed_jobs": completed,
                "failed_jobs": failed,
                "deadlocks": self.deadlock_count,
            }

    def get_resource_status(self):
        with self.state_lock:
            out = {}
            for name, r in self.resources.items():
                out[name] = {
                    "locked": r["lock"].locked(),
                    "owner": r["owner"],
                    "requested_by": r["requested_by"],
                }
            return out

    def get_logs(self, limit=40):
        with self.state_lock:
            return [e["text"] for e in reversed(self.memory_logs)][:limit]

    def latest_seq(self):
        with self.state_lock:
            return self.log_seq

    def get_events_since(self, seq):
        """Return every log entry with a sequence number greater than
        `seq`, oldest first. Used to show toast notifications to a
        browser for events it hasn't seen yet — including ones caused
        by a completely different user."""
        with self.state_lock:
            return [e for e in self.memory_logs if e["seq"] > seq]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_job_input(self, user_name, document, pages):
        if not self.running:
            return "Simulation is stopped. Press 'Start Simulation' first."
        if not user_name or not user_name.strip():
            return "Please enter a username."
        if not document or not document.strip():
            return "Please enter a document name."
        try:
            pages_int = int(pages)
            if pages_int <= 0:
                return "Number of pages must be a positive number."
        except (TypeError, ValueError):
            return "Number of pages must be a valid whole number."
        return None

    # ------------------------------------------------------------------
    # MODE 1: MULTITHREADING
    # Every job simply runs on its own thread and sleeps to simulate
    # printing. No shared lock is used here on purpose: this mode's
    # whole point is to show several threads making progress at the
    # same time, independent of each other.
    # ------------------------------------------------------------------
    def submit_multithreaded_job(self, user_name, document, pages, printer):
        job_id = self._next_job_id()
        thread_name = self._next_thread_name()
        duration = self.job_duration  # snapshot now, so later slider changes don't retroactively change this job
        job = {
            "job_id": job_id, "user_name": user_name, "document": document,
            "pages": pages, "printer": printer, "thread_id": thread_name,
            "status": STATUS_QUEUED, "created_time": self._now(),
            "start_time": "", "end_time": "", "start_ts": None, "end_ts": None,
            "duration_sec": duration, "held_resource": "", "requested_resource": "",
        }
        with self.state_lock:
            self.jobs[job_id] = job
        csv_manager.save_all_jobs(self.jobs)
        self.log(f"User {user_name} submitted {document} as {job_id}")

        t = threading.Thread(
            target=self._multithread_worker, args=(job_id,), name=thread_name, daemon=True
        )
        self.log(f"{thread_name} created for {job_id}")
        t.start()
        return job_id

    def _multithread_worker(self, job_id):
        job = self.jobs[job_id]
        thread_name = job["thread_id"]
        duration = job["duration_sec"]
        self._update_job(job_id, status=STATUS_PRINTING, start_time=self._now(), start_ts=time.time())
        self.log(f"{thread_name} started printing {job['document']} for {job['user_name']} "
                 f"on {job['printer']} — {duration}s (no shared lock)")

        time.sleep(duration)

        self._update_job(job_id, status=STATUS_COMPLETED, end_time=self._now(), end_ts=time.time())
        with self.state_lock:
            self.completed_count += 1
        self.log(f"{thread_name} completed {job_id} ({job['document']}) in {duration}s")

    # ------------------------------------------------------------------
    # MODE 2: SYNCHRONIZATION
    # Jobs targeting the same printer must take turns because they
    # share one threading.Lock. This is the "critical section" pattern:
    #
    #     with printer_lock:
    #         # only one thread at a time gets past this line
    #         ... simulate printing ...
    # ------------------------------------------------------------------
    def submit_synchronized_job(self, user_name, document, pages, printer):
        job_id = self._next_job_id()
        thread_name = self._next_thread_name()
        duration = self.job_duration
        job = {
            "job_id": job_id, "user_name": user_name, "document": document,
            "pages": pages, "printer": printer, "thread_id": thread_name,
            "status": STATUS_QUEUED, "created_time": self._now(),
            "start_time": "", "end_time": "", "start_ts": None, "end_ts": None,
            "duration_sec": duration, "held_resource": "",
            "requested_resource": printer,
        }
        with self.state_lock:
            self.jobs[job_id] = job
        csv_manager.save_all_jobs(self.jobs)
        self.log(f"User {user_name} submitted {document} as {job_id} (targeting {printer})")

        t = threading.Thread(
            target=self._sync_worker, args=(job_id, printer), name=thread_name, daemon=True
        )
        t.start()
        return job_id

    def _sync_worker(self, job_id, printer):
        job = self.jobs[job_id]
        thread_name = job["thread_id"]
        duration = job["duration_sec"]
        lock = self.resources[printer]["lock"]

        self._update_job(job_id, status=STATUS_WAITING)
        if lock.locked():
            self.log(f"{thread_name} ({job['user_name']}) is waiting for {printer} — busy")

        # --- CRITICAL SECTION ------------------------------------------------
        with lock:  # only one thread may be inside this block per printer
            with self.state_lock:
                self.resources[printer]["owner"] = thread_name
            self._update_job(job_id, status=STATUS_PRINTING, start_time=self._now(),
                              start_ts=time.time(), held_resource=printer, requested_resource="")
            self.log(f"{thread_name} acquired {printer} — {job['user_name']} printing "
                      f"{job['document']} for {duration}s")

            time.sleep(duration)

            self.log(f"{thread_name} finished, releasing {printer} after {duration}s")
        # --- END CRITICAL SECTION --------------------------------------------

        with self.state_lock:
            self.resources[printer]["owner"] = None
        self._update_job(job_id, status=STATUS_COMPLETED, end_time=self._now(),
                          end_ts=time.time(), held_resource="")
        with self.state_lock:
            self.completed_count += 1

    # ------------------------------------------------------------------
    # Demonstration helpers
    # ------------------------------------------------------------------
    def generate_test_users(self, mode, speed=None):
        sample = [
            ("Alice", "Report.pdf", 5, "Printer A"),
            ("Bob", "Assignment.pdf", 8, "Printer B"),
            ("Charlie", "Research.pdf", 10, "Printer A"),
        ]
        ids = []
        for user, doc, pages, printer in sample:
            if mode == "Synchronization":
                ids.append(self.submit_synchronized_job(user, doc, pages, printer))
            else:
                ids.append(self.submit_multithreaded_job(user, doc, pages, printer))
        return ids

    # ------------------------------------------------------------------
    # System controls
    # ------------------------------------------------------------------
    def start_simulation(self):
        self.running = True
        self.log("Simulation STARTED")

    def stop_simulation(self):
        self.running = False
        self.log("Simulation STOPPED (no new jobs will be accepted)")

    def reset_simulation(self, clear_csv=True):
        """Cooperative reset. We do not force-kill any running
        threads (unsafe); instead we simply forget about them and
        create fresh Lock objects. Any straggling daemon thread will
        finish naturally in the background and has no effect once the
        UI no longer references it."""
        with self.state_lock:
            self.jobs = {}
            self.job_counter = 0
            self.thread_counter = 0
            self.completed_count = 0
            self.failed_count = 0
            self.deadlock_count = 0
            self.memory_logs = []
            self.log_seq = 0
            self.running = True
            self.deadlock_active = False
            self.deadlock_thread_ids = []
            self.deadlock_cancel_events = {}
            self.resources = {
                "Printer A": {"lock": threading.Lock(), "owner": None, "requested_by": None},
                "Printer B": {"lock": threading.Lock(), "owner": None, "requested_by": None},
            }
        if clear_csv:
            csv_manager.reset_data()
        self.log("Simulation RESET — all jobs, threads and locks cleared")


# NOTE: the single shared instance of this class is created in app.py
# using `@st.cache_resource`, which is Streamlit's officially supported
# way to share one Python object across every connected user. That is
# what makes PrintSync a true multi-user app instead of one simulation
# per browser tab.
