"""
csv_manager.py
----------------------------------------------------------------------
Handles all reading and writing of the two CSV "databases" used by
PrintSync:

    data/print_jobs.csv    -> one row per print job
    data/system_logs.csv   -> one row per timestamped event

WHY A DEDICATED LOCK?
Multiple worker threads (one per print job) can try to write to these
CSV files at the same time. If two threads write at the exact same
moment, the file can get corrupted (rows mixed together). To prevent
this, every write goes through `csv_lock`. This is the SAME
synchronization concept used for the printer itself (see
printer_manager.py) applied to a different shared resource: the CSV
file on disk.
----------------------------------------------------------------------
"""

import csv
import os
import threading
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
JOBS_CSV = os.path.join(DATA_DIR, "print_jobs.csv")
LOGS_CSV = os.path.join(DATA_DIR, "system_logs.csv")

JOB_FIELDS = [
    "job_id", "user_name", "document", "pages", "printer",
    "thread_id", "status", "created_time", "start_time", "end_time",
    "duration_sec", "held_resource", "requested_resource",
]
LOG_FIELDS = ["timestamp", "message"]

# A single lock shared by every thread that touches the CSV files.
# "with csv_lock:" guarantees only one thread is inside the critical
# section (reading/writing the file) at any given time.
csv_lock = threading.Lock()


def ensure_files():
    """Create the data folder and CSV files (with headers) if they
    do not already exist. Safe to call many times."""
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(JOBS_CSV):
        with csv_lock:
            with open(JOBS_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=JOB_FIELDS)
                writer.writeheader()

    if not os.path.exists(LOGS_CSV):
        with csv_lock:
            with open(LOGS_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                writer.writeheader()


def log_event(message: str):
    """Append one timestamped event to system_logs.csv.
    Protected by csv_lock because many threads log events concurrently.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    try:
        with csv_lock:
            with open(LOGS_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                writer.writerow({"timestamp": timestamp, "message": message})
    except OSError:
        # If the disk write fails we don't want to crash the whole
        # simulation - the in-memory log (kept in PrinterManager) is
        # still shown to the user.
        pass
    return f"{timestamp} — {message}"


def save_all_jobs(jobs_dict):
    """Re-write print_jobs.csv from scratch using the current
    in-memory jobs dictionary. Because job status changes over time
    (QUEUED -> PRINTING -> COMPLETED, etc.) it is simplest for a
    classroom demo to overwrite the whole file rather than patch
    individual rows. This whole operation is wrapped in csv_lock so a
    half-written file is never read by mistake.
    """
    try:
        with csv_lock:
            with open(JOBS_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=JOB_FIELDS)
                writer.writeheader()
                for job in jobs_dict.values():
                    row = {k: job.get(k, "") for k in JOB_FIELDS}
                    writer.writerow(row)
    except OSError:
        pass


def read_jobs():
    """Return all job rows from the CSV as a list of dicts."""
    ensure_files()
    with csv_lock:
        with open(JOBS_CSV, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def read_logs(limit=200):
    """Return the most recent `limit` log rows (newest first)."""
    ensure_files()
    with csv_lock:
        with open(LOGS_CSV, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return list(reversed(rows))[:limit]


def reset_data():
    """Wipe both CSV files back to just their header row."""
    with csv_lock:
        with open(JOBS_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=JOB_FIELDS).writeheader()
        with open(LOGS_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=LOG_FIELDS).writeheader()
