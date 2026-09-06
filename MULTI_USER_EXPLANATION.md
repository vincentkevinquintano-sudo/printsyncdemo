# PrintSync — Explaining "Multi-User" During Your Demo

A short script you can read almost word-for-word when your teacher or classmates ask "wait, how do multiple people actually share this?"

---

## The one-sentence answer

> "Every browser is looking at the same simulation, because the app keeps one shared Python object in memory instead of giving each visitor their own private copy."

---

## The 60-second explanation

1. **Normally, Streamlit apps don't share anything.** Every browser tab that opens a Streamlit app gets its own private memory (`st.session_state`). If PrintSync worked that way, each of you would be running your *own* invisible printer simulation — nobody would ever see anyone else's print jobs.

2. **PrintSync forces one object to be shared.** In the code, this line does the trick:
   ```python
   @st.cache_resource
   def get_manager():
       return PrinterManager()
   ```
   `st.cache_resource` tells Streamlit: *"Build this object once, the very first time the app starts — and give every future visitor a reference to that same object, forever."* So Browser 1, Browser 2, and Browser 30 are all pointing at the exact same jobs list, the exact same printer locks, the exact same log.

3. **The threads and locks are real, and they're shared too.** When anyone submits a print job, a real `threading.Thread` is created inside that one shared object. If two students submit to Printer A at the same moment, they are both trying to grab the *same* `threading.Lock` — so the lock decides who goes first, not which browser got there first. This is why the synchronization and deadlock demos work correctly no matter how many people are clicking at once.

4. **Everyone's screen updates on its own.** The dashboard at the bottom of the page automatically refreshes once a second (`st.fragment(run_every=1)`), so if Student A submits a job, Student B sees it appear in their Thread Monitor without touching anything.

---

## If someone asks "isn't that slow with lots of users?"

> "Only the small dashboard section refreshes every second — not the whole page. So one more viewer just means one more small refresh, not one more full page reload. That's the `st.fragment` doing its job."

---

## If someone asks "what if this were deployed at massive scale?"

> "This model assumes the app runs as a single process, which is how Streamlit Community Cloud's free tier works. If a company deployed something like this across multiple separate server processes for extra scale, each process would need its own copy of the shared state — you'd need a real database or message queue instead of an in-memory object to keep them all in sync. For a classroom demo with one process, this approach is simple and correct."

---

## Optional: a diagram to show alongside this

```
 Browser 1     Browser 2     Browser 3
     |             |             |
     v             v             v
   +--------------------------------------+
   |        Streamlit server process       |
   |                                        |
   |   +-------------------+   +----------+ |
   |   |   PrinterManager   |   | CSV files | |
   |   | jobs, threads,     |-->| protected | |
   |   | printer locks      |   | by a lock | |
   |   | (created ONCE,     |   |           | |
   |   |  shared by cache)  |   |           | |
   |   +-------------------+   +----------+ |
   +--------------------------------------+
```

Every browser talks to the same box in the middle. That box is what makes it "multi-user."
