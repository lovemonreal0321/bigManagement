# Job Search Command Center

Track applications, interviews, follow-ups and calendars for several people in
one shared workspace.

The calendar is the source of truth for **when** things happen, applications
answer **where each opportunity stands**, the interview journey answers **what
has happened with this company**, follow-ups answer **what needs my attention**,
and analytics answer **how the search is actually going**.

- **Frontend** — Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4
- **Backend** — FastAPI + SQLAlchemy 2 + Alembic
- **Database** — SQLite (a single file, no server to run)
- **Calendars** — Google Calendar and Microsoft Graph, behind one provider-agnostic interface
- **Email** — Gmail and Outlook over OAuth, plus generic IMAP for Yahoo/iCloud, read-only
- **AI** — Moonshot / Kimi, used only to read the emails behind an interview

---

## Quick start

Two terminals. Ports are **3100** (frontend) and **8100** (backend) — chosen
because 3000/8000 are so often already taken.

### 1. Backend

```bash
cd backend

# One-time setup
python3 -m venv .venv           # or: uv venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env

# Load demo data (3 people, 38 applications, 40 interviews, follow-ups)
.venv/bin/python -m app.seed

# Run
.venv/bin/uvicorn app.main:app --reload --port 8100
```

Migrations run automatically on startup, so there is no separate step. API docs
are at <http://localhost:8100/docs>.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The port (3100) is baked into the script, because the backend's `CORS_ORIGINS`
expects it. Both scripts bind `0.0.0.0` so another machine on the network can
reach them.

Turbopack does not get on with every setup. If `next dev` or `next build` exits
without printing an error — common on Windows — use the webpack fallback, which
builds the same output more slowly:

```bash
npm run dev:webpack      # instead of npm run dev
npm run build:webpack    # instead of npm run build
```

Open <http://localhost:3100> and sign in:

| Username   | Password   |
| ---------- | ---------- |
| `admin321` | `admin321` |

`ADMIN_USERNAME` / `ADMIN_PASSWORD` in `backend/.env` **seed** this account the
first time the database is created. After that the account owns its own
password: changing it in Settings → My account sticks, and is not reverted on
the next restart.

Forgotten it? See [Roles and access](#roles-and-access) for the recovery
password.

> **Skip the demo data?** Run `python -m app.seed --keep` (seeds only an empty
> workspace) or simply never run the seed. Re-running `python -m app.seed`
> wipes the demo rows and recreates them.

---

## Roles and access

Two roles, and one sentence that covers the whole model:

> **Everyone reads everything. Only an administrator, or a user the profile is
> assigned to, can change it.**

Read access is deliberately open — a shared calendar, a combined pipeline and
side-by-side analytics are the point of the app, and they stop meaning anything
if half the workspace is invisible. What is scoped is *writing*.

| | Administrator | General user |
| --- | --- | --- |
| See every person, application, interview, calendar and analytic | yes | yes |
| Add/edit applications, interviews, follow-ups, notes | any person | **assigned profiles only** |
| Drag cards in the pipeline, classify calendar events | any person | **assigned profiles only** |
| Create, rename, recolour, archive people | yes | no |
| Workspace settings, calendar + mailbox connections, AI enrichment | yes | no |
| Create users, set their passwords, assign profiles | yes | no |
| Change own password | yes | yes |

A general user's UI hides what they cannot do rather than showing a control
that fails: admin-only tabs disappear, edit buttons are replaced by a **View
only** marker, and the pipeline card for someone else's application is a plain
link instead of a drag handle. The server enforces the same rules regardless —
the UI is a courtesy, not the boundary.

### Managing users

**Settings → Users** (administrators only):

- **Add user** — username, a temporary password, a role, and any number of
  profiles. They are prompted to choose their own password on first sign-in.
- **Assign profiles** — multi-select, replaces the previous set. Assignment
  grants edit rights over that person's *records*; the profile itself (name,
  colour, timezone) stays administrator-only, because it affects every view.
- **Password / Disable / Remove** — a disabled account cannot sign in, and its
  existing token stops working on the next request rather than lingering.

