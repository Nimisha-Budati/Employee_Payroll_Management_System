# PayrollPro – SRS Compliance Report

Project: *Employee Payroll Management System with AI-Powered Assistance* (Team HANOVA)
Report date: 19 October 2026
Basis: the SRS (sections 1–3), the existing source code and database models, and the [Feature Guide](FEATURES.md).

Status key: ✅ **Implemented and tested** · 🟡 **Partially implemented** · ❌ **Missing**

---

## 1. Checklist before this work (from the source code)

| SRS | Requirement | Status found | Evidence in code |
| --- | --- | --- | --- |
| 3.1 | Login, secure auth, sessions, email OTP reset, role restriction | ✅ | `accounts/auth_views.py`, throttling, 57 account tests |
| 3.2 | Add/update/view employees, status, search/filter | ✅ | `accounts/views.py` employee endpoints + tests |
| 3.2 | Manage departments and designations | 🟡 | Free-text fields with suggestions only; no way to manage them |
| 3.3 | Mark attendance, check-in/out, history, admin view, working hours | ✅ | GPS check-in/out, `worked_minutes` |
| 3.3 | Late minutes (monitor and report) | ❌ | No shift or late-minute field anywhere |
| 3.4 | Leave apply/approve/reject/history | ✅ | Leave endpoints, balances, tests |
| 3.5 | WFH submit/approve/reject/history | ✅ | WFH endpoints |
| 3.6 | Shift definition, assignment, storage | ❌ | No model, API or page |
| 3.7 | Overtime records, amounts, approval status, payroll inclusion | 🟡 | Overtime auto-paid from attendance time; no records, no approval |
| 3.8 | Basic, HRA, **DA**, **Bonus**, OT rate, PF, PT, IT, other deductions | 🟡 | No DA; bonus only as a manual per-payslip adjustment |
| 3.9 | Payroll generation, gross/deductions/net, attendance & leave | ✅ | `payroll/calculator.py` + tests |
| 3.9 | Include **approved** overtime | ❌ | Unapproved attendance overtime was paid |
| 3.10 | Monthly payslips, details, PDF download | ✅ | ReportLab PDF + tests |
| 3.11 | Upload/view/manage documents | ✅ | Private document storage + tests |
| 3.12 | Announcements | ✅ | |
| 3.12 | Admin sends notifications to target employees, with **expiry** | ❌ | Only automatic notifications; no expiry, no targeting |
| 3.13 | Holiday calendar | ✅ | |
| 3.14 | Employee/attendance/leave/payroll reports, **Excel export** | 🟡 | Payroll CSV only; no OpenPyXL, no employee/attendance/leave reports |
| 3.15 | Analytics: employee, attendance, payroll, **leave** statistics | 🟡 | No leave statistics or attendance trend |
| 3.16 | Search/filter employees, attendance, leave, payroll, **documents** | 🟡 | Documents and WFH had no search |
| 3.17 | Audit: user, action, **module**, date/time, IP | 🟡 | Only employee/salary/payroll actions; no module field |
| 3.18.1 | AI Chatbot with conversation history | ❌ | No Gemini integration |
| 3.18.2 | AI Leave Policy Assistant | ❌ | |
| 3.18.3 | AI Salary Breakdown Assistant | ❌ | |
| 3.18.4 | AI Attendance Insight Generator | ❌ | |
| — | Google OAuth sign-in | ✅ | `accounts/google_auth.py`, 35 tests |

Existing test suite at the start: 85 tests, 84 passing. 1 intermittent Windows error came from a test that left a document file open while deleting it from the real `media/` folder.

---

## 2. Checklist after this work

