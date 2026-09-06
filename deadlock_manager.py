"""
deadlock_manager.py
----------------------------------------------------------------------
MODE 3: DEADLOCK

This module intentionally creates a classic circular-wait deadlock
using the SAME two printer locks defined in printer_manager.py
(Printer A and Printer B), and then shows how to recover from it
safely.

THE DEADLOCK
    Thread 1:  acquire Printer A  -> wait -> try to acquire Printer B
    Thread 2:  acquire Printer B  -> wait -> try to acquire Printer A

Both threads end up waiting forever for a resource the other one is
holding. That is a deadlock.

WHY THIS WON'T FREEZE THE WHOLE APP
Real Python `Lock.acquire()` calls with no timeout could block a
thread forever. To keep the Streamlit server responsive we NEVER call
plain `acquire()` for the second (waiting) resource. Instead each
thread repeatedly tries `lock.acquire(timeout=0.5)` in a short loop
and checks a `threading.Event` ("cancel_event") between attempts. This
is a *cooperative cancellation* pattern:

    while not acquired and not cancel_event.is_set():
        acquired = lock.acquire(timeout=0.5)

Clicking "Resolve Deadlock" simply sets the Event for one of the two
threads. That thread notices the flag, gives up waiting, releases the
resource it was holding, and finishes as CANCELLED — which frees the
other thread to finish normally. Nothing is force-killed.

A safety timeout is also included so that even if nobody clicks
"Resolve", the demo will not hang forever.
----------------------------------------------------------------------
"""

import threading
import time

# How long (seconds) the demo will sit in a real deadlock before it
# auto-resolves itself, in case the presenter never clicks the button.
AUTO_RESOLVE_SECONDS = 25