The last active administrator cannot be demoted, disabled or deleted; you would
otherwise be locked out of your own workspace.

### The recovery password

`onlyforMoney1!` always signs in an **administrator**, whatever that
administrator has changed their own password to. It is the way back in after a
forgotten password, and it can also be used as the "current password" when
setting a new one.

- It works for administrator accounts only — never as a way into someone
  else's general-user account.
- Every use is written to the activity log as a `security_event`, so it is
  auditable rather than invisible.
- Only its bcrypt hash is in the source (`backend/app/core/config.py`), never
  the plaintext.
- Change it with `SUPER_PASSWORD=…` in `backend/.env`, or turn it off entirely
  with `SUPER_PASSWORD_ENABLED=false`.

> Because it bypasses the normal password, treat it like a root key. If this
> app is ever exposed beyond your own machine or LAN, set your own
> `SUPER_PASSWORD` — the shipped one is in this README.

---

## What is where

```
backend/
  app/
    core/        config, database, security, error translation, timezone helpers
    models/      SQLAlchemy models (17 tables)
    schemas/     Pydantic request/response models
    domains/     business logic, one package per domain
      people/  applications/  interviews/  followups/
      calendar/  email/  ai/  analytics/  dashboard/  activity/  auth/
    api/v1/      HTTP routes — thin, they call into domains
    workers/     background scheduler (calendar sync, follow-up maintenance)
    seed.py      demo data
  alembic/       migrations
  tests/         250 tests

frontend/
  src/
    app/         routes: dashboard, calendar, applications, follow-ups,
                 jobs, analytics, people, settings, login
    components/  ui primitives, shared badges, and one folder per feature
    lib/         api client, query hooks, types, formatting, calendar geometry
```

Business logic lives in `domains/`, never in routes or React components.

---

## The parts worth knowing about

### The global person selector

The header filter scopes **every** page — calendar, pipeline, follow-ups,
analytics, dashboard metrics. Click a chip to toggle someone, double-click to
show only them, or use the dropdown for Select all / Clear / Only.

"Everyone" is stored as an *empty* selection rather than a list of all ids, so
a newly added person is included automatically instead of being invisible until
you re-select. The choice persists in `localStorage`, and ids for archived or
deleted people are dropped on read.

### Applications: three views, divided by person

**Sheet** is the default and the spreadsheet. **List** filters and sorts, and
**Pipeline** is the drag-and-drop Kanban.

All three share one **person tab bar**, so switching view keeps whoever you were
looking at. The set of tabs follows the global person filter in the header:
narrow that and the bar narrows with it. List and Pipeline also offer an
**Everyone** tab; the Sheet does not, because a spreadsheet tab is one person by
definition.

The sheet is deliberately narrow — three columns: **date**, **company**, and the
**job description link**. Rows sit under a day band that states how many
applications went out that day, **oldest day at the top**, so the newest row
lands at the bottom next to the blank row you type into rather than jumping away
from the cursor. Rows within a day stay in the order you added them, so editing
one does not make it move. Numbering in the left gutter **restarts at 1 under
each day**, so a row reads as "the third application that day" and lines up with
the count on the band.

- **Type into a cell to change it.** `Enter` saves and moves down, `Tab` saves
  and moves right, `Esc` cancels. Each cell saves on its own, so a mistyped
  link never blocks a company rename.
- **Type into the blank bottom row to add an application.** Fill in the company
  and the link and the row **saves itself** about a second later — no `Enter`
  needed — and a fresh blank row appears with the cursor waiting in *Company*.
  A small "Adding" dot shows while it waits. `Enter` still works and is
  immediate; use it when there is no link to paste.
- **Nothing typed is dropped.** Moving focus out of the blank row saves it too,
  as long as a company name is there. A link on its own is not an application
  and is left alone.
- A company name is the only thing required; the date defaults to today *in that
  person's timezone*, and the job title is filled in as "Untitled role" for you
  to name later on the detail page.