| SRS | Requirement | Status | How it is met | Tests |
| --- | --- | --- | --- | --- |
| 3.1 | Authentication, sessions, OTP reset, RBAC | ✅ | Unchanged; sign-in, failures, sign-out and password events now audited | existing 57 + `test_srs.AuditCoverageTests` |
| 3.1 | Google OAuth | ✅ | Unchanged; link, unlink and Google sign-in audited | `accounts/test_google.py` (35) |
| 3.2 | Employee management | ✅ | Unchanged + Excel export | existing |
| 3.2 | Departments and designations | ✅ | `GET /employees/departments/`, rename/merge across employees, Departments dialog | `SearchAndDepartmentTests` |
| 3.3 | Attendance, history, working hours | ✅ | Unchanged | existing |
| 3.3 | **Late minutes** | ✅ | Shift snapshot, scheduled start and `late_minutes` stored at check-in; filters, per-employee summary, dashboards, Excel | `workforce.tests.LateMinuteTests` |
| 3.4 | Leave | ✅ | Decisions now audited; Excel leave report | existing + Excel tests |
| 3.5 | WFH | ✅ | Admin search added; decisions audited | `SearchAndDepartmentTests`, `AuditCoverageTests` |
| 3.6 | **Shift management** | ✅ | `workforce` app: shifts (overnight, grace, break, default), bulk assignment with overlap/replace rules, employee shift records, admin page, employee view | `ShiftManagementTests` |
| 3.7 | **Overtime management** | ✅ | `OvertimeRecord` (hours, rate, amount, source, status, reviewer); claim, record, approve/reject, generate from attendance, lock after finalisation | `OvertimeTests` |
| 3.8 | **DA and bonus** | ✅ | `da` earning (part of gross, LOP and PF wage); monthly `bonus` paid in full, overridable per draft | `SalaryComponentTests` |
| 3.9 | Payroll incl. **approved overtime** | ✅ | Payroll pays only approved overtime; run reports pending overtime | `OvertimeTests`, existing payroll tests |
| 3.10 | Payslips + PDF | ✅ | DA line added to PDF, CSV and on-screen payslip | `SalaryComponentTests` (PDF) |
| 3.11 | Documents | ✅ | Admin search and type filter; review audited | `SearchAndDepartmentTests` |
| 3.12 | **Notifications with targets and expiry** | ✅ | Send to all / department / selected employees, optional expiry, read counts, withdraw | `NotificationBroadcastTests` |
| 3.13 | Holidays | ✅ | Changes audited | `AuditCoverageTests` |
| 3.14 | **Reports and Excel export** | ✅ | OpenPyXL employee, attendance, leave, overtime and payroll workbooks with filters | `payroll/test_excel.py` (5) |
| 3.15 | Analytics dashboard | ✅ | Leave statistics, 14-day attendance chart, lateness, overtime | existing dashboard test + browser check |
| 3.16 | Search and filtering | ✅ | Documents, WFH, shift records, overtime, audit (module/date/IP) added | `SearchAndDepartmentTests` |
| 3.17 | Audit logs incl. **module** | ✅ | `module` column (back-filled), recorded across 15 modules | `AuditCoverageTests`, module asserts in other tests |
| 3.18.1 | **AI Chatbot** + history | ✅* | Gemini `generateContent`; saved conversations | `assistant/tests.py` |
| 3.18.2 | **AI Leave Policy Assistant** | ✅* | Grounded in rules, entitlements, live balance, admin policy text | `assistant/tests.py` |
| 3.18.3 | **AI Salary Breakdown Assistant** | ✅* | Grounded in structure and payslips; admins can choose an employee | `assistant/tests.py` |
| 3.18.4 | **AI Attendance Insight Generator** | ✅* | Real statistics + Gemini narrative, follow-ups, company view for admins | `assistant/tests.py` |

**Update (AI grounding):** the assistants now retrieve the signed-in user's own records through `assistant/retrieval.py` (payslip breakdown and comparison computed by PayrollPro, leave, WFH, overtime, attendance, documents), use a verified knowledge base (`assistant/knowledge/guide.md`), refuse questions about other people, and answer from the records when Gemini is unavailable. 18 scenario tests in `assistant/test_retrieval.py` cover the required questions, privacy, missing data and Gemini outages (140 tests in total, all passing).

\* The AI code paths are tested with the HTTP call to Google replaced by a stub that returns Gemini's documented response format. **No live Gemini call was made**, because this environment has no `GEMINI_API_KEY`. See section 5.

---

## 3. Files added or changed

**Backend – new**
- `backend/workforce/` – `models.py` (Shift, ShiftAssignment, OvertimeRecord), `services.py` (shift lookup, late minutes, overtime totals), `serializers.py`, `views.py`, `urls.py`, `admin.py`, `apps.py`, `tests.py`, `migrations/0001_initial.py`
- `backend/assistant/` – `models.py` (AIConversation, AIMessage, AIKnowledgeBase), `gemini.py` (REST client), `context.py` (grounding and attendance statistics), `views.py`, `urls.py`, `admin.py`, `apps.py`, `tests.py`, `migrations/0001_initial.py`
- `backend/payroll/excel.py`, `backend/payroll/test_excel.py`, `backend/payroll/migrations/0003_salary_da_bonus.py`
- `backend/accounts/test_srs.py`, `backend/accounts/migrations/0018_attendance_shift_notification_expiry_audit_module.py`, `0019_fill_audit_module.py`