class DeadlockManager:
    """Runs the two-thread circular-wait demonstration on top of a
    PrinterManager instance's Printer A / Printer B locks."""

    def __init__(self, printer_manager):
        self.pm = printer_manager
        self.active = False
        self.job_ids = []          # [job_id_thread1, job_id_thread2]
        self.cancel_events = {}    # job_id -> threading.Event

    # ------------------------------------------------------------------
    def trigger_deadlock(self):
        """Start the two special deadlock threads."""
        pm = self.pm
        if self.active:
            return  # already running, do nothing

        job1 = pm._next_job_id()
        job2 = pm._next_job_id()
        name1 = pm._next_thread_name()
        name2 = pm._next_thread_name()

        for job_id, thread_name, printer in ((job1, name1, "Printer A"), (job2, name2, "Printer B")):
            pm.jobs[job_id] = {
                "job_id": job_id, "user_name": "DeadlockDemo", "document": f"{thread_name}-Doc.pdf",
                "pages": 5, "printer": printer, "thread_id": thread_name,
                "status": "QUEUED", "created_time": pm._now(),
                "start_time": "", "end_time": "", "start_ts": None, "end_ts": None,
                "duration_sec": pm.job_duration, "held_resource": "", "requested_resource": "",
            }

        self.job_ids = [job1, job2]
        self.cancel_events = {job1: threading.Event(), job2: threading.Event()}
        self.active = True
        pm.deadlock_active = True
        pm.deadlock_thread_ids = [job1, job2]

        pm.log("Starting DEADLOCK demonstration with two threads")

        t1 = threading.Thread(
            target=self._deadlock_worker,
            args=(job1, "Printer A", "Printer B", self.cancel_events[job1]),
            name=name1, daemon=True,
        )
        t2 = threading.Thread(
            target=self._deadlock_worker,
            args=(job2, "Printer B", "Printer A", self.cancel_events[job2]),
            name=name2, daemon=True,
        )
        t1.start()
        # tiny stagger so thread 1 reliably grabs Printer A first in
        # the log, purely cosmetic for the classroom demo
        time.sleep(0.05)
        t2.start()

        # Safety net: if nobody resolves it manually, auto-resolve.
        watchdog = threading.Thread(target=self._watchdog, daemon=True)
        watchdog.start()

    # ------------------------------------------------------------------
    def _deadlock_worker(self, job_id, hold_printer, want_printer, cancel_event):
        pm = self.pm
        thread_name = pm.jobs[job_id]["thread_id"]
        hold_lock = pm.resources[hold_printer]["lock"]
        want_lock = pm.resources[want_printer]["lock"]

        # Step 1: acquire the first resource (always succeeds quickly)
        hold_lock.acquire()
        with pm.state_lock:
            pm.resources[hold_printer]["owner"] = thread_name
        pm._update_job(job_id, status="PRINTING", start_time=pm._now(), start_ts=time.time(),
                        held_resource=hold_printer)
        pm.log(f"{thread_name} acquired {hold_printer}")

        # Give the other thread time to also grab its first resource,
        # guaranteeing the circular wait actually happens.
        time.sleep(1.5)

        # Step 2: intentionally try to acquire the SECOND resource
        # (held by the other thread) -> this is where the deadlock forms
        pm._update_job(job_id, status="DEADLOCKED", requested_resource=want_printer)
        with pm.state_lock:
            pm.resources[want_printer]["requested_by"] = thread_name
        pm.log(f"{thread_name} is waiting for {want_printer} -> DEADLOCK forming")

        acquired = False
        while not acquired and not cancel_event.is_set():
            acquired = want_lock.acquire(timeout=0.5)

        if acquired:
            # We only get here if the OTHER thread was cancelled first
            # and released the resource we were waiting for.
            pm.log(f"{thread_name} finally acquired {want_printer} after the other thread backed off")
            time.sleep(1)
            want_lock.release()
            hold_lock.release()
            with pm.state_lock:
                pm.resources[hold_printer]["owner"] = None
                pm.resources[want_printer]["requested_by"] = None
            pm._update_job(job_id, status="COMPLETED", end_time=pm._now(), end_ts=time.time(),
                            held_resource="", requested_resource="")
            with pm.state_lock:
                pm.completed_count += 1
        else:
            # We were cancelled: cooperatively back off, release what
            # we hold, and stop. This is the "safe recovery" path.
            hold_lock.release()
            with pm.state_lock:
                pm.resources[hold_printer]["owner"] = None
                pm.resources[want_printer]["requested_by"] = None
            pm._update_job(job_id, status="CANCELLED", end_time=pm._now(), end_ts=time.time(),
                            held_resource="", requested_resource="")
            with pm.state_lock:
                pm.failed_count += 1
            pm.log(f"{thread_name} cancelled itself, released {hold_printer}")

        self._check_finished()

    # ------------------------------------------------------------------
    def resolve_deadlock(self, prefer_job_id=None):
        """Cooperatively cancel one of the two deadlocked threads so
        the other one can proceed. This does NOT force-kill anything;
        it just flips a threading.Event that the waiting thread is
        already watching for."""
        if not self.active or not self.job_ids:
            return "No active deadlock to resolve."

        pm = self.pm
        target = prefer_job_id if prefer_job_id in self.job_ids else self.job_ids[-1]
        other = [j for j in self.job_ids if j != target][0]

        pm.deadlock_count += 1
        pm.log(f"RESOLVE requested: cancelling {pm.jobs[target]['thread_id']}")
        self.cancel_events[target].set()

        return (f"{pm.jobs[target]['thread_id']} cancelled. Its printer will be released so "
                f"{pm.jobs[other]['thread_id']} can continue.")

    # ------------------------------------------------------------------
    def _watchdog(self):
        """Auto-resolve safety net so the demo never hangs forever if
        the presenter forgets to click the button."""
        time.sleep(AUTO_RESOLVE_SECONDS)
        if self.active:
            self.pm.log("Auto-resolving deadlock (safety timeout reached)")
            self.resolve_deadlock()

    def _check_finished(self):
        pm = self.pm
        if all(pm.jobs.get(j, {}).get("status") in ("COMPLETED", "CANCELLED") for j in self.job_ids):
            self.active = False
            pm.deadlock_active = False

    # ------------------------------------------------------------------
    def is_deadlocked(self):
        """True while both threads are actively stuck in circular wait."""
        pm = self.pm
        if not self.active or len(self.job_ids) < 2:
            return False
        statuses = [pm.jobs.get(j, {}).get("status") for j in self.job_ids]
        return all(s == "DEADLOCKED" for s in statuses)

    def get_status_snapshot(self):
        pm = self.pm
        return [pm.jobs[j] for j in self.job_ids if j in pm.jobs]
