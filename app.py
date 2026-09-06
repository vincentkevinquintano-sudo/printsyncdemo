"""
app.py
----------------------------------------------------------------------
PrintSync — Multi-User Printer Simulation System
Streamlit front-end. This file only handles DISPLAY and USER INPUT.
All real threading / locking / deadlock logic lives in
printer_manager.py and deadlock_manager.py.

SIMPLE-DEMO + MULTI-USER NOTES
- A simple tab layout (Multithreading / Synchronization / Deadlock)
  keeps the screen focused on one concept at a time for a live demo.
- `@st.cache_resource` creates the shared PrinterManager / DeadlockManager
  ONE time for the whole app, no matter how many browser tabs connect.
  Every visitor reads and writes the SAME simulation state.
- The live-updating parts of the page (metrics, printers, thread table,
  log) live inside `st.fragment(run_every=...)`. Only that small piece
  of the page re-executes every tick — the rest of the app (sidebar,
  forms) is untouched. This is what lets many people watch the
  dashboard at once without each of them re-running the whole script
  every second.
----------------------------------------------------------------------
"""

import time

import streamlit as st

from printer_manager import PrinterManager
from deadlock_manager import DeadlockManager

st.set_page_config(page_title="PrintSync", page_icon="🖨️", layout="wide")


# ----------------------------------------------------------------------
# Shared state — created ONCE for every user of the deployed app.
# ----------------------------------------------------------------------
@st.cache_resource
def get_manager():
    return PrinterManager()


@st.cache_resource
def get_deadlock_manager(_manager):
    return DeadlockManager(_manager)


manager = get_manager()
dl_manager = get_deadlock_manager(manager)


# ----------------------------------------------------------------------
# SIDEBAR — controls only, kept short on purpose
# ----------------------------------------------------------------------
with st.sidebar:
    st.title("🖨️ PrintSync")
    st.caption("Multithreading • Synchronization • Deadlock")

    st.subheader("Controls")
    c1, c2 = st.columns(2)
    if c1.button("▶ Start", use_container_width=True):
        manager.start_simulation()
    if c2.button("⏸ Stop", use_container_width=True):
        manager.stop_simulation()
    if st.button("🔄 Reset Everything", use_container_width=True):
        manager.reset_simulation()
        st.rerun()

    manager.job_duration = st.number_input(
        "Print duration (seconds)", min_value=1, max_value=15, value=manager.job_duration, step=1,
        help="Every job takes exactly this long, so it's predictable when several users print at once.",
    )

    st.caption("🟢 Running" if manager.running else "🔴 Stopped")

    st.divider()
    st.checkbox("🔔 Notify me about other users' activity", value=True, key="notif_enabled")


# ----------------------------------------------------------------------
# HEADER
# ----------------------------------------------------------------------
st.title("PrintSync")
st.caption("A live printer simulation for teaching multithreading, synchronization, and deadlock.")

tab_multi, tab_sync, tab_deadlock = st.tabs(
    ["🧵 Multithreading", "🔒 Synchronization", "⚠️ Deadlock"]
)

# ----------------------------------------------------------------------
# TAB 1: MULTITHREADING
# ----------------------------------------------------------------------
with tab_multi:
    st.info(f"Each print job runs on its **own thread**, independently, and takes **{manager.job_duration}s**. "
             "Nothing forces them to wait for each other.")
    left, right = st.columns([1, 1])

    with left:
        with st.form("multi_form", clear_on_submit=True):
            user_name = st.text_input("User Name", placeholder="e.g. Vincent", key="m_user")
            document = st.text_input("Document", placeholder="e.g. Thesis.pdf", key="m_doc")
            pages = st.number_input("Pages", min_value=1, max_value=200, value=5, key="m_pages")
            printer = st.selectbox("Printer", ["Printer A", "Printer B"], key="m_printer")
            go = st.form_submit_button("🖨️ Submit Print Job", type="primary")
        if go:
            err = manager.validate_job_input(user_name, document, pages)
            if err:
                st.warning(f"⚠ {err}")
            else:
                jid = manager.submit_multithreaded_job(user_name, document, pages, printer)
                st.success(f"{jid} started on a new thread!")

    with right:
        st.write("Or skip the form:")
        if st.button("🎓 Generate 3 Test Jobs", use_container_width=True, key="m_gen"):
            manager.generate_test_users("Multithreading")
            st.rerun()

# ----------------------------------------------------------------------
# TAB 2: SYNCHRONIZATION
# ----------------------------------------------------------------------
with tab_sync:
    st.info(f"All jobs sent to the **same printer** share one `threading.Lock`. Each one takes **{manager.job_duration}s** "
             "and only one prints at a time — the rest wait their turn.")
    left, right = st.columns([1, 1])

    with left:
        with st.form("sync_form", clear_on_submit=True):
            user_name = st.text_input("User Name", placeholder="e.g. Vincent", key="s_user")
            document = st.text_input("Document", placeholder="e.g. Thesis.pdf", key="s_doc")
            pages = st.number_input("Pages", min_value=1, max_value=200, value=5, key="s_pages")
            printer = st.selectbox("Printer", ["Printer A", "Printer B"], key="s_printer")
            go = st.form_submit_button("🖨️ Submit Print Job", type="primary")
        if go:
            err = manager.validate_job_input(user_name, document, pages)
            if err:
                st.warning(f"⚠ {err}")
            else:
                jid = manager.submit_synchronized_job(user_name, document, pages, printer)
                st.success(f"{jid} started — it will wait if the printer is busy.")

    with right:
        st.write("Tip: submit 3 jobs to the **same printer** to see the queue form.")
        if st.button("🎓 Generate 3 Test Jobs (same printer)", use_container_width=True, key="s_gen"):
            manager.generate_test_users("Synchronization")
            st.rerun()

