# PayrollPro – Employee Payroll Management System

PayrollPro is a web application for running a small company's HR and payroll in one place: employee records, GPS-verified attendance with shift-based late minutes, shifts, overtime approval, leave and work-from-home requests, document verification, salary structures, monthly payroll with PDF payslips, Excel reports, analytics, announcements, targeted notifications, private messaging, an audit trail and four Google Gemini–powered AI assistants.

- **Backend:** Django 6.1 + Django REST Framework, PostgreSQL, ReportLab (PDF), OpenPyXL (Excel), Google Gemini API (AI), google-auth (Google sign-in)
- **Frontend:** plain HTML, CSS and JavaScript (no build step), responsive, light and dark themes
- **Roles:** Administrator and Employee, each with its own portal

> 📘 For a step-by-step description of every feature (workflows, rules, validations, notifications and a worked payroll example), see the **[Feature Guide](docs/FEATURES.md)**. For the requirement-by-requirement status against the SRS, see **[SRS compliance](docs/SRS_COMPLIANCE.md)**.

---

## Contents

1. [Features](#1-features)
2. [Payroll rules](#2-payroll-rules)
3. [Project structure](#3-project-structure)
4. [Setup](#4-setup)
5. [Configuration (`.env`)](#5-configuration-env)
6. [Google sign-in (optional)](#6-google-sign-in-optional)
7. [Getting started as an administrator](#7-getting-started-as-an-administrator)
8. [API reference](#8-api-reference)
9. [Security](#9-security)
10. [Tests](#10-tests)

---

## 1. Features

### 1.1 Accounts and sign-in

| Feature | Details |
| --- | --- |
| Separate admin and employee sign-in | The login page has an *Administrator* / *Employee* switch. Signing in with the wrong type is refused. |
| Username **or** email login | Either one can be used in the username field. |
| Remember me | Keeps the session for 7 days (configurable); otherwise it ends when the browser closes. |
| Self-registration | Anyone can register an **Employee** account. Admin accounts cannot be created publicly. An administrator then completes the employee record (see *Onboarding*). |
| Forgot password with OTP | A 6-digit code is emailed (printed to the server console when email is not configured). It expires in 10 minutes and allows 5 attempts. After verifying, the user sets a new password. |
| Change password | From **Settings**, using the current password. The session stays signed in. |
| Password strength | Django's validators: minimum length, not too common, not all numbers, not similar to the username/email. |
| Brute-force lockout | 5 failed logins or OTP requests (per IP and per username) lock that route for 15 minutes. |
| Inactive accounts | Deactivated employees cannot sign in by any method. |
| Sign in with Google | Optional "Continue with Google" for login and sign-up, plus connect/disconnect from Settings. See [section 6](#6-google-sign-in-optional). |
| First superuser | An account made with `createsuperuser` is treated as an administrator on first login. |

### 1.2 Dashboards

**Admin dashboard**
- Employee counts: total, active, inactive, joined this month, accounts waiting for onboarding
- Pending work: leave requests, WFH requests and documents awaiting review
- Today: employees checked in, on leave, and working from home
- Latest payroll period (gross, deductions, net, drafts left) and a six-month net/gross trend chart
- Active employees without a salary structure (these are skipped by payroll)
- Headcount by department, the five most recent pending leave requests and the latest announcements

**Employee dashboard**
- Employee ID, department, designation, joining date and status
- Leave balance per leave type for the current year
- Own pending leave, WFH and document requests
- Days present this month and today's check-in/check-out state
- Latest payslip and a salary (net pay) trend for the last six payslips
- Upcoming holidays and the latest announcements

### 1.3 Employee management (admin)

- Add an employee with login details (username, email, temporary password), employee ID, name, phone, department, designation and joining date
- **Onboarding:** accounts that registered themselves appear as *pending accounts*; the admin completes their employee record without creating a new login
- Edit any employee detail, including email and status
- Deactivate / reactivate (soft delete). Inactive employees cannot sign in and are skipped in payroll. An admin cannot deactivate their own account.
- Search (ID, username, name, email, department, designation), filter by status and department, sort by ID, name, department, joining date or status, and paginate
- Validation: unique employee ID (2–20 letters, numbers, `- _ /`), valid phone number (7–15 digits), unique username and email
- Every create, update and deactivation is written to the audit log

### 1.4 Attendance (GPS-based)

- **Admin:** set the office location (latitude/longitude, or "use my current location"), the allowed radius in metres, and turn attendance on or off
- **Employee:** check in and check out from the browser. The browser's GPS location is sent, and the server checks the distance to the office (haversine formula). Outside the radius, the action is refused with the actual distance.
- One record per employee per day; you cannot check in twice, check out twice, or check out before checking in
- Each record stores times, coordinates and distance from the office for both check-in and check-out
- **Employee:** today's status and recent attendance history
- **Admin:** all attendance records, filterable by a single date or a date range, with search by name, username or employee ID
- Administrators cannot mark attendance for themselves
- **Late minutes:** each check-in records the employee's shift, scheduled start and minutes late (0 within the shift's grace period; otherwise minutes since the shift start). Admins filter late/on-time check-ins and see a per-employee *Late & hours summary* (days present, late days, late minutes, average lateness, hours worked)
- Excel export of attendance records and the summary

### 1.4a Shifts (admin)

- Create, edit, deactivate and delete shifts: name, start/end time (overnight shifts supported), grace period, unpaid break, description, and one **default shift** for employees without an assignment
- **Assign** a shift to one or many employees for a date range (or open-ended); overlapping assignments are refused unless *Replace current shift* is ticked, which ends the earlier assignment the day before
- **Employee shift records:** full assignment history, searchable and filterable by shift or "active today"; employees see their current shift and history on *Attendance & shift*
- Shifts drive late minutes and the standard working day used for overtime

### 1.4b Overtime

- **Employees** claim overtime for a past day (hours in quarter steps + reason); the rate comes from their salary structure
- **Admins** record overtime for any employee (optionally approved at once), edit pending records, approve, or reject with a reason
- **Generate from attendance:** creates *pending* records for time worked beyond each day's shift (or the standard 8 h)
- Statuses: Pending → Approved / Rejected, or Cancelled. Only **approved** overtime is paid; amount = hours × rate
- Overtime in a month whose payroll is finalised is locked. Payroll runs report how many overtime records are still pending
- Monthly totals (records, pending, approved hours and amount), Excel export, notifications and audit entries

### 1.5 Leave management

- **Admin-controlled leave policy** (*People → Leave policy*), stored in PostgreSQL: create, edit, activate/deactivate leave types; allowed days per employee per leave year (or no limit); paid/unpaid; carry forward with a maximum; leave year start month, minimum notice, maximum days per request and past-date rule; carry unused days forward; view and adjust any employee's balance. No leave type or limit is hard-coded. (Initial types: Casual 12, Sick 12, Earned 15 paid days; Other unpaid, no limit.)
- Employees apply with dates and a reason; the number of days is calculated automatically, and the form shows each type with the days that can still be requested
- **Leave balance** per type on the Leave page and dashboard: total allowed, used (approved), pending (separate) and available
- Requests that exceed the balance (counting pending requests), break the notice / length / past-date rules, or use inactive types are refused on the server
- Employees can cancel their own **pending** requests; rejected and cancelled requests never use balance
- Overlapping pending/approved leave requests are refused
- **Admin:** approve or reject (with a reason shown to the employee), filter by status and leave type, search by employee, paginate
- A request can only be processed once
- Approved paid leave counts as a paid day in payroll; approved "Other" leave is loss of pay

### 1.6 Work from home (WFH)

- Employees request WFH for a date range with a reason
- Overlapping pending/approved requests are refused
- Employees can cancel their own pending requests
- **Admin:** approve, or reject with a required note shown to the employee; filter by status
- Approved WFH days count as paid days in payroll

### 1.7 Documents

- Employees upload documents: Identity proof, Address proof, Education certificate, Resume, or Other (with a custom type name)
- PDF, JPG or PNG only, up to 5 MB. The real file header is checked, not just the extension.
- Status: *Pending review* → *Verified* or *Rejected* (rejection needs a reason, shown to the employee)
- Employees can delete documents only while they are still pending
- Files are private: they are streamed through an authenticated endpoint to the owner or an administrator only, never served publicly
- **Admin:** review all documents and filter by status

### 1.8 Salary structures (admin)

Each employee has one monthly salary structure:

| Earnings | Deductions | Other |
| --- | --- | --- |
| Basic (must be > 0) | Provident fund % of basic + DA (default 12%) | Overtime pay per approved hour |
| House rent allowance (HRA) | Professional tax (per month) | Monthly bonus (paid in full) |
| **Dearness allowance (DA)** | Income tax / TDS (per month) | Effective-from date |
| Conveyance allowance | Other deductions (e.g. loan instalment) | |
| Medical allowance | | |
| Special allowance, other allowance | | |

- Monthly gross is calculated automatically
- Fixed monthly deductions (PF + professional tax + TDS + other) may not exceed the gross
- Filter employees by status and by "structure configured / not configured", search, paginate
- The employee is notified when their structure is set or changed; every change is audited

### 1.9 Payroll runs (admin)

1. **Run payroll** for a month (only after that month has ended). Choose how absence is handled:
   - *Calculate from attendance, leave and work-from-home records* (default), or
   - *Do not deduct for absence (full month)*, for companies that don't use attendance
2. Draft payslips are created for every active employee who has a salary structure. Employees are **skipped** with a reason if they already have a payslip for that month, have no salary structure, joined after the month, or their deductions would exceed earnings.
3. **Review drafts:** search, filter by status, paginate, and see totals (count, gross, deductions, net, drafts, paid)
4. **Adjust a draft:** loss-of-pay days (whole or half days, no more than the working days), bonus, other deductions and a note. Amounts are recalculated, and the net salary cannot go negative.
5. **Recalculate** a draft from the current salary structure and attendance (this discards manual adjustments)
6. **Delete** a draft
7. **Review the variance** against the previous month (see 1.9a), record the review, then **finalise**: drafts become *Paid* and are published to employees, who are notified. Finalising is refused until a current review exists
8. **Export CSV** payroll register for the month (opens in Excel; formula injection is neutralised)
9. **View/download a PDF payslip** for any employee

Paid payslips can no longer be changed. Each payslip stores a snapshot of the employee's code, name, department and designation, so later changes to the employee don't alter old payslips. Every run, adjustment, recalculation, deletion, finalisation and export is audited.

### 1.9a Payroll variance review (admin)

- Before finalising, **Payroll runs → Review & finalise** opens a side-by-side comparison of every employee's payslip with the previous month: each earning and deduction, working/LOP days and overtime hours, with the amount and % change
- **Flags** (nothing is changed automatically): net salary change of at least 10% (*check*) or 20% (*high*), zero net pay, a paid employee with no payslip this month, loss-of-pay days up by 2+ or at least half the month, overtime above 25% of fixed pay, drafts that no longer match current records (*stale*), manual adjustments, salary-structure changes, new joiners and leavers
- **Reasons from recorded data:** salary-structure changes (who and when), loss-of-pay days split into unpaid leave, days with no check-in/leave/WFH (with dates) and days before joining, approved overtime records, bonus source, holidays changing working days, role changes, payslip notes and manual adjustments
- **Review:** the administrator records a review (confirming flagged employees or adding a note). Editing, recalculating or generating a draft afterwards requires a new review. Reviews and finalisation are audited
- The threshold is configurable (`PAYROLL_VARIANCE_THRESHOLD_PERCENT`)

### 1.10 Payslips (employee)

- List of the employee's own **paid** payslips, filtered by year, with totals
- View a payslip on screen: working days, loss-of-pay days, paid days, overtime hours, every earning and deduction, and net salary
- Download as a professionally formatted **PDF** (A4, company name from settings)
- Employees never see draft payslips or anyone else's payslips

### 1.11 Reports and Excel export (admin)

- Monthly payroll totals for a selected year: payslip count, gross, deductions, net, drafts and paid, shown as a chart and table
- **Cost by department** for a selected month: headcount, gross and net
- **Analytics page:** payroll cost, net pay and overtime cost trends, late check-ins and late rate, absenteeism (loss-of-pay days ÷ working days), leave days and leave utilisation by type, headcount with joiners and leavers, a department breakdown, and every summary compared with the previous period of the same length. Filters: month range (up to 24 months) and department; empty states when there is no data; Excel export of the analytics (three sheets)
- **Excel (.xlsx) reports built with OpenPyXL** for employees, attendance (with late minutes and a per-employee summary), leave (with per-employee day totals), overtime and payroll (register + department totals). Filters: date range or payroll year/month, department, employee, status, leave type, late-only. Styled headers, frozen header row, auto-filter, totals rows, ₹ number formats; user text is always stored as text (no formula injection). Every export is audited

### 1.12 Holiday calendar

- Month calendar view for everyone
- **Admin:** click a day to add a holiday; edit or delete it. Types: *Fixed* or *Tentative*, with an optional description. One holiday per date.
- Employees are notified when a holiday is added, changed or removed
- Holidays are excluded from payroll working days

### 1.13 Announcements

- Admins publish company announcements (title and message) and can delete them
- All employees are notified; the latest announcements also appear on both dashboards

### 1.14 Private messages (chat)

- One-to-one conversations between an administrator and an employee
- Admins pick any active employee to start a conversation; employees reply in conversations started with them
- Messages are up to 4000 characters, marked as read when opened, and refresh automatically every 8 seconds while the page is visible
- The other person gets a notification that links straight to the conversation

### 1.15 Notifications

- **Admins send notifications** to all active employees, one department or selected employees, with an optional **expiry**; expired notifications disappear from inboxes. A *Sent notifications* table shows delivered and read counts, expiry status, and lets admins withdraw a notification
- A bell in the top bar with an unread badge, refreshed every minute
- Notifications are created for: leave, WFH and document submissions and decisions; attendance check-in/out (to admins); new holidays and announcements; new chat messages; welcome/onboarding; salary structure changes; and payslips being published
- Each notification links to the relevant page. Mark one, or all, as read. The latest 100 are kept in view.

### 1.16 Audit log (admin)

- Append-only record of important activity in every module: sign-in success/failure/refusal, sign-out, password reset and change, Google link/unlink; employee create/update/deactivate and department renames; leave, WFH, document and overtime decisions; shift and assignment changes; holiday and announcement changes; office-location changes; salary structures; payroll run, adjust, recalculate, delete, finalise; CSV/Excel exports; notification sends/withdrawals; AI knowledge-base edits
- Each entry stores the user, **module**, action, record, summary, date/time and IP address
- Filter by module and date range, search by summary, user or IP, paginate

### 1.16a AI-powered assistance (Google Gemini)

- **Database-connected answers:** every question is routed by the backend, which identifies the user from the session, fetches only their own relevant records (latest finalised payslip with a computed breakdown and month-on-month comparison, salary structure, leave balance and requests, WFH requests, overtime, attendance, documents) and verified guide topics, then asks Gemini to explain them. Requests for another person's data are refused without calling Gemini. If Gemini is unavailable, personal questions are answered directly from the records. See [Feature Guide §27.1](docs/FEATURES.md#271-how-answers-are-grounded-database-connected-assistant)
- **AI Chatbot:** answers questions about the organisation, how to use PayrollPro and the user's own records, with saved conversation history
- **AI Leave Policy Assistant:** explains leave types, entitlements, the employee's live balance and requests, system rules and the organisation's own leave policy text
- **AI Salary Breakdown Assistant:** explains salary components, deductions and net pay from the employee's real salary structure and payslips (optionally a chosen payslip); admins can ask about a chosen employee
- **AI Attendance Insight Generator:** computes attendance rate, absences, late days/minutes (and by weekday), typical check-in time, hours worked and unapproved overtime for a period, then asks Gemini for a written summary, patterns and suggestions; follow-up questions supported. Admins can analyse one employee or the whole company. The figures work even without an API key
- **Chat history:** saved in PostgreSQL in *Pinned* and *Recent chats* sections; a three-dot menu on each chat offers **Rename** (inline, Enter saves, Escape cancels), **Pin / Unpin** and **Delete**; **Search** finds chats by title, your questions or the assistant's answers, with highlighted snippets
- **Knowledge base (admin):** company overview, leave policy and FAQ text the assistants may quote
- Grounded and private: the model only receives the asking user's own records (or what an admin chose) plus system rules; the API key stays on the server; per-user hourly limit; clear error messages when Gemini is unavailable

### 1.16b Attendance corrections

- Employees cannot edit attendance. On **Attendance & shift** they click **Request correction** (or *Correct* on a day) and choose the date, the type (*missed check-in*, *missed check-out*, *incorrect times*, *worked but no attendance recorded*), the correct times (check-out may be the next day for overnight shifts) and a reason
- Validation: no future dates or times, within the last 60 days (`ATTENDANCE_CORRECTION_WINDOW_DAYS`), not before joining, not in a month whose payroll is finalised, check-out after check-in and within 24 hours, and the type must match what is recorded. One pending request per employee and day (database constraint)
- Employees see the status and the administrator's response and can cancel while pending
- **Admin page *Attendance corrections*:** filter by status, type, department, dates and search; recorded and requested values side by side; approve (optional note) or reject (reason required). Approval updates the attendance record, marks it *Corrected* and recalculates late minutes from the shift; the audit log stores the original value, corrected value, approver, reason and time

### 1.16c Team calendar

- **Company → Team calendar** shows approved leave, approved work from home, shifts and holidays in a month grid (with an event list below; phones get the list only), month navigation and event-type toggles
- **Administrators:** every active employee, filters for employee, department, event type and a custom date range (up to 62 days); explicit shift assignments are shown and the default shift is noted
- **Employees:** *My schedule* (own leave with type, WFH, own shift, holidays) and *Team availability* (colleagues in their own department shown only as *On leave* / *Working from home*, never the leave type or reason)

### 1.16d Employee onboarding

- Each new employee gets a checklist computed from data PayrollPro already stores: first and last name, email, phone, department and designation, postal address (optional setting), profile photo (optional), required documents (default: identity and address proof; a document counts once **verified** and not expired) and the salary structure. No new personal fields are collected
- The employee sees the checklist and links on their dashboard; when everything is provided the administrators are notified once (*Ready for review*)
- **Admin page *Onboarding*:** tabs for open, ready, in progress and completed; missing items per employee; view checklist; send a reminder; **mark complete** (refused while items are missing); reopen with a reason; checklist settings. Employees who existed before this feature were marked completed by the migration
- Create, edit, deactivate and reactivate employees work as before; deactivation and reactivation now record the date and are audited

### 1.16e Document expiry and reminders

- Documents can have an **expiry date** (employee at upload, administrator during verification or later). Expiry status (*Valid*, *Expiring soon*, *Expired*, *No expiry*) is shown separately from the review status; both document pages filter by expiry, and dashboards show counts
- **Automatic reminders** (Settings → *Automatic reminders*, admin): document reminders to the employee and administrators on configurable days before expiry (default 30, 7 and 1) and once on expiry; a daily digest to administrators of leave, WFH, corrections, overtime and documents waiting at least *N* days; a weekly onboarding reminder to employees with missing items. Each reminder is sent once (logged). Reminders run automatically when a dashboard is opened (at most every 6 hours), from **Send due reminders now**, or from `python manage.py send_reminders` (schedule it daily)

### 1.16f Notification preferences and audit filters

- **Settings → Notifications:** switch optional kinds off (announcements, attendance, chat, corrections, documents, holidays, leave, overtime, reminders, shifts, WFH). Security alerts (password reset/change, Google connect/disconnect), payslip and employee-record messages, onboarding and messages sent by an administrator are always delivered
- The notifications page has *All / Unread* tabs (with the unread count) and a type filter
- **Audit log:** filter by date range, employee (the person the action was about, or who did it), action and module (filter options come from the recorded entries); each entry shows the affected employee. Audit entries are append-only: there is no write API and the model refuses updates and deletes

### 1.17 Profile and settings

- **Profile:** name, email, phone, address and profile photo (JPG/PNG, up to 2 MB, real image check). Employees also see their employment details.
- **Settings:** change password; connect or disconnect a Google account
- **Light / dark theme** toggle, remembered in the browser and applied before the page renders (no flash)
- Responsive layout with a collapsible sidebar for phones and tablets

---

## 2. Payroll rules

All money is calculated with `Decimal` and rounded half-up to 2 places (₹).

| Item | Rule |
| --- | --- |
| Fixed gross | Basic + HRA + DA + conveyance + medical + special + other allowance |
| Working days | Weekdays (Mon–Fri by default, `PAYROLL_WORKING_WEEKDAYS`) minus holidays in the calendar |
| Paid ("covered") day | A working day on which the employee checked in, was on approved **paid** leave, or had approved WFH |
| Loss of pay (LOP) days | Working days not covered, plus approved unpaid ("Other") leave days, plus working days before the joining date |
| No-attendance mode | Skips the attendance check; only unpaid leave and joining date cause LOP |
| LOP deduction | Fixed monthly gross × LOP days ÷ working days |
| Provident fund | PF % × *earned* PF wage, i.e. (basic + DA) reduced for LOP |
| Professional tax, TDS | Fixed monthly amounts from the salary structure, pro-rated by paid days. The system does not calculate income-tax slabs. |
| Other deductions | Taken in full (not pro-rated) |
| Overtime | Sum of the employee's **approved** overtime records in the month (hours × rate). Attendance time beyond the shift (or 8 h) only becomes overtime once a record is approved |
| Bonus | The salary structure's monthly bonus, paid in full (not reduced for LOP, not in the PF wage); admins can change it on a draft payslip |
| Gross earnings | All seven components + overtime + bonus |
| Net salary | Gross − (PF + professional tax + TDS + other deductions + LOP deduction) |

---

## 3. Project structure

```
Employee_Payroll_Management_System/
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example            # copy to .env and fill in
│   ├── config/                 # Django settings, root URLs, WSGI/ASGI
│   ├── accounts/               # users, employees, attendance, leave, WFH, documents,
│   │   │                       # holidays, announcements, chat, notifications, audit log
│   │   ├── auth_views.py       # CSRF, register, login/logout, password reset & change
│   │   ├── google_auth.py      # Sign in with Google (OAuth 2.0 + PKCE + OpenID Connect)
│   │   ├── views.py            # REST API for the features above
│   │   ├── throttling.py       # login / OTP lockout
│   │   ├── audit.py            # audit-log helper
│   │   └── notifications.py    # in-app notification helpers
│   ├── payroll/                # salary structures, payslips, payroll runs, reports, dashboards
│   │   ├── calculator.py       # all payroll maths
│   │   ├── pdf.py              # payslip PDF (ReportLab)
│   │   ├── excel.py            # Excel reports (OpenPyXL)
│   │   └── dashboard.py        # admin and employee dashboard APIs
│   ├── workforce/              # shifts, shift assignments, overtime records, late-minute rules
│   ├── assistant/              # Gemini AI assistants (gemini.py client, context.py grounding)
│   └── media/                  # uploaded photos and documents (not in git)
└── frontend/
    ├── index.html              # sign in / register / forgot password
    ├── admin-*.html            # admin pages
    ├── employee-*.html         # employee pages
    ├── announcements.html, chat.html, notifications.html, settings.html, google-callback.html
    ├── css/app.css             # single stylesheet (light and dark themes)
    └── js/                     # app.js (shared shell, API client, UI helpers) + one script per page
```

### Pages

| Admin | Employee | Shared |
| --- | --- | --- |
| `admin-dashboard.html` – Dashboard | `employee-dashboard.html` – Dashboard | `index.html` – Sign in / Register |
| `employee-management.html` – Employees | `employee-attendance.html` – Attendance | `announcements.html` – Announcements |
| `admin-attendance.html` – Attendance | `employee-leave.html` – Leave | `chat.html` – Messages |
| `admin-leave.html` – Leave requests | `employee-wfh.html` – Work from home | `notifications.html` – Notifications |
| `admin-leave-policy.html` – Leave policy | | |
| `admin-wfh.html` – Work from home | `employee-documents.html` – Documents | `settings.html` – Settings |
| `admin-documents.html` – Documents | `employee-payslips.html` – Payslips | `google-callback.html` – Google sign-in return |
| `admin-payroll.html` – Payroll runs | `employee-holidays.html` – Holiday calendar | |
| `admin-salary.html` – Salary structures | `employee-profile.html` – Profile | |
| `admin-reports.html` – Reports + Excel | `overtime.html` – Overtime (shared) | `ai-assistant.html` – AI assistant |
| `admin-shifts.html` – Shifts | | |
| `admin-payroll-review.html` – Payroll variance review | `calendar.html` – Team calendar (shared) | |
| `admin-analytics.html` – Analytics | | |
| `admin-corrections.html` – Attendance corrections | | |
| `admin-onboarding.html` – Onboarding | | |
| `admin-holidays.html` – Holiday calendar | | |
| `admin-audit.html` – Audit log | | |
| `admin-profile.html` – Profile | | |

---

## 4. Setup

### Requirements

- Python 3.12 or newer (Django 6.1)
- PostgreSQL
- A modern browser (location access is needed for attendance)

### 4.1 Backend

```bash
cd backend
python -m venv venv                 # skip if you already have one
venv\Scripts\activate               # Windows (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env              # macOS/Linux: cp .env.example .env — then edit .env
python manage.py migrate            # creates/updates the database tables; existing data is kept
python manage.py createsuperuser    # first administrator
python manage.py runserver          # API at http://127.0.0.1:8000/api/
```

Create the PostgreSQL database named in `DB_NAME` (default `employee_payroll`) before running `migrate`.

### 4.2 Frontend

The frontend is static files. Serve the `frontend` folder on port 5500, either with VS Code Live Server or:

```bash
cd frontend
python -m http.server 5500
```

Open `http://127.0.0.1:5500/index.html`.

Use the **same hostname** for the frontend and the API (`127.0.0.1` for both, not `localhost` for one of them) so the session cookie works. The frontend finds the API automatically at `<same host>:8000/api`.

---

## 5. Configuration (`.env`)

`backend/.env` holds all secrets and is ignored by git. Start from `backend/.env.example`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | — | Long random string. Required when `DJANGO_DEBUG=False`. |
| `DJANGO_DEBUG` | `False` | `True` for local development |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` in debug | Comma-separated host names |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | local dev origins | Frontend origin(s), needed for other origins and production |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `employee_payroll`, `postgres`, –, `localhost`, `5432` | PostgreSQL connection |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | console backend | Email for password-reset codes. Without it, codes are printed in the server console. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | empty | Enables Google sign-in |
| `GOOGLE_REDIRECT_URI` | `http://127.0.0.1:8000/api/auth/google/callback/` | Must match Google Cloud Console exactly |
| `FRONTEND_URL` | `http://127.0.0.1:5500` in debug | Where the browser returns after Google sign-in |
| `COMPANY_NAME` | `PayrollPro` | Shown on PDF payslips |
| `PAYROLL_WORKING_WEEKDAYS` | `0,1,2,3,4` | Working weekdays (0 = Monday … 6 = Sunday) |
| `PAYROLL_STANDARD_DAILY_HOURS` | `8` | Standard day for employees without a shift (time beyond it is candidate overtime) |
| `PAYROLL_VARIANCE_THRESHOLD_PERCENT` | `10` | Net-salary change that the variance review flags (twice this is *high*) |
| `ATTENDANCE_CORRECTION_WINDOW_DAYS` | `60` | How many days back an employee may request an attendance correction |
| `GEMINI_API_KEY` | empty | Google Gemini API key; empty switches the AI features off |
| `GEMINI_MODEL` | `gemini-flash-latest` | Gemini model name; `python manage.py gemini_check` lists the models your key can use and tests this one |
| `GEMINI_TIMEOUT_SECONDS`, `AI_MAX_REQUESTS_PER_HOUR` | `30`, `40` | AI request timeout and per-user hourly limit |
| `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCKOUT_SECONDS` | `5`, `900` | Brute-force lockout |
| `SESSION_COOKIE_AGE` | `604800` (7 days) | "Remember me" session length in seconds |
| `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_HSTS_SECONDS` | `True`, `31536000` | HTTPS settings used when debug is off |
| `DB_CONN_MAX_AGE`, `DJANGO_LOG_LEVEL` | `60`, `WARNING` | Database connection reuse, log level |

The time zone is `Asia/Kolkata`.

> **Note:** An older version of `settings.py` contained a hard-coded database password and secret key. If you used those, change that PostgreSQL password and generate a new secret key:
> `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"`

---

## 6. Google sign-in (optional)

The "Continue with Google" button works only after you add Google credentials. Without them the button is shown disabled and password login is unaffected.

**Google Cloud Console (one time)**
1. Go to https://console.cloud.google.com and create a project.
2. *APIs & Services → OAuth consent screen*: choose **External**, fill in the app name and your email. While in *Testing*, add your Gmail under **Test users**.
3. *APIs & Services → Credentials → Create credentials → OAuth client ID → Web application*.
4. **Authorized JavaScript origins:** `http://127.0.0.1:5500`
5. **Authorized redirect URIs:** exactly `http://127.0.0.1:8000/api/auth/google/callback/`
6. Copy the Client ID and Client secret into `backend\.env` (never into frontend files or git):
   ```
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   ```
7. Restart the Django server. Use `127.0.0.1` (not `localhost`) everywhere so cookies stay on one host.

**How it works:** OAuth 2.0 authorization-code flow with PKCE, `state` and `nonce`. The code is exchanged server-to-server (the client secret never reaches the browser), and the ID token's signature, audience, issuer, expiry and nonce are verified with Google's public keys.

**Rules the app enforces**
- New Google users become plain **Employee** accounts (an admin still completes onboarding). Google never creates an admin.
- A Google account is identified by Google's stable ID, never by email, and is never auto-linked by email. If the email already belongs to a user, sign in with the password and use *Settings → Connect Google account*.
- Only Google accounts with a verified email are accepted. Inactive employees are still blocked.
- Admins can use Google only after linking it from Settings.
- Google-only accounts have no password; use "Forgot password" to add one before disconnecting Google.

**Production:** use HTTPS URLs for the origin and redirect URI, and set `DJANGO_DEBUG=False`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` and `DJANGO_ALLOWED_HOSTS` to your real https domains.

---

## 7. Getting started as an administrator

1. Sign in with the superuser account and choose **Administrator**.
2. **Employees:** add employees, or complete the records of accounts that registered themselves (listed as pending).
3. **Salary structures:** set each employee's pay. Employees without one are skipped in payroll.
4. **Attendance → Office location:** set the office coordinates and radius, then enable attendance so employees can check in.
5. **Shifts:** create shifts (mark one as the default) and assign employees, so late minutes and overtime use the right working hours.
6. **AI assistant → Knowledge base** (optional): add your company overview and leave policy, and set `GEMINI_API_KEY` in `backend/.env` to switch on the AI answers.
7. **Leave policy:** review the leave types and days per year, set the leave year and rules, and add any other types your organisation offers.
8. **Holiday calendar:** add the year's holidays so they are excluded from working days.
9. Each month: approve overtime on **Overtime** (optionally *From attendance* first). After the month ends, **Payroll runs → Run payroll** creates drafts. Review and adjust them, then **Finalise** to publish them to employees. Download PDFs or export the CSV register.
10. Use **Reports** for monthly and department totals and Excel exports, and **Audit log** to see who changed what.

---

## 8. API reference

All endpoints are under `/api/`. Authentication is by session cookie. Unsafe requests (POST/PUT/PATCH/DELETE) must send the CSRF token from `GET /api/csrf/` in the `X-CSRFToken` header. Unauthenticated requests get `401`. List endpoints marked *paginated* return pages when `?page=` (and optional `page_size`, max 100) is sent, and the full list otherwise.

### Authentication

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `csrf/` | Get the CSRF token and cookie |
| POST | `register/` | Register an employee account |
| POST | `login/` | Sign in (`username` or email, `password`, `role`, `remember_me`) |
| POST | `logout/` | Sign out |
| POST | `password/forgot/` | Send a password-reset code |
| POST | `password/verify-otp/` | Verify the code, returns a reset token |
| POST | `password/reset/` | Set a new password with the reset token |
| POST | `password/change/` | Change password (signed in) |
| GET | `auth/google/config/` | Whether Google sign-in is configured |
| POST | `auth/google/start/` | Start Google sign-in / sign-up / link |
| GET | `auth/google/callback/` | Google redirect target |
| GET, DELETE | `auth/google/link/` | Google link status / disconnect |

### People and requests

| Method | Endpoint | Who | Description |
| --- | --- | --- | --- |
| GET, POST | `employees/` | Admin | List (search, filter, sort, *paginated*) / add employee |
| GET | `employees/meta/` | Admin | Departments and pending self-registered accounts |
| GET, PUT, DELETE | `employees/<id>/` | Admin | View / update / deactivate |
| GET, PUT | `profile/` | All | Own profile (multipart for photo) |
| GET, POST | `leaves/` | All | List (admin: all, *paginated*) / apply |
| GET | `leaves/balance/` | All | Leave balance (`?year=`, admin `?employee_id=`) |
| PUT | `leaves/<id>/status/` | Admin | Approve / reject |
| DELETE | `leaves/<id>/` | Employee | Cancel own pending request |
| GET, POST | `leave-types/` | All / Admin | Active leave types (admin `?all=true` includes inactive and request counts) / create |
| GET, PUT, PATCH, DELETE | `leave-types/<id>/` | Admin | View / edit, activate or deactivate / delete if unused |
| GET, PUT | `leave-policy/` | All / Admin | Leave rules and current leave year / update |
| POST | `leave-policy/carry-forward/` | Admin | Carry unused days into `year` |
| PUT | `leave-policy/balances/` | Admin | Adjust one employee's balance (`employee_id`, `leave_type_id`, `year`, `adjustment`, `note`) |
| GET, POST | `wfh/` | All | List / request |
| PUT, DELETE | `wfh/<id>/` | Admin / Employee | Review / cancel own pending request |
| GET, POST | `documents/` | All | List / upload (employees only) |
| DELETE | `documents/<id>/` | Employee | Delete own pending document |
| GET | `documents/<id>/file/` | Owner, Admin | Download the private file |
| PUT | `documents/<id>/review/` | Admin | Verify / reject |

### Attendance, calendar and communication

| Method | Endpoint | Who | Description |
| --- | --- | --- | --- |
| GET, PUT | `attendance/settings/` | Admin | Office location, radius, enabled |
| GET | `attendance/status/` | All | Today's record and whether attendance is enabled |
| POST | `attendance/check-in/`, `attendance/check-out/` | Employee | Mark attendance with `latitude`, `longitude` |
| GET | `attendance/history/` | All | Own recent records (`?limit=`, max 90) |
| GET | `attendance/` | Admin | All records (`date`, `from`, `to`, `search`, *paginated*) |
| GET, POST | `holidays/` | All / Admin | List / add |
| PUT, DELETE | `holidays/<id>/` | Admin | Edit / delete |
| GET, POST | `announcements/` | All / Admin | List / publish |
| DELETE | `announcements/<id>/` | Admin | Delete |
| GET | `chat/employees/` | Admin | Active employees to message |
| GET, POST | `chat/conversations/` | All / Admin | List / start conversation |
| GET, POST | `chat/conversations/<id>/messages/` | Participants | Read / send messages |
| GET | `notifications/` | All | Latest 100 and unread count |
| POST | `notifications/<id>/read/` | All | Mark one as read |
| POST | `notifications/read-all/` | All | Mark all as read |
| GET | `audit-logs/` | Admin | Audit log (`entity_type`, `action`, `search`, *paginated*) |

### Payroll and dashboards

| Method | Endpoint | Who | Description |
| --- | --- | --- | --- |
| GET | `payroll/salary-structures/` | Admin | Employees with their structures (`configured`, `status`, `search`, *paginated*) |
| GET, PUT | `payroll/salary-structures/<employee id>/` | Admin | View / set structure |
| GET | `payroll/my-salary-structure/` | Employee | Own structure |
| GET | `payroll/payslips/` | All | Payslips with totals (admin: all; employee: own paid) |
| GET, PATCH, DELETE | `payroll/payslips/<id>/` | All / Admin | View / adjust draft / delete draft |
| POST | `payroll/payslips/<id>/recalculate/` | Admin | Rebuild a draft |
| GET | `payroll/payslips/<id>/pdf/` | Owner, Admin | PDF (`?inline=1` to view in browser) |
| POST | `payroll/run/` | Admin | Generate drafts (`year`, `month`, `lop_mode`, optional `employee_ids`) |
| POST | `payroll/finalize/` | Admin | Mark drafts as paid (optional `payslip_ids`) |
| GET | `payroll/export/` | Admin | CSV register (`year`, `month`) |
| GET | `payroll/reports/` | Admin | Yearly monthly totals and department breakdown |
| GET | `dashboard/admin/` | Admin | Admin dashboard data |
| GET | `dashboard/employee/` | All | Employee dashboard data |
| GET | `reports/excel/<employees\|attendance\|leave\|overtime\|payroll>/` | Admin | Excel report (filters: `from`, `to`, `year`, `month`, `department`, `employee`, `status`, `leave_type`, `late`, `search`) |

### Shifts, overtime, notifications sending and AI

| Method | Endpoint | Who | Description |
| --- | --- | --- | --- |
| GET, POST | `shifts/` | Admin | List / create shifts |
| GET, PUT, PATCH, DELETE | `shifts/<id>/` | Admin | View / edit / delete (refused when assigned) |
| GET, POST | `shifts/assignments/` | Admin | Shift records (`employee`, `shift`, `on`, `search`, *paginated*) / assign employees (`employee_ids`, `shift_id`, `start_date`, `end_date`, `replace`) |
| PUT, DELETE | `shifts/assignments/<id>/` | Admin | Edit / remove an assignment |
| GET | `shifts/my/` | All | Own current shift and history |
| GET, POST | `overtime/` | All | List with totals (admin: all; employee: own) / claim or record overtime |
| PUT, PATCH, DELETE | `overtime/<id>/` | Owner, Admin | Edit / cancel a pending record |
| PUT | `overtime/<id>/review/` | Admin | Approve / reject |
| POST | `overtime/generate/` | Admin | Pending records from attendance for `year`/`month` |
| GET, POST | `notifications/broadcasts/` | Admin | Sent notifications with read counts / send (`target_type`, `department`, `employee_ids`, `expires_at`) |
| DELETE | `notifications/broadcasts/<id>/` | Admin | Withdraw |
| GET | `employees/departments/` | Admin | Departments with headcount and designations |
| POST | `employees/departments/rename/` | Admin | Rename a department or designation for all employees |
| GET | `ai/status/` | All | Whether Gemini is configured |
| GET, POST | `ai/conversations/` | All | Own conversations, pinned first (`feature`; `search` = 2–100 characters, matches titles and message text and returns `match` snippets) / start one (`feature`: CHAT, LEAVE, SALARY; admin `subject_id`; `payslip_id`) |
| GET, PATCH, DELETE | `ai/conversations/<id>/` | Owner | Messages / rename (`title`) and pin or unpin (`pinned`; 409 if already in that state) / delete |
| POST | `ai/conversations/<id>/messages/` | Owner | Ask a question (`message`) |
| POST | `ai/attendance-insights/` | All | Statistics + AI insights (`from`, `to`; admin `scope` EMPLOYEE/COMPANY, `subject_id`) |
| GET | `ai/attendance-insights/stats/` | All | Statistics only (no AI key needed) |
| GET, PUT | `ai/knowledge/` | Admin | AI knowledge base |

### Variance review, corrections, calendar, onboarding, reminders and analytics

| Method | Endpoint | Who | Description |
| --- | --- | --- | --- |
| GET | `payroll/variance/` | Admin | Comparison with the previous month (`year`, `month`, `flagged=true`) |
| POST | `payroll/variance/review/` | Admin | Record a review (`year`, `month`, `note`, `acknowledge_flags`); required before `payroll/finalize/` (409 `review_required` otherwise) |
| GET | `reports/analytics/` | Admin | Trends and comparisons (`from`, `to` as YYYY-MM, `department`) |
| GET | `reports/excel/analytics/` | Admin | Analytics workbook |
| GET, POST | `attendance/corrections/` | All | Own requests (admin: all; `status`, `correction_type`, `department`, `employee`, `from`, `to`, `search`, *paginated*) / request a correction (employee) |
| POST | `attendance/corrections/<id>/review/` | Admin | Approve / reject (`status`, `review_note`) |
| POST | `attendance/corrections/<id>/cancel/` | Owner | Cancel a pending request |
| GET | `calendar/` | All | Events (`start`, `end`, `types`; admin `department`, `employee`; employee `scope` mine/team) |
| GET | `onboarding/` | Admin | Checklists (`state` OPEN/READY/IN_PROGRESS/COMPLETED, `search`, `department`) |
| GET | `onboarding/me/` | All | Own checklist |
| GET, PUT | `onboarding/settings/` | Admin | Required items |
| POST | `onboarding/<employee id>/complete/`, `reopen/`, `remind/` | Admin | Complete (refused while items are missing), reopen (`note`), remind |
| PUT | `documents/<id>/expiry/` | Admin | Set or clear the expiry date |
| GET, PUT | `notifications/preferences/` | All | Optional notification kinds (`preferences`: {kind: true/false}) |
| GET, PUT | `reminders/settings/` | Admin | Reminder days, pending threshold, on/off |
| POST | `reminders/run/` | Admin | Send due reminders now |
| GET | `audit-logs/meta/` | Admin | Modules and actions for the filters (`audit-logs/` also accepts `employee`, `actor`, `action`) |

The Django admin site is available at `http://127.0.0.1:8000/admin/`.

---

## 9. Security

- Session authentication with HttpOnly, SameSite=Lax cookies; CSRF required on every unsafe request
- Secure cookies, HTTPS redirect, HSTS and content-type sniffing protection when `DJANGO_DEBUG=False`
- All secrets in `.env` (git-ignored); the server refuses to start without a secret key in production
- Role checks on every admin endpoint; employees can only see their own data
- Login and OTP brute-force lockout; generic login and reset messages that don't reveal whether an account exists
- Reset codes are stored hashed, expire after 10 minutes and allow 5 attempts
- Uploaded files are checked by size and real file signature; employee documents are never publicly served
- CSV export neutralises spreadsheet formulas
- Google sign-in uses PKCE, state and nonce, verifies the ID token, and never links accounts by email
- Sensitive admin actions are recorded in the audit log with the user and IP address
- For multi-process or multi-server deployments, configure a shared cache (e.g. Redis) so lockouts apply across processes

---

## 10. Tests

```bash
cd backend
python manage.py test      # needs a PostgreSQL user allowed to create a test database
```

Reminders can be scheduled daily (for example with Windows Task Scheduler):

```bash
python manage.py send_reminders
```

The suite (192 tests) covers the payroll variance review and the review required before finalising, attendance correction requests, the team calendar, onboarding checklists, document expiry and reminders, notification preferences, audit filters and append-only audit entries, analytics and its Excel export, the admin-controlled leave policy (types, limits, leave year, carry forward, adjustments, validation, cancellation), AI chat rename/pin/search, authentication and permissions, employees, leave, attendance and late minutes, shifts, overtime approval and its payroll integration, DA/bonus calculations, documents, Google sign-in, notifications with expiry, audit coverage, Excel exports, the AI assistants (with the Gemini HTTP call stubbed), and the payroll calculator, runs, adjustments, finalisation, PDFs, exports and reports. Uploaded test files go to a temporary folder, not `backend/media/`.