**Backend – changed**
- `config/settings.py` (apps, Gemini settings, temporary media folder for tests), `config/urls.py`, `requirements.txt` (`openpyxl`), `.env.example`
- `accounts/models.py` (attendance shift/late fields, notification expiry, NotificationBroadcast, audit module), `accounts/audit.py`, `accounts/views.py`, `accounts/serializers.py`, `accounts/urls.py`, `accounts/auth_views.py`, `accounts/google_auth.py`
- `payroll/models.py`, `payroll/calculator.py`, `payroll/serializers.py`, `payroll/views.py`, `payroll/pdf.py`, `payroll/dashboard.py`, `payroll/urls.py`, `payroll/tests.py` (closes file responses; fixes the Windows file-lock error)

**Frontend – new:** `admin-shifts.html` + `js/shifts.js`, `overtime.html` + `js/overtime.js`, `ai-assistant.html` + `js/ai.js`

**Frontend – changed:** `js/app.js` (navigation, icons, badges), `css/app.css` (checklist, AI chat, tabs), `admin-attendance.html` + `js/attendance.js`, `employee-attendance.html` + `js/my-attendance.js`, `js/salary.js`, `js/payslip-view.js`, `admin-reports.html` + `js/reports.js`, `notifications.html` + `js/notifications.js`, `admin-audit.html` + `js/audit.js`, `admin-dashboard.html` + `js/admin-dashboard.js`, `js/employee-dashboard.js`, `admin-documents.html` + `js/documents.js`, `js/requests.js`, `employee-management.html` + `js/employees.js`

**Docs:** `README.md`, `docs/FEATURES.md` (sections 22–28), this report.

Migrations are additive (new tables and nullable/defaulted columns). They were applied to the development database `employee_payroll` with no data changes, apart from back-filling the new audit `module` column.

---

## 4. Tests performed

| Check | Result |
| --- | --- |
| `python manage.py test` (PostgreSQL test database) | **122 tests, all passing** (85 existing + 37 new) |
| `manage.py check`, `makemigrations --check` | No issues, no missing migrations |
| `node --check` on every frontend script | No syntax errors |
| Browser walk-through on a separate QA database (`employee_payroll_qa`, served on `[::1]` so the real data was untouched) | Admin: dashboard analytics, attendance late filter and summary, Excel download (HTTP 200, valid .xlsx), shifts page, overtime approval through the UI, AI page (not-configured state, attendance figures), reports Excel form, notification sent to the Sales department with an expiry, audit log showing module and IP. Employee: attendance & shift card, notification received with expiry, approved overtime shown, admin page redirected, admin Excel API refused (403). Light/dark mode and phone width (375 px) checked; no console errors |

Not tested here: real GPS check-in in a browser (covered by API tests with coordinates), a live Gemini request, live Google OAuth, and real SMTP delivery.

---

## 5. Configuration still required

1. **Gemini:** set `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`) in `backend/.env`, restart Django, then ask one question on each AI tab to confirm the live connection. The configured model must exist for the key; the default is the `gemini-flash-latest` alias; `python manage.py gemini_check` lists usable models and tests the configured one (`gemini-2.5-flash` is no longer available to new keys).
2. **Install the new dependency** wherever the project is deployed: `pip install -r requirements.txt` (adds `openpyxl`).
3. **Run migrations** on other databases: `python manage.py migrate`.
4. **Shifts:** create shifts and mark one as the default. Until then, late minutes are not recorded ("—").
5. **AI knowledge base:** fill in the company overview and leave policy (AI assistant → Knowledge base).
6. **SMTP** for real OTP emails (`EMAIL_*` variables); otherwise codes print to the server console.
7. **Google OAuth** credentials, if Google sign-in is wanted (README section 6).

---

## 6. Remaining gaps and deviations

| Item | Notes |
| --- | --- |
| React.js frontend (SRS 2.1 / 2.4) | The project uses plain HTML/CSS/JavaScript. It was kept rather than rebuilt, as instructed; every SRS function is available in the current UI |
| Live AI verification | Only verified with stubbed HTTP responses; needs a real key (section 5) |
| WeasyPrint | Not used; ReportLab meets the PDF requirement (the SRS allows either) |
| Late minutes for past records | Attendance recorded before this change has no shift snapshot, so it shows "—" |
| Non-functional requirements (SRS 4) | Not load-tested; the SRS text supplied was cut off in section 4.1 |
| Lockout and AI rate limits | Use Django's default per-process cache; configure a shared cache (e.g. Redis) for multi-process deployments |