# ----------------------------------------------------------------------
# TAB 3: DEADLOCK
# ----------------------------------------------------------------------
with tab_deadlock:
    st.info("Thread 1 grabs Printer A then wants B. Thread 2 grabs Printer B then wants A. Neither can continue: **deadlock**.")
    b1, b2 = st.columns(2)
    if b1.button("🚨 Trigger Deadlock", type="primary", use_container_width=True, disabled=dl_manager.active):
        dl_manager.trigger_deadlock()
        st.rerun()
    if b2.button("✅ Resolve Deadlock", use_container_width=True, disabled=not dl_manager.active):
        msg = dl_manager.resolve_deadlock()
        st.toast(msg)
        st.rerun()

    snapshot = dl_manager.get_status_snapshot()
    if snapshot:
        cols = st.columns(2)
        for i, job in enumerate(snapshot):
            with cols[i]:
                with st.container(border=True):
                    st.markdown(f"**{job['thread_id']}**")
                    st.write(f"Holds: `{job.get('held_resource') or '—'}`")
                    st.write(f"Wants: `{job.get('requested_resource') or '—'}`")
                    st.write(f"Status: **{job['status']}**")
        if dl_manager.is_deadlocked():
            st.error("⚠ DEADLOCK DETECTED — each thread is waiting on a resource the other one holds.")
    else:
        st.caption("Click **Trigger Deadlock** to start the two-thread demo.")


st.divider()


def _duration_display(job):
    """Turn a job's timestamps into a short, human string for the
    Duration column: a live countdown while printing, the final
    elapsed time once done, or just the planned duration beforehand."""
    duration = job.get("duration_sec")
    status = job["status"]
    now = time.time()

    if status in ("PRINTING", "DEADLOCKED") and job.get("start_ts"):
        remaining = max(0.0, duration - (now - job["start_ts"]))
        return f"⏱ {remaining:.1f}s left"
    if status in ("COMPLETED", "CANCELLED") and job.get("start_ts") and job.get("end_ts"):
        elapsed = job["end_ts"] - job["start_ts"]
        return f"{elapsed:.1f}s"
    if duration:
        return f"{duration}s (planned)"
    return ""


# ----------------------------------------------------------------------
# LIVE DASHBOARD — a fragment so it refreshes on its own without
# forcing the whole page (sidebar, forms) to re-run. This is the piece
# that keeps things fast when many people are viewing at once.
#
# It also drives cross-user NOTIFICATIONS: every browser tracks the
# last log "sequence number" it has already seen (in its own
# st.session_state). Each tick, it asks the shared manager for
# anything new since then — including events caused by a totally
# different user — and shows them as toast pop-ups. This is what
# lets User 2 find out, instantly, that User 1 just started printing.
# ----------------------------------------------------------------------
@st.fragment(run_every=1)
def live_dashboard():
    if "notif_seen_seq" not in st.session_state:
        # First time this browser has loaded: don't replay old history,
        # just start watching for events from this point forward.
        st.session_state.notif_seen_seq = manager.latest_seq()

    if st.session_state.get("notif_enabled", True):
        new_events = manager.get_events_since(st.session_state.notif_seen_seq)
        if new_events:
            st.session_state.notif_seen_seq = new_events[-1]["seq"]
            shown = new_events[-3:]  # avoid flooding the screen if many happened at once
            for entry in shown:
                st.toast(entry["message"], icon="🖨️")
            if len(new_events) > len(shown):
                st.toast(f"+{len(new_events) - len(shown)} more events — see the log below", icon="ℹ️")

    stats = manager.get_stats()
    resources = manager.get_resource_status()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active", stats["active_threads"])
    m2.metric("Waiting", stats["waiting_threads"])
    m3.metric("Completed", stats["completed_jobs"])
    m4.metric("Deadlocks", stats["deadlocks"])

    p1, p2 = st.columns(2)
    p1.metric("Printer A", "BUSY 🔴" if resources["Printer A"]["locked"] else "AVAILABLE 🟢",
               resources["Printer A"]["owner"] or "")
    p2.metric("Printer B", "BUSY 🔴" if resources["Printer B"]["locked"] else "AVAILABLE 🟢",
               resources["Printer B"]["owner"] or "")

    st.subheader("🧵 Thread Monitor")
    jobs = manager.get_jobs()
    if jobs:
        rows = [
            {
                "Thread": j["thread_id"], "User": j["user_name"], "Job": j["document"],
                "Printer": j["printer"], "Status": j["status"], "Duration": _duration_display(j),
                "Holds": j.get("held_resource") or "", "Wants": j.get("requested_resource") or "",
            }
            for j in jobs
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No jobs yet — submit one above to get started.")

    with st.expander("📋 System Log"):
        logs = manager.get_logs(limit=15)
        for entry in logs:
            st.text(entry)
        if not logs:
            st.caption("No events yet.")


live_dashboard()

st.caption("No physical printing occurs — `time.sleep()` simulates print time.")