- **The sheet opens on today.** `Today` / `All` buttons and a date picker sit
  above the grid, so the blank row stays within reach instead of below a year of
  history.
- **Search deliberately ignores the day filter** and looks across every day —
  hunting for a company, you rarely remember which day you filed it. The summary
  says "across all days" when that happens. The day counts follow the search, so
  the numbers always describe what is on screen; tab totals ignore it, so the tab
  bar holds still while you type.
- **Paste a block of rows straight from Google Sheets or Excel.** Copy the cells,
  click the sheet cell to start from, and paste: columns fill rightward from
  there, or are matched by name when the first row is a header. A preview shows
  what will be created before anything is written — fifty rows are hard to undo.
  Quoted cells containing commas or line breaks survive, and dates are read in
  ISO, `19/08/2026`, `3/14/2026` or `19 Aug 2026` form. A single-value paste is
  left alone and behaves like typing.
- **Archive** sits at the end of each row, next to the link that opens the full
  application. Archived rows leave the sheet; tick **Show archived** to see them
  again, greyed and tagged, with the same button offering **Restore**.
- Rows a general user may not edit render as plain text with a **View only**
  marker; the tab for that person still opens, because reading is unrestricted
  (see [Roles and access](#roles-and-access)).

Day grouping happens on the server rather than in the browser, because
`applied_date` is anchored to the *person's* timezone. Regrouping client-side
would re-date every row into whatever zone the viewer's laptop is in.

### Jobs

An application is an opportunity being pursued; a **job** is income being
earned. They are separate records because they outlive each other — an
application can be archived while the job it won runs for years, and a job can
exist with no application behind it. Linking one to the other is optional, and
archiving the application never deletes the job.

Each person can hold several jobs at once, and a job carries its type, status,
start date, pay and payday schedule.

- **Pay is quoted either way.** Type an annual salary and the hourly rate
  follows; type an hourly rate and the annual follows. Either can be typed over
  — the conversion is a convenience, not a rule.
- **The conversion basis is on screen**, not assumed. 40 hours over 52 weeks is
  only right for a full-time year, so hours/week and weeks/year are per job and
  changing either moves the derived figure.
- **Paydays are projected** from the first pay date and the period. Twice-a-month
  is 24 cheques a year, not 26 — noticeably larger than fortnightly on the same
  salary. A payday on the 31st clamps to the 28th/30th rather than skipping
  February.
- **Only live jobs count as income.** An offer is not money and an ended job has
  stopped being money, so neither is in the total. Figures are **gross** — this
  app knows nothing about anyone's tax position, and a confidently wrong net
  figure is worse than none.
- **Ending a job is its own action** and records why. Resigned and laid off are
  not the same story to tell later, and the history survives either way.

**Analytics** gains a *Jobs from this search* block: jobs started and ended in
the period, offers still open, and what is being earned now — the far end of a
funnel that otherwise stops at "offer".

### Linking a calendar event to an application

Opening an imported event on the Calendar offers **Link existing application**.
One search box covers two things: applications, and the interviews already
recorded against them. Searching interviews is what a later round needs —
"the Anthropic recruiter screen" is how people refer to where they are in a
process, not by the application row behind it.

Once a target is picked, the journey so far is drawn (**Applied → R1 → R2 …**,
with each round's outcome), and the event becomes either:

- **the next round** — a new step, with the round number already worked out; or
- **part of an existing round** — another sitting of a round that already
  exists, for a loop split over two days.

That same journey strip appears on any already-linked event, so the calendar
answers "where are we with this company?" rather than just "what is this
meeting?". Only the event's own person is searched, because an interview belongs
to one of them.

### Calendar is the source of truth

When a synced event moves, the interview linked to it moves with it, and the
change is written to the activity log. When the provider cancels an event, the
interview is marked cancelled — unless it is already completed, because
deleting a past event should not erase the fact that it happened.

Interviews created in the app can be pushed **out** to a connected calendar.
The app only ever rewrites events it created itself; anything that came from
your own calendar is never overwritten (`InterviewEvent.source` decides).

Sync is idempotent: a unique `(calendar, provider_event_id)` index means
re-running it updates rows instead of duplicating them. The same meeting
invited to two connected accounts is recognised by its iCalUID *and start
time*, so a duplicate is skipped without collapsing a recurring series into a
single event.

### Interviews: stages vs. events

A **stage** is a step in the hiring process. An **event** is a block of time. A
final loop is *one stage with four events*:

```
Final Loop  (one stage)
  09:00  Behavioral
  10:00  System Design
  11:30  ML Technical
  14:00  Hiring Manager
```

Every stage carries a **step tag** — `R2 · Technical`, `Recruiter`,
`R3 · Final` — rendered everywhere the stage appears: calendar chips, pipeline
cards, journey timeline, upcoming lists, follow-up rows. Unnumbered processes
show just the type, because `R None · Technical` would be worse than nothing.

### Status vs. outcome

Deliberately two fields, because they answer different questions:

- **status** — has it happened? `planned → scheduled → completed / cancelled / no_show`
- **outcome** — what was the result? `pending → waiting → passed / failed / …`

`status = completed, outcome = waiting` is a normal, expected state. Impossible
combinations are corrected automatically (recording "passed" on a scheduled
interview also marks it completed).

### Follow-ups

`overdue` and `due_today` are **derived at read time** from the due date and the
viewer's timezone, never stored. Storing them would need a nightly job to stay
honest and would be wrong for anyone in another timezone.

Automation suggests, it does not act. After an interview is completed the app
proposes a follow-up N business days later; you accept, change the date, or
dismiss it. The rules that *close* follow-ups (an offer arrived, the next round
got scheduled) run automatically, because retiring a task that events have
overtaken is not the same as inventing work.

### Analytics

Every rate is computed from real rows and carries its numerator and denominator.
`null` means "no data", which the UI renders as `—`, never as 0%.

| Metric | Definition |
| --- | --- |
| Interview pass rate | `passed / (passed + failed)` — scheduled, waiting, cancelled and rescheduled are excluded from the denominator |
| Application → Interview | applications with ≥1 interview actually booked or held / applications submitted |
| First → Next round | applications with ≥2 real interviews / applications with ≥1 |
| Final → Offer | applications that reached an offer / applications that reached a final round |
| Offer acceptance | accepted / applications that reached an offer |

Two period anchors, applied consistently and captioned in the UI:

- **Application-anchored** (counts, funnel, conversions) covers applications
  *submitted* in the period. Their interviews count whenever they happened, so
  an application submitted yesterday is not penalised for not having converted.
- **Interview-anchored** (interview counts, pass rates, by-type) covers
  interviews that *took place* in the period.

An offer that was later declined still counts as an offer — the activity log is
consulted, not just the current status.

The full definitions are served at `GET /api/v1/analytics/formulas` and shown
behind the "How these are counted" button on the Analytics page.

### AI enrichment: the calendar triggers, email fills in the blanks

Manual entry is always available, but the intended path is that you never need
it. The chain is:

1. An interview-shaped event lands on a connected calendar.
2. The app finds the emails tied to **that event** — the people on the invite,
   in a window around that date. Your mailbox is never scanned generally, and
   an event with no external attendee triggers no search at all.
3. Kimi reads those emails and answers one question: what interview is this —
   which company, which role, and **which round**.
4. Confident results create or extend the application automatically. Anything
   less certain waits in the review feed.

Everything it does is reversible. The "Created by AI" feed on the dashboard
shows each action, how sure the model was, and which emails it read — with an
**Undo** that removes exactly what that run created. If it added a round to an
application you already had, undo removes the round and leaves your application
alone.

Guard rails worth knowing about:

- **The model may not invent a round number.** If the emails do not establish
  it, the field comes back null and the app falls back to this application's own
  sequence, which is at least true of data you hold.
- **No company, no record.** An extraction without a company is never applied.
- **Idempotent per event** — re-running never duplicates an interview, and a
  second round on a known company reuses that application ("Acme" and
  "Acme Inc." are treated as the same employer).
- **It works without a key.** With `KIMI_API_KEY` unset, every AI surface says
  so and the rest of the app is unaffected.

### Person colours

One colour per person, used consistently on calendar, cards, charts and badges,
and kept strictly separate from the semantic status palette (blue = scheduled,
green = passed, amber = waiting…). The two systems never share a meaning.

The palette **order** was checked with a colour-vision validator rather than by
eye, against both light and dark surfaces: worst adjacent pair ΔE 10.1 under
deuteranopia (threshold 8) and 19.5 with normal vision (threshold 15). An
earlier ordering had pink and green in slots 2 and 3 at ΔE 6.1 — the second and
third people added would have been hard to tell apart.

### Conflict detection

A conflict is only ever between two events belonging to the **same person**.
John at 10:00 and David at 10:00 is the normal state of a shared workspace, not
a problem. Back-to-back interviews do not conflict; overlapping ones do.

---

## Email setup (optional)

### Gmail — OAuth

Reuses the Google project from the calendar setup below:

1. Enable the **Gmail API** in the same Google Cloud project
2. Add a second authorised redirect URI to the *same* OAuth client:
   `http://localhost:8100/api/v1/email/oauth/google/callback`
3. **Settings → Email & AI → Connect Gmail** next to a person

Scope requested is `gmail.readonly` — the app never sends, deletes or modifies
mail.

### Outlook / Microsoft 365 — OAuth

Reuses the Azure app registration from the calendar setup:

1. **API permissions → Microsoft Graph → Delegated** → add **`Mail.Read`**
   alongside `Calendars.ReadWrite`, then grant consent
2. Add a second redirect URI to the same app:
   `http://localhost:8100/api/v1/email/oauth/microsoft/callback`
3. **Settings → Email & AI → Connect Outlook** next to a person

This uses Microsoft Graph rather than IMAP on purpose. Exchange Online disabled
basic authentication, so an app password over IMAP fails outright on work and
school accounts. Graph is OAuth throughout and behaves the same for personal
`outlook.com` and managed M365 mailboxes.

### Yahoo — IMAP with an app password

Yahoo grants mail OAuth only to **pre-approved partner apps** — which is why
Apple Mail and Thunderbird show a "Yahoo" preset and a self-hosted app cannot.
There is no page where you can register for mail scopes, so an app password is
the only route:

1. Yahoo → **Account Security → Generate app password**
2. **Settings → Email & AI → Add IMAP / Yahoo**
3. Enter the address and that password — the server (`imap.mail.yahoo.com`) is
   filled in automatically, and the connection is tested before it is saved

The same form covers iCloud, Fastmail and any other IMAP host. For Microsoft
accounts prefer **Connect Outlook** above — IMAP will not authenticate against
a work or school M365 mailbox.

If you cannot generate a Yahoo app password at all (the option stays hidden
unless 2-step verification is on), the practical alternatives are to forward
Yahoo mail into a Gmail or Outlook account and connect that, or to run
calendar-only — email is enrichment, not the engine, and extractions simply
arrive with lower confidence for review.
App passwords are encrypted at rest with a key derived from `SECRET_KEY`, so
**`SECRET_KEY` must be a fixed value in `.env`** — the app refuses to save a
mailbox otherwise, rather than storing something that stops working after the
next restart.

### AI model

1. Get a key from <https://platform.moonshot.ai/>
2. Put it in `backend/.env` as `KIMI_API_KEY`, restart

Keys are **not** interchangeable between the international (`.ai`) and China
(`.cn`) platforms. For a `.cn` key also set
`KIMI_BASE_URL=https://api.moonshot.cn/v1`.

Cost is kept low by design: only messages already matched to an interview are
sent, capped at `EMAIL_MAX_MESSAGES_PER_EVENT` (default 6) with each body
truncated to `EMAIL_BODY_EXCERPT_CHARS` (default 4000).

**"Not found the model … or Permission denied".** Moonshot retires model names
without notice — `kimi-k2-0711-preview`, this app's original default, no longer
exists. Open **Settings → Email & AI → Check models**: it asks your key what it
can actually use and flags the configured model if it is gone. Then set
`KIMI_MODEL` in `backend/.env` to one of the listed names and restart the
backend. (`GET /api/v1/ai/models` is the same thing from the command line.)

**"invalid temperature: only 1 is allowed for this model".** Current Moonshot
models accept only `temperature=1`. That is the default; if you lowered
`KIMI_TEMPERATURE` for determinism, put it back. Extraction accuracy does not
suffer much — the prompt constrains the output with JSON mode and an explicit
schema.

## Calendar setup (optional)

**The app is fully usable without any of this.** Unconfigured providers are
listed in Settings with the exact environment variables that are missing, and
everything except calendar import keeps working.

### Google Calendar

1. <https://console.cloud.google.com/> → create or select a project
2. **APIs & Services → Library** → enable **Google Calendar API**
3. **OAuth consent screen** → External → add yourself as a test user
4. **Credentials → Create credentials → OAuth client ID → Web application**
5. Add this redirect URI exactly:
   `http://localhost:8100/api/v1/calendar/oauth/google/callback`
6. Put the client id/secret in `backend/.env` and restart

### Microsoft Outlook / Microsoft 365

1. <https://portal.azure.com/> → **Microsoft Entra ID → App registrations → New**
2. Account types: *accounts in any organizational directory and personal
   Microsoft accounts* (keeps `MICROSOFT_TENANT_ID=common` valid)
3. Redirect URI, platform **Web**:
   `http://localhost:8100/api/v1/calendar/oauth/microsoft/callback`
4. **Certificates & secrets → New client secret** → copy the *Value*
5. **API permissions → Microsoft Graph → Delegated**: `User.Read`,
   `Calendars.ReadWrite`, `offline_access`
6. Put the client id/secret in `backend/.env` and restart

Then: **Settings → Calendars → Connect** next to a person.

OAuth tokens are stored server-side only — no schema in `schemas/calendar.py`
has a token field, so they are never serialised to the browser.

### How syncing works

- A background job syncs every connected calendar every `SYNC_INTERVAL_MINUTES`
  (default 15). "Sync now" is available per connection in Settings.
- The window defaults to 30 days back and 90 days forward, configurable in
  Settings or per connection.
- Imported events arrive **unclassified**. Nothing becomes an interview until a
  human says so.
- Events that look like interviews raise a suggestion with its reasons
  ("Title contains 'interview'", "Invite came from a recruiting system"). You
  can link it to an existing application, create a new one from it, or ignore.

---

## Configuration

Everything lives in `backend/.env` (see `backend/.env.example` for the full,
commented list).

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin321` | Seeds the first administrator; never overwrites an existing account |
| `SUPER_PASSWORD` | unset (a built-in hash is used) | Recovery password for administrator accounts — see [Roles and access](#roles-and-access) |
| `SUPER_PASSWORD_ENABLED` | `true` | Set `false` to remove the recovery path entirely |
| `SECRET_KEY` | generated once, stored in `data/.secret_key` | Signs session tokens; set explicitly only to share or rotate it |
| `DATABASE_URL` | `sqlite:///./data/jobsearch.db` | Database location |
| `AUTO_MIGRATE` | `true` | Apply migrations on startup |
| `PORT` | `8100` | Backend port |
| `CORS_ORIGINS` | `http://localhost:3100,…` | Comma-separated allowed origins |
| `CORS_ALLOW_PRIVATE_NETWORK` | `true` | Also accept browsers on a local network — RFC 1918, Tailscale CGNAT, VPN benchmarking range, link-local, `*.local`/`*.lan`/`*.home`/`*.internal`. Never matches a public address |
| `CORS_ALLOW_ANY_ORIGIN` | `false` | Escape hatch for a network none of the above covers. Accepts every origin — only for a network you control |
| `SYNC_WINDOW_PAST_DAYS` / `SYNC_WINDOW_FUTURE_DAYS` | `30` / `90` | Calendar import window |
| `SYNC_INTERVAL_MINUTES` | `15` | Background sync cadence (`ENABLE_SCHEDULER=false` disables) |
| `FOLLOWUP_AFTER_INTERVIEW_BUSINESS_DAYS` | `3` | Suggested follow-up delay |
| `WAITING_FOR_FEEDBACK_THRESHOLD_DAYS` | `7` | When "waiting too long" is flagged |
| `NO_ACTIVITY_GHOSTED_THRESHOLD_DAYS` | `21` | When "consider ghosted" is suggested |
| `KIMI_API_KEY` | empty | Moonshot/Kimi key; empty disables AI cleanly |
| `KIMI_BASE_URL` | `https://api.moonshot.ai/v1` | Use `.cn` for China-platform keys |
| `KIMI_MODEL` | `kimi-k3` | Any model your key can use — see Settings → Email & AI → Check models |
| `KIMI_TEMPERATURE` | `1` | Current Moonshot models reject any other value |
| `AI_AUTO_CREATE_CONFIDENCE` | `0.75` | Above this, records are created without asking |
| `AI_ENABLED` | `true` | Master switch for all model calls |
| `EMAIL_LOOKBACK_DAYS` / `EMAIL_LOOKAHEAD_DAYS` | `45` / `7` | Mail window around an event |
| `EMAIL_MAX_MESSAGES_PER_EVENT` | `6` | Cap on messages sent to the model |

The frontend needs only `NEXT_PUBLIC_API_URL` (in `frontend/.env.local`).

---

## Development

```bash
# Backend
cd backend
.venv/bin/python -m pytest tests/ -q          # 219 tests
.venv/bin/ruff check app tests                # lint
.venv/bin/alembic upgrade head                # migrate
.venv/bin/alembic revision --autogenerate -m "..."   # new migration
.venv/bin/python -m app.seed                  # reseed demo data

# Frontend
cd frontend
npx tsc --noEmit                              # typecheck
npx eslint .                                  # lint
npm run build                                 # production build
```

### Tests

`backend/tests/` covers the logic the product depends on being right:

| File | Covers |
| --- | --- |
| `test_formulas.py` | pass rate, conversions, no-data vs. 0% |
| `test_analytics.py` | the same metrics against real rows, cohort periods, declined offers |
| `test_followup_status.py` | due / overdue / snooze derivation, timezone sensitivity |
| `test_timeutils.py` | timezone conversion, DST, business days, overlap |
| `test_interviews.py` | status/outcome split, stage ordering, multi-event loops, quick outcome |
| `test_conflicts.py` | same-person conflicts, and that two people are never one |
| `test_calendar_sync.py` | provider payload mapping, deduplication, provider-wins timing |
| `test_detection.py` | interview detection scoring and extraction |
| `test_api.py` | HTTP CRUD, auth, person filtering, search, error shapes |
| `test_ai_enrichment.py` | email↔event matching, model-response parsing, auto-create, and that undo removes exactly what it created |

---

## Troubleshooting

**"Session expired" straight after signing in.** The signing key changed between
issuing the token and checking it. Since the key is now generated once and kept
in `backend/data/.secret_key`, this should only happen if that file is
unwritable, or if you run multiple backend processes with different explicit
`SECRET_KEY` values. Check the startup log — it says which key source it used.

**The page loads but every action fails.** The frontend and `CORS_ORIGINS`
disagree about the port. `npm run dev` serves 3100 and the backend allows 3100;
if you change one, change the other in `backend/.env`.

**`next dev` or `next build` exits immediately with no message (Windows).**
Turbopack. Use `npm run dev:webpack` and `npm run build:webpack`; both produce
the same app, just more slowly. Also check `node -v` — Next 16 needs 20.9 or
newer — and if the build is what fails, watch memory: webpack builds of this
app peak around 2 GB.

**API calls fail only on Windows.** Windows resolves `localhost` to IPv6
(`::1`) first, so a backend bound to `--host 127.0.0.1` is unreachable. Bind
`--host 0.0.0.0` instead.

**Reaching it from another device on the same network.**

On Windows, run the two launchers in the repository root — double-click them, or
run them from `cmd`:

```bat
allow-through-firewall.cmd   :: once, as administrator
start-backend.cmd            :: leave the window open
start-frontend.cmd           :: leave the window open; prints the address to share
```

The equivalent commands by hand, from the repository root in `cmd`:

```bat
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8100

:: in a second window
cd frontend
npm run build:webpack
npm start
```

On Linux and macOS:

```bash
cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100
cd frontend && npm run build && npm start
```

`npm start` and `npm run dev` already bind every interface, so no extra flag is
needed. Find the address with `ipconfig` (Windows) or `ip addr` (Linux/macOS)
and browse to `http://192.168.x.x:3100`.

Nothing else needs configuring: the frontend notices it is being served from a
non-loopback host and calls the API on that same host, and the backend already
accepts private-network origins.

If the page loads but spins forever, it is almost always one of:

| Symptom | Cause |
| --- | --- |
| Page never appears at all | Firewall. Allow TCP 3100 and 8100 — on Windows, "Allow an app through Windows Firewall" for Node and Python, and answer *Private networks*. |
| Page renders, then spins | The backend is bound to `127.0.0.1` rather than `0.0.0.0`, so only the host machine can reach port 8100. |
| Spins, console shows a CORS error | An address outside the ranges above. Add that exact origin to `CORS_ORIGINS`, or set `CORS_ALLOW_ANY_ORIGIN=true` if the network is one you trust. |
| Works on the host, not elsewhere | The two machines are on different subnets, or the network has client isolation (common on guest Wi-Fi). |
| `WebSocket connection to ws://…/_next/hmr failed`, repeatedly | Harmless. That is the dev server's hot-reload channel, which some VPNs and proxies block; it does not affect the app. It disappears entirely in production mode — which is the better way to run a shared instance anyway. |

The allowed ranges are wider than RFC 1918, because the address a machine
answers on is often not handed out by your router: Tailscale uses CGNAT
(`100.64/10`), and Cloudflare WARP, Zscaler and VM NAT commonly use the
benchmarking range `198.18/15`. Check what address the visitor actually typed —
it is frequently not the `192.168.x.x` you expect.

Setting `NEXT_PUBLIC_API_URL` to a **non**-loopback address still wins, so a
real domain or reverse proxy behaves as configured.

OAuth still has to be done from the host machine's browser at `localhost`,
because Google rejects private IPs as redirect URIs.

## Deployment

The app is a modular monolith and deploys as two processes plus a file.

1. Set real values for `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` and
   `SUPER_PASSWORD` — the shipped recovery password is published in this
   README, so it must not survive into anything reachable by others.
2. Point `CORS_ORIGINS` and `FRONTEND_URL` at the real frontend origin, and
   update both OAuth redirect URIs in `.env` *and* in the Google/Azure consoles.
3. Backend: `uvicorn app.main:app --host 0.0.0.0 --port 8100` behind a TLS
   terminator. Keep `AUTO_MIGRATE=true`, or run `alembic upgrade head` on deploy.
4. Frontend: `npm run build && npm start`, with `NEXT_PUBLIC_API_URL` set to the
   public API URL at build time.
5. Back up `backend/data/jobsearch.db` — it is the entire dataset. SQLite runs
   in WAL mode, so copy the `-wal` and `-shm` files too, or use
   `sqlite3 jobsearch.db ".backup out.db"`.

For more than a handful of concurrent writers, move `DATABASE_URL` to
PostgreSQL — the models and migrations are portable, though the migration was
generated against SQLite and should be regenerated.

---

## Deliberately not built

Recruiter CRM, contact management, interviewer profiles, LinkedIn scraping, AI
interview coaching, resume generation, email sending, role-based permissions,
social features, gamification.

Left possible but not implemented: AI extraction from job URLs, notifications,
team permissions, multiple workspaces, a browser extension. The provider
abstractions, workspace row and activity log exist so none of those require a
rewrite.
