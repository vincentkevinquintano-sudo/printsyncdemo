# PrintSync

**Multi-User Printer Simulation System for Demonstrating Multithreading, Synchronization, and Deadlock**

A Streamlit web application built for a college Computer Science demonstration. Multiple people open the same URL, submit simulated print jobs, and watch real Python threads compete for shared printer resources — including a safely-recoverable deadlock.

---

## 1. Project Description

PrintSync simulates a shared office printer being used by many people at once. Instead of a single-user desktop app, it is a small "operating system" style demo: every print request becomes a real `threading.Thread`, and two virtual printers (`Printer A` and `Printer B`) are shared resources protected by `threading.Lock` objects. The app has three modes that build on each other:

1. **Multithreading** — many threads running independently
2. **Synchronization** — those threads correctly taking turns on a shared printer
3. **Deadlock** — what goes wrong when two threads grab shared resources in the wrong order, and how to recover

No physical printing happens — `time.sleep()` stands in for the time it would take to print.

## 2. Objectives

- **Multithreading**: show that `threading.Thread` lets several print jobs make progress "at the same time" instead of strictly one-after-another.
- **Synchronization**: show that a `threading.Lock` around a *critical section* prevents two threads from using the same printer at the exact same instant, at the cost of one thread having to wait.
- **Deadlock**: show what happens when two threads acquire two shared locks in opposite orders — a circular wait where neither thread can proceed.
- **Deadlock recovery**: show a safe, cooperative way to break the deadlock (cancelling one thread via a `threading.Event`) rather than an unsafe forced kill.

## 3. Technologies

- Python 3
- Streamlit (UI only — no HTML/CSS/JS written by hand)
- `threading` (`Thread`, `Lock`, `Event`)
- `csv` (persistent storage, no external database)
- `time`, `datetime`

## 4. Project Structure

```
PrintSync/
├── app.py                 # Streamlit UI — display and user input only
├── printer_manager.py     # Core simulation engine: jobs, threads, locks
├── deadlock_manager.py    # Deadlock demo + safe cooperative recovery
├── csv_manager.py         # Thread-safe CSV read/write helpers
├── requirements.txt
├── README.md
└── data/
    ├── print_jobs.csv     # created automatically if missing
    └── system_logs.csv    # created automatically if missing
```

## 5. Installation

```bash
pip install -r requirements.txt
```

## 6. Running Locally

```bash
streamlit run app.py
```

Then open the URL Streamlit prints in your terminal (usually `http://localhost:8501`).

## 7. Hosting on Streamlit Community Cloud

1. Create a new GitHub repository and push the whole `PrintSync/` folder to it.
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **"New app"** and connect it to your repository.
4. Set the main file path to `app.py`.
5. Click **Deploy**.
6. Share the generated URL (something like `https://your-app-name.streamlit.app`) with your classmates so they can all submit print jobs to the same running app.

### A note on multi-user state and scaling to more viewers

Streamlit normally isolates `st.session_state` per browser tab. PrintSync gets around this with **`@st.cache_resource`** (see the top of `app.py`), which is Streamlit's officially supported way to share one Python object across every connected user. The `PrinterManager` (jobs, locks, logs) and `DeadlockManager` are each created **once** for the whole running app, not once per visitor — so everyone's browser sees the same threads, the same locks, and the same log.

To keep things responsive as **more people join at once**, the live-updating part of the page (metrics, printer status, thread table, log) is wrapped in `@st.fragment(run_every=1)`. Only that small fragment re-executes on its own every second — the sidebar, tabs, and forms are untouched — so each viewer's browser does far less work per refresh than if the whole page reran. This is what lets a whole class watch the same dashboard smoothly.

**Limitation:** if your hosting platform ever runs multiple separate server processes/containers for the same app (some "auto-scaling" setups do this), each process would have its own independent cached objects and users could be split across them. Streamlit Community Cloud's free tier runs a single process per app, which is exactly what this design assumes.

## 8. Classroom Demonstration — Suggested Presentation Flow

### Part 1 — Multithreading
1. Open the **🧵 Multithreading** tab.
2. Click **Generate 3 Test Jobs** (or submit a few jobs by hand from different browser tabs/devices).
3. Point at the **Thread Monitor** table at the bottom: several rows show `PRINTING` at the same time, each with a different Thread ID.
4. Say: *"Each print request creates a separate thread, so multiple documents make progress concurrently."*

### Part 2 — Synchronization
1. Open the **🔒 Synchronization** tab.
2. Click **Generate 3 Test Jobs (same printer)**, or submit two or three jobs that all target **Printer A**.
3. Point at the **Printer A** metric at the bottom: it flips to `BUSY` with one owner while the others sit at `WAITING` in the Thread Monitor until the lock is released.
4. Say: *"Because the printer is a shared resource, `threading.Lock` makes sure only one thread enters the critical section — acquiring, printing, and releasing — at a time."*

### Part 3 — Deadlock
1. Open the **⚠️ Deadlock** tab.
2. Click **🚨 Trigger Deadlock**.
3. Watch the two thread cards: Thread 1 holds Printer A and wants Printer B; Thread 2 holds Printer B and wants Printer A. The banner **⚠ DEADLOCK DETECTED** appears.
4. Say: *"Each thread is holding one resource while waiting for a resource the other thread holds — a circular wait. Neither can move forward."*

### Part 4 — Recovery
1. Click **✅ Resolve Deadlock**.
2. Watch one thread flip to `CANCELLED` (releasing its printer) and the other flip to `COMPLETED`.
3. Say: *"We didn't force-kill anything. The cancelled thread noticed a cooperative cancellation signal (`threading.Event`), gave up waiting, and safely released its resource — which let the other thread finish."*

*(If nobody clicks Resolve, the demo auto-resolves itself after ~25 seconds so the app never actually hangs.)*

## 9. Other Controls

- **Start / Stop / Reset** (sidebar): Stop simply blocks new job submissions; Reset cooperatively clears all jobs, counters, logs, and creates fresh locks (it never force-kills a thread).
- **Print Duration**: a sidebar setting (default 3 seconds) that every job uses, no matter who submits it or how many pages they type. A fixed, short duration makes a multi-user demo predictable — everyone waits about the same, easy-to-see amount of time.
- **🔔 Notifications**: with "Notify me about other users' activity" checked (on by default), your browser pops up a toast the instant *any* user — including someone else's browser — submits a job, acquires a printer, or completes one. You no longer have to keep an eye on the log to know what other people are doing.
- **Demonstration Controls**: `Generate 3 Test Users` and `Clear Simulation` are there so the presenter can run the whole demo solo, without waiting for classmates to submit real jobs.

## 10. Data Files

`data/print_jobs.csv` and `data/system_logs.csv` are created automatically the first time the app runs if they don't already exist. All writes go through a dedicated `csv_lock` (see `csv_manager.py`) because multiple threads can try to log an event or save job state at the same moment — the same synchronization idea the app is teaching, applied to file I/O.
