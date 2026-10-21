# PayrollPro – Feature Guide

This guide describes every feature of PayrollPro in detail: what it is for, who can use it, how it works step by step, the rules the system enforces, who gets notified, and where to find it (page and API endpoint).

For installation and configuration, see the [README](../README.md).

---

## Contents

1. [Roles and access](#1-roles-and-access)
2. [Sign-in and accounts](#2-sign-in-and-accounts)
   - 2.1 Sign in · 2.2 Remember me · 2.3 Self-registration · 2.4 Forgot password (OTP) · 2.5 Change password · 2.6 Brute-force lockout · 2.7 Sessions and sign-out · 2.8 Sign in with Google
3. [Dashboards](#3-dashboards)
4. [Employee management](#4-employee-management)
5. [GPS attendance](#5-gps-attendance)
6. [Leave management](#6-leave-management)
7. [Work from home](#7-work-from-home)
8. [Documents](#8-documents)
9. [Salary structures](#9-salary-structures)
10. [Payroll runs](#10-payroll-runs)
11. [Payslips and PDF](#11-payslips-and-pdf)
12. [Reports and CSV export](#12-reports-and-csv-export)
13. [Holiday calendar](#13-holiday-calendar)
14. [Announcements](#14-announcements)
15. [Private messages](#15-private-messages)
16. [Notifications](#16-notifications)
17. [Audit log](#17-audit-log)
18. [Profile](#18-profile)
19. [Settings](#19-settings)
20. [Interface and usability](#20-interface-and-usability)
21. [Security features](#21-security-features)
22. [Shift management](#22-shift-management)
23. [Late minutes](#23-late-minutes)
24. [Overtime management](#24-overtime-management)
25. [Excel reports](#25-excel-reports)
26. [Sending notifications with expiry](#26-sending-notifications-with-expiry)
27. [AI-powered assistance](#27-ai-powered-assistance)
28. [Departments, designations and analytics](#28-departments-designations-and-analytics)
29. [Payroll variance review](#29-payroll-variance-review)
30. [Attendance correction requests](#30-attendance-correction-requests)
31. [Team calendar](#31-team-calendar)
32. [Analytics and reports](#32-analytics-and-reports)
33. [Employee onboarding](#33-employee-onboarding)
34. [Document expiry and reminders](#34-document-expiry-and-reminders)
35. [Notification preferences and audit improvements](#35-notification-preferences-and-audit-improvements)
36. [AI assistant: new topics and evidence](#36-ai-assistant-new-topics-and-evidence)

---

## 1. Roles and access

PayrollPro has two roles. Every account has exactly one.

| | **Administrator** | **Employee** |
| --- | --- | --- |
| How the account is created | `python manage.py createsuperuser`, or an existing staff/superuser account (it gets the admin role automatically on first login) | Public registration, Google sign-up, or added by an administrator |
| Portal | Admin portal (`admin-dashboard.html` and the admin pages) | Employee portal (`employee-dashboard.html` and the employee pages) |
| Can do | Manage employees, salaries, payroll, approvals, holidays, announcements, office location; read the audit log | Mark own attendance, request leave/WFH, upload documents, view own payslips |

**How access is enforced**

- Every admin API endpoint checks the role on the server. An employee calling an admin endpoint gets *"Access denied. Administrator access is required."* (HTTP 403).
- Employees can only ever read their own data (leave, WFH, documents, attendance, payslips). Requests for someone else's record return "not found".
- In the browser, opening a page for the other role sends you to your own dashboard. If the server no longer recognises your session, you are sent to the sign-in page with the message *"Your session has ended. Please sign in again."*

---

## 2. Sign-in and accounts

### 2.1 Sign in

**Page:** `index.html` · **API:** `POST /api/login/`

**How it works**
1. Choose **Employee** or **Administrator** with the switch at the top of the form. The button text changes to "Sign in as employee" / "Sign in as administrator".
2. Enter your **username or email** and password. The eye icon shows or hides the password.
3. Optionally tick **Remember me** (see 2.2).
4. On success you go straight to your dashboard.

**Rules**
- The login type must match the account's role. An employee choosing "Administrator" (or the reverse) gets *"Incorrect login type"*.
- Inactive employees cannot sign in (*"This employee account is inactive"*).
- A wrong username or password always shows the same message, *"Invalid username or password"*, so nobody can find out which usernames exist.
- If you are already signed in and open the sign-in page, you are taken straight to your dashboard.

### 2.2 Remember me

When ticked, the session lasts 7 days (configurable with `SESSION_COOKIE_AGE`). When not ticked, the session ends when the browser is closed. The same option applies to Google sign-in.

### 2.3 Self-registration

**Page:** `index.html` → "Create an account" (shown only when *Employee* is selected) · **API:** `POST /api/register/`

**How it works**
1. Enter a username, email, password and the password again.
2. The account is created as an **Employee** and you can sign in immediately.
3. You receive a *"Welcome to PayrollPro"* notification.
4. The account appears to administrators as a **pending account** (see [4.3 Onboarding](#43-onboarding-self-registered-accounts)). Until an admin completes the employment record, your dashboard shows a warning, and payroll, attendance and leave don't apply to you yet.

**Rules**
- Only employee accounts can be registered publicly. Administrator registration is refused.
- Username: up to 150 characters; letters, numbers and `@ . + - _` only; must be unique (case-insensitive).
- Email: must be valid and unique.
- Password must pass Django's strength checks: minimum length, not a common password, not entirely numeric, not too similar to the username or email.

### 2.4 Forgot password (OTP)

**Page:** `index.html` → "Forgot password?" · **API:** `POST /api/password/forgot/`, `/api/password/verify-otp/`, `/api/password/reset/`

**How it works (three steps)**
1. **Request a code.** Enter your username or email. A random 6-digit code is emailed to the account's address. (If email isn't configured, the code is printed in the Django server console, which is handy in development.) A *Resend code* link is available.
2. **Verify the code.** Enter the 6-digit code. If it is correct, the server issues a one-time reset token.
3. **Choose a new password.** Enter and confirm the new password. You can then sign in with it.

**Rules**
- The response is always *"If an active account matches, a verification code has been sent."*, so it never reveals whether an account exists.
- Codes expire after **10 minutes** and allow **5 attempts**. After that you must request a new code.
- Requesting a new code invalidates any earlier one.
- Codes are stored only as a hash, never in plain text.
- Code requests are rate-limited (see 2.6).
- The new password must pass the same strength checks as registration.
- Google-only accounts (which have no password) can use this flow to set one.

### 2.5 Change password

**Page:** `settings.html` · **API:** `POST /api/password/change/`

Enter your current password, a new password and the new password again. The current password must be correct and the new one must pass the strength checks. You stay signed in after the change.

### 2.6 Brute-force lockout

After **5 failed attempts** within the lockout window, the same route is locked for **15 minutes**, counted both per IP address and per username/email. This applies to:
- password sign-in (failed logins)
- password-reset code requests
- Google sign-in failures (per IP)

The user sees *"Too many failed attempts. Please wait a few minutes before trying again."* A successful sign-in clears the counter. Both limits can be changed with `LOGIN_MAX_FAILED_ATTEMPTS` and `LOGIN_LOCKOUT_SECONDS`.

### 2.7 Sessions and sign-out

- Sign-in creates a secure, HttpOnly session cookie; JavaScript cannot read it.
- **Sign out** is in the user menu (top right) and on the Settings page. It ends the server session and clears the browser's stored state.
- When a session expires, the next action sends you back to the sign-in page with an explanation.

### 2.8 Sign in with Google

**Pages:** `index.html` ("Continue with Google", "Sign up with Google"), `settings.html` (connect/disconnect), `google-callback.html` · **API:** `/api/auth/google/config/`, `start/`, `callback/`, `link/`

This feature is optional. Until Google credentials are added to `.env`, the buttons are shown disabled with the note *"Google sign-in has not been set up on this server yet."*

**How it works**
1. You click a Google button. The browser asks the server to start the flow, and the server returns Google's consent URL (with a one-time `state`, `nonce` and PKCE challenge stored in your session).
2. You choose your Google account on Google's page.
3. Google sends you back to the server's callback. The server checks the `state`, exchanges the code with Google directly (the client secret never reaches the browser), and verifies the ID token's signature, audience, issuer, expiry and nonce.
4. The server then does one of three things:
   - **Linked account found:** signs you in.
   - **New Google account with an unused email, Employee selected:** creates a new **Employee** account (username taken from the email, name from Google, no password) and signs you in.
   - **Link mode (from Settings):** connects the Google account to the user who is already signed in.
5. You land on your dashboard (or back on Settings for link mode).

**Connecting and disconnecting (Settings)**
- **Connect Google account** links your Google identity to your current account. After that, "Continue with Google" signs you in.
- **Disconnect** removes the link. It is only allowed if your account has a password, so you can't lock yourself out. Google-only accounts are told to set a password with "Forgot password" first.

**Account-safety rules**
- A Google account is identified by Google's permanent account ID, not by its email.
- It is **never** attached to an existing account just because the email matches. If the email is already registered, you get *"An account with this email already exists. Sign in with your password, then connect Google from Settings."*
- Google can **never create an administrator**. An admin must sign in with their password and connect Google from Settings first.
- Only Google accounts with a **verified email** are accepted.
- The same role and inactive-account checks as password sign-in apply.
- One Google account can be linked to only one user, and each user can link only one Google account.
- Every failure shows a clear, fixed message (cancelled, expired attempt, Google unreachable, email not verified, wrong login type, and so on).

---

## 3. Dashboards

### 3.1 Admin dashboard

**Page:** `admin-dashboard.html` · **API:** `GET /api/dashboard/admin/`

A time-of-day greeting ("Good morning, …") and a quick **Run payroll** button, then:

**Summary cards** (each card links to the related page)
| Card | Shows |
| --- | --- |
| Active employees | Number of active employees, and how many joined this month |
| Net payroll | Net pay for the latest payroll month, payslip count and drafts still open |
| Pending approvals | Total pending items, split into leave · WFH · documents |
| Checked in today | Employees checked in out of all active employees, plus how many are on leave or working remotely today |

**Needs attention** – warning banners appear only when relevant:
- Self-registered accounts waiting for an employee record → *Onboard*
- Active employees with no salary structure (they will be skipped in payroll) → *Set up salaries*
- Draft payslips for the latest month not yet finalised → *Review*

**Charts and lists**
- **Net payroll trend:** bar chart of net pay for the last six payroll months
- **Headcount by department:** horizontal bars for active employees
- **Pending leave requests:** the five most recent, with type, dates and number of days
- **Latest announcements:** the three newest

### 3.2 Employee dashboard

**Page:** `employee-dashboard.html` · **API:** `GET /api/dashboard/employee/`

If the employment record hasn't been created yet, a banner explains that an administrator must complete it before payroll, attendance and leave work.

**Summary cards**
| Card | Shows |
| --- | --- |
| Net pay | Net salary of the latest paid payslip and its month |
| Today | Not checked in / Checked in / Completed today, plus days present this month |
| Pending requests | Pending leave · WFH · documents |
| Employment | Designation, employee ID and department |

**Charts and lists**
- **Salary trend:** net pay for the last six paid payslips
- **Leave balance:** days remaining per leave type for the current year
- **Upcoming holidays:** the next three, with Fixed/Tentative badges
- **Latest announcements:** the three newest

---

## 4. Employee management

**Page:** `employee-management.html` (Admin) · **API:** `/api/employees/`, `/api/employees/meta/`, `/api/employees/<id>/`

### 4.1 Employee list

A table showing each employee's name and email, employee ID, department and designation, joining date, status (Active/Inactive) and salary status (*Configured* or *Not set*, which links to Salary structures).

- **Search** as you type, across employee ID, username, first/last name, email, department and designation
- **Filter** by status (Active/Inactive) and by department (the list is built from departments already in use)
- **Sort** by clicking column headers (employee ID, name, department, joining date, status); click again to reverse
- **Pagination:** 10 per page

### 4.2 Add employee

Click **Add employee** and fill in three sections:

| Section | Fields |
| --- | --- |
| Account | Username, email, temporary password (the employee can change it after signing in) |
| Personal | First name, last name, phone |
| Employment | Employee ID, joining date, department (with suggestions from existing departments), designation |

On save, a login account (role Employee) and the employee record are created together. The new employee gets a welcome notification and the action is written to the audit log.

**Validation**
- **Employee ID:** 2–20 characters, starting with a letter or number; letters, numbers, `-`, `_` and `/` only; stored in capitals; must be unique.
- **Phone:** 7–15 characters made of digits, spaces, `+`, `-`, `(` and `)`.
- **Department** and **designation** cannot be blank.
- **Username** and **email** must be unique; the temporary password must pass the strength checks.

### 4.3 Onboarding self-registered accounts

People who registered themselves (or signed up with Google) have a login but no employee record. The page shows a banner, *"N registered accounts waiting for an employee record"*, with a button for each person.

Clicking a person opens **Complete employee record**. Their existing login is reused (no new username or password), and you fill in the personal and employment details. After saving, they appear in the employee list and can be included in payroll.

### 4.4 Edit employee

**Edit** opens the same form with the current values. You can change the name, email, phone, employee ID, joining date, department, designation and status. Only fields that actually changed are recorded in the audit log, for example *"Updated EMP001: department, designation."*

### 4.5 Deactivate and reactivate

- **Deactivate** (after confirmation) marks the employee *Inactive* and disables their login. They can no longer sign in by any method and are skipped in payroll. **All their records are kept.**
- **Reactivate** sets them back to *Active* and re-enables sign-in.
- An administrator cannot deactivate their own account.
- Both actions are audited.

---

## 5. GPS attendance

Attendance is marked from the browser using the device's location. An employee can only check in or out when they are physically near the office.

### 5.1 Office location (Admin)

**Page:** `admin-attendance.html` → **Office location** · **API:** `GET/PUT /api/attendance/settings/`

| Setting | Description |
| --- | --- |
| Latitude / Longitude | The office position. **Use my current location** fills these from the admin's device. |
| Allowed radius (metres) | How close an employee must be (default 100 m) |
| Attendance enabled | Turns attendance on or off for everyone |

Attendance cannot be enabled until a valid latitude (−90 to 90) and longitude (−180 to 180) are saved.

### 5.2 Check in and check out (Employee)

**Page:** `employee-attendance.html` · **API:** `GET /api/attendance/status/`, `POST /api/attendance/check-in/`, `POST /api/attendance/check-out/`

**How it works**
1. The page shows today's date and status (*Not checked in*, *Checked in* or *Checked out*), today's times, and the allowed radius.
2. Click **Check in**. The browser asks permission to share your location (high-accuracy GPS) and sends the coordinates to the server.
3. The server calculates the distance from the office using the haversine (great-circle) formula.
   - **Within the radius:** the check-in time, coordinates and distance are saved.
   - **Outside the radius:** refused with the actual distance, e.g. *"You are 350 m from the office. You must be within 100 m to mark attendance."*
4. Later, click **Check out**, which goes through the same location check.
5. After checking out, the page shows *"You have completed attendance for today. Worked 8h 15m."*

**Rules**
- One attendance record per employee per day.
- You can't check in twice, check out twice, or check out before checking in.
- If attendance is disabled or the office location isn't set, employees see *"Attendance has not been set up yet."*
- If location permission is denied, the employee is told how to allow it.
- Administrators cannot mark attendance.
- Every check-in and check-out notifies administrators.

### 5.3 Attendance history (Employee)

The same page lists the employee's last 30 days with date, check-in, check-out, hours worked and status.

### 5.4 All attendance records (Admin)

**Page:** `admin-attendance.html` · **API:** `GET /api/attendance/`

A table showing each record's employee, date, check-in and check-out times, hours worked, distance from the office at check-in/check-out, and status.

- **Search** by name, username or employee ID
- **Filter** by a single date (with a clear button); the API also accepts a `from`/`to` date range
- **Pagination:** 15 per page

### 5.5 How attendance affects pay

A day with a check-in counts as a paid day. Time worked beyond the standard 8 hours on days with both a check-in and a check-out counts as overtime. See [10.4](#104-how-a-payslip-is-calculated).

---

## 6. Leave management

**Pages:** `employee-leave.html` (Employee), `admin-leave.html` and `admin-leave-policy.html` (Admin) · **API:** `/api/leaves/`, `/api/leaves/balance/`, `/api/leaves/<id>/status/`, `/api/leaves/<id>/` (cancel), `/api/leave-types/`, `/api/leave-policy/`

### 6.1 Leave policy (Admin – *People → Leave policy*)

Leave types and limits are **stored in the database and managed by administrators**; nothing about leave types or day counts is fixed in code. The first migration created the previous defaults (Casual 12, Sick 12, Earned 15 paid days per year; *Other* unpaid with no limit) so existing behaviour and history were kept.

- **Leave types:** create, edit, activate/deactivate (and delete while unused). Each type has a name, description, **days allowed per employee per leave year** (or *no annual limit*), **paid or unpaid** (unpaid days are loss of pay in payroll), **carry forward** on/off with a **maximum** number of days, and a display order. Changing the days updates every employee's balance immediately. A type with requests cannot be deleted (deactivate it instead); renaming it also relabels its requests.
- **Leave rules:** the month the **leave year** starts (January = calendar year, April = April–March …), **minimum notice** in days, **maximum days per request**, and whether leave may be applied for **past dates**.
- **Carry forward:** for a chosen leave year, records for every employee the unused days of the previous year (up to each type's maximum). Safe to run again.
- **Employee balances:** view any employee's balance by type and year and **adjust** it by ± days with a required reason.
- Every change is written to the audit log (module *Leave*).

### 6.2 Leave balance (Employee)

The Leave page and the dashboard show, for every active leave type (and any inactive type used this leave year): **Total allowed** (annual days + carried forward + adjustment), **Used** (approved days), **Pending** (shown separately, never counted as used) and **Available** (total − used). When requests are pending it also shows how many days **can still be requested** (available − pending), so several pending requests cannot exceed the allowance. Rejected and cancelled requests never count. The figures come straight from the policy, so an administrator's change is reflected immediately.

### 6.3 Apply for leave (Employee)

1. Click **Apply for leave**.
2. Choose the leave type (the list shows each type the administrator offers with the days you can still request), the start and end dates (both default to today), and a reason (up to 500 characters). The form shows whether the type is paid, your balance, the number of days requested and a warning if it is more than you can request.
3. Submit. The number of days is calculated automatically (end − start + 1, counting calendar days), and the request is created as **Pending**.
4. All administrators are notified.

**Rules**
- The end date can't be before the start date.
- A request can't overlap another pending or approved leave request of yours.
- For types with an annual limit, the days requested can't exceed what can still be requested in that leave year (pending requests are reserved). The error says how many days are left and suggests an unlimited unpaid type if one is offered.
- The administrator's rules for notice, maximum days per request and past dates are checked on the server.
- Inactive or unknown leave types are refused.
- A **pending** request can be cancelled by the employee from the Leave page; it then no longer affects the balance.

### 6.4 Review leave (Admin)

The admin table shows the employee (username and code), leave type, dates, number of days, reason, status and actions.

- **Approve:** after confirming, the request becomes *Approved* and the employee is notified.
- **Reject:** opens a box for an optional reason (shown to the employee). The request becomes *Rejected* and the employee is notified with the reason.
- **Filter** by status, **search** by username, name or employee ID, **paginate** (10 per page). The API also filters by leave type.
- A request can only be processed once. Trying again gives *"This leave request has already been processed."* (This is safe even when two admins click at the same moment.)

### 6.5 Employee view

The employee's table shows their own requests with type, dates, days, reason, status and the admin's response (rejection reason), filterable by status.

### 6.6 How leave affects pay

Approved **paid** leave days count as paid days. Approved **Other** leave days are always loss of pay, even if the employee also checked in on those days.

---

## 7. Work from home

**Pages:** `employee-wfh.html` (Employee), `admin-wfh.html` (Admin) · **API:** `/api/wfh/`, `/api/wfh/<id>/`

### 7.1 Request WFH (Employee)

1. Click **Request WFH**, choose the from/to dates and enter a reason.
2. The request is created as **Pending**, the number of days is shown, and all administrators are notified.

**Rules**
- The end date can't be before the start date.
- A request can't overlap another pending or approved WFH request of yours.
- Administrators can't create WFH requests.

### 7.2 Cancel (Employee)

A pending request has a **Cancel** button. After confirmation it becomes *Cancelled*, and administrators are notified. Approved or rejected requests can't be cancelled.

### 7.3 Review (Admin)

- **Approve** after confirmation; the employee is notified.
- **Reject** requires a **note**, which is shown to the employee and included in the notification.
- **Filter** by status (Pending, Approved, Rejected, Cancelled) and paginate.
- A request can only be processed once.

### 7.4 How WFH affects pay

Approved WFH days count as paid days, just like a day with a check-in.

---

## 8. Documents

**Pages:** `employee-documents.html` (Employee), `admin-documents.html` (Admin) · **API:** `/api/documents/`, `/api/documents/<id>/`, `/api/documents/<id>/file/`, `/api/documents/<id>/review/`

### 8.1 Upload (Employee)

1. Click **Upload document**.
2. Enter a title (e.g. "Passport") and choose a type: *Identity proof, Address proof, Education certificate, Resume* or *Other*. For *Other*, type in what the document is.
3. Choose the file and upload. It is saved as **Pending review**, and administrators are notified.

**File rules**
- Only **PDF, JPG or PNG**, up to **5 MB** (checked in the browser and again on the server).
- The server reads the file's first bytes to confirm it really is a PDF/JPG/PNG. A renamed file of another type is rejected.
- Files are stored in folders by year and month.
- Administrators can't upload documents (they only review them).

### 8.2 View

**View** opens the file in a new tab. Files are **private**: they are never served from a public URL. They are streamed through an authenticated endpoint that only the owner and administrators can use, with headers that stop the browser caching them.

### 8.3 Delete (Employee)

An employee can delete their own document **only while it is pending review**. After confirmation the record and the file are both permanently removed. Verified or rejected documents can't be deleted.

### 8.4 Review (Admin)

The admin table lists every employee's documents with employee, title, type, upload date and status, filterable by status.
- **Verify** after confirmation → *Verified*; the employee is notified.
- **Reject** requires a reason → *Rejected*; the reason appears under the document title and in the employee's notification.

---

## 9. Salary structures

**Page:** `admin-salary.html` (Admin) · **API:** `/api/payroll/salary-structures/`, `/api/payroll/salary-structures/<employee id>/`, `/api/payroll/my-salary-structure/`

A salary structure holds an employee's fixed monthly pay. Payroll uses it every month, and an employee without one is skipped.

### 9.1 List

A table of active employees showing basic pay, monthly gross (or *Not set*), effective date and an **Edit** / **Set up** button. You can search by ID, name or department and filter by *configured / not configured*. 10 per page.

### 9.2 Set up or edit

The form has three sections.

**Earnings (per month)**
| Field | Notes |
| --- | --- |
| Basic pay | Required, must be greater than 0 |
| House rent allowance (HRA) | Optional, default 0 |
| Conveyance allowance | Optional |
| Medical allowance | Optional |
| Special allowance | Optional |
| Other allowance | Optional |

**Deductions**
| Field | Notes |
| --- | --- |
| Provident fund (% of basic) | 0–100, default 12 |
| Professional tax / month | Fixed amount |
| Income tax (TDS) / month | Fixed amount (the system doesn't calculate tax slabs) |
| Other fixed deduction / month | For example a loan instalment |
| Overtime pay per hour | Used for overtime earnings |

**Effective**
- Effective from (date)

While you type, the form shows a live **Monthly gross** preview.

**Rules**
- No amount can be negative.
- PF + professional tax + TDS + other deduction can't exceed the monthly gross.
- Saving notifies the employee (*"Salary structure updated"*) and writes an audit entry including the new gross.
- A changed structure doesn't alter payslips that already exist. Use **Recalculate** on a draft to apply it.

---

## 10. Payroll runs

**Page:** `admin-payroll.html` (Admin) · **API:** `/api/payroll/run/`, `/api/payroll/payslips/`, `/api/payroll/payslips/<id>/`, `/api/payroll/payslips/<id>/recalculate/`, `/api/payroll/finalize/`

### 10.1 The payroll page

- **Month and year pickers** default to the last completed month (years go back six years).
- **Summary cards:** number of payslips (draft/paid), gross earnings, deductions and net payable.
- **Payslip table:** employee and code, department, paid days / working days, gross, deductions, net, status, and actions (View, Adjust for drafts, PDF).
- **Search** by code, name or department, **filter** by Draft/Paid, 10 per page.
- Buttons: **Run payroll**, **Finalise N drafts** (shown only when drafts exist) and **Export CSV**.

### 10.2 Payroll lifecycle

```
Run payroll  →  DRAFT payslips  →  (adjust / recalculate / delete)  →  Finalise  →  PAID (visible to employees, locked)
```

### 10.3 Run payroll

1. Pick the month and click **Run payroll**.
2. Choose the **loss of pay** mode:
   - **Calculate from attendance, leave and work-from-home records** (default)
   - **Do not deduct for absence (full month)**, for organisations that don't use attendance. Unpaid leave and joining date still apply.
3. Click **Generate drafts**. A result window shows how many drafts were created and lists each **skipped** employee with the reason.

**Who is included:** every *active* employee with an enabled login (the API can also limit the run to selected employees).

**Who is skipped, and why**
| Reason shown | Meaning |
| --- | --- |
| A payslip already exists for this month | Existing payslips are never overwritten |
| No salary structure has been set | Set one up, then run again |
| Joined after this month | Joining date is after the month ended |
| Deductions exceed earnings | Net would be negative |

**Rules**
- Payroll can only be run **after the month has ended**.
- Drafts are invisible to employees.
- Running again for the same month only adds payslips for employees who don't have one yet, so it is safe to repeat.
- Each run is audited, including the attendance mode used.

### 10.4 How a payslip is calculated

All amounts use exact decimal maths, rounded to 2 decimal places (₹).

1. **Working days** = the month's working weekdays (Mon–Fri by default) minus holidays on the calendar.
2. **Payable days** = working days on or after the joining date.
3. **Covered days** (attendance mode) = payable days on which the employee checked in, was on approved paid leave, or had approved WFH. In no-attendance mode, all payable days are covered.
4. Approved **unpaid ("Other") leave** days are removed from covered days.
5. **LOP days** = working days − covered days.
6. **Overtime** = the employee's **approved** overtime records dated in the month (hours and hours × rate). See [24](#24-overtime-management).
7. **Earnings:** the seven salary components (basic, HRA, DA, conveyance, medical, special, other) + overtime pay + bonus = **gross earnings**. The bonus defaults to the salary structure's monthly bonus and is not reduced for loss of pay.
8. **Deductions:**
   - **LOP deduction** = fixed monthly gross × LOP days ÷ working days
   - **PF** = PF % × earned PF wage ((basic + DA) × paid share of the month)
   - **Professional tax** and **TDS** = monthly amounts × paid share of the month (so a month with no paid days isn't taxed)
   - **Other deductions** in full
9. **Net salary** = gross earnings − total deductions.

**Worked example.** Basic ₹30,000, HRA ₹12,000, other allowances ₹8,000 (gross ₹50,000), PF 12%, professional tax ₹200, TDS ₹1,000. The month has 22 working days and the employee has 2 LOP days.

| Item | Calculation | Amount |
| --- | --- | --- |
| LOP deduction | 50,000 × 2 ÷ 22 | ₹4,545.45 |
| PF | 12% × 30,000 × 20/22 | ₹3,272.73 |
| Professional tax | 200 × 20/22 | ₹181.82 |
| TDS | 1,000 × 20/22 | ₹909.09 |
| Total deductions | | ₹8,909.09 |
| **Net salary** | 50,000 − 8,909.09 | **₹41,090.91** |

Each payslip also keeps a **snapshot** of the employee's code, name, department and designation, so later changes to the employee don't alter old payslips.

### 10.5 View a payslip

**View** opens the full breakdown on screen: attendance summary (working, LOP, paid days, overtime hours), every earning and deduction, and the net salary.

### 10.6 Adjust a draft

**Adjust** (drafts only) lets you change:

| Field | Rule |
| --- | --- |
| Loss of pay days | Whole or half days (e.g. 1 or 1.5), between 0 and the month's working days |
| Bonus (₹) | 0 or more; added to gross |
| Other deductions (₹) | 0 or more |
| Note | Up to 300 characters |

All totals are recalculated immediately. A change that would make the net salary negative is refused. Each adjustment is audited, listing which fields changed.

### 10.7 Recalculate a draft

Inside the Adjust window, **Recalculate from attendance** rebuilds the draft from the **current** salary structure and attendance/leave/WFH records, **discarding manual adjustments**. Use it after changing a salary structure or approving late leave. It asks for confirmation and is audited.

### 10.8 Delete a draft

**Delete draft** (inside the Adjust window) removes the draft after confirmation. Running payroll again for that month recreates it. Paid payslips can't be deleted. Audited.

### 10.9 Finalise

**Finalise N drafts** asks for confirmation, then for the selected month:
- marks every draft as **Paid** and records the payment time
- makes the payslips **visible to employees** and **locks them** (no adjust, recalculate or delete)
- sends each employee a *"Payslip available"* notification
- writes an audit entry

The API can also finalise only selected payslips.

---

## 11. Payslips and PDF

### 11.1 My payslips (Employee)

**Page:** `employee-payslips.html` · **API:** `GET /api/payroll/payslips/`

- **Year picker** (current year and five previous years)
- **Summary cards:** net received in the year (with payslip count), gross earnings and deductions
- **Table:** month, gross, deductions, net, payment date, and **View** / **PDF** buttons
- Only **paid** payslips are shown. Drafts and other people's payslips are never visible.

### 11.2 PDF payslip

**API:** `GET /api/payroll/payslips/<id>/pdf/` (add `?inline=1` to open in the browser instead of downloading)

An A4 PDF generated on the server with ReportLab, containing:
- Company name (from `COMPANY_NAME`) and the pay period
- Employee name, employee ID, department, designation
- Working days, paid days, loss-of-pay days and status
- A two-column **Earnings / Deductions** table in Indian rupee format (earning lines that are zero are hidden, except basic pay)
- Gross earnings and total deductions
- A highlighted **Net salary** bar
- Footer: *"This is a computer-generated payslip and does not require a signature."*

The file is named `payslip_<code>_<year>-<month>.pdf`. Admins can open any payslip's PDF; employees only their own paid ones.

---

## 12. Reports and CSV export

### 12.1 Reports (Admin)

**Page:** `admin-reports.html` · **API:** `GET /api/payroll/reports/`

For the selected year:
- **Summary cards:** total net paid/payable, gross earnings, deductions (PF, tax, LOP) and the number of payroll months and payslips
- **Net payroll by month:** bar chart for January to December
- **Cost by department:** horizontal bars of net pay per department, with headcount, for the latest payroll month of that year (the API also accepts a specific `month`)
- **Monthly table:** month, payslip count, gross, deductions, net, status (*N draft* or *All paid*) and a **CSV** button for that month

### 12.2 CSV payroll register

**Buttons:** *Export CSV* (Payroll page) and *CSV* (each Reports row) · **API:** `GET /api/payroll/export/?year=&month=`

Downloads `payroll_<year>-<month>.csv` with one row per payslip and these columns:

> Employee ID, Name, Department, Designation, Working days, LOP days, Basic, HRA, Conveyance, Medical, Special, Other allowance, Overtime, Bonus, Gross, PF, Professional tax, TDS, Other deductions, LOP deduction, Total deductions, Net salary, Status

- Saved as UTF-8 with a byte-order mark, so Excel shows ₹ and names correctly.
- Text values that start with `=`, `+`, `-` or `@` are escaped, so a malicious name can't run a spreadsheet formula.
- Each export is recorded in the audit log.

---

## 13. Holiday calendar

**Pages:** `admin-holidays.html` (Admin), `employee-holidays.html` (Employee) · **API:** `/api/holidays/`, `/api/holidays/<id>/`

### 13.1 Calendar view (everyone)

- A month grid with **previous / next / today** navigation. Today is highlighted.
- Holidays appear inside their day cell. Tentative holidays are styled differently.
- Beside the calendar, **Holidays in <month>** lists each holiday with its full date, description and a Fixed/Tentative badge.

### 13.2 Manage holidays (Admin)

- **Add:** click an empty day (the date is pre-filled) or use **Add holiday**. Enter a name, date, type (*Fixed* or *Tentative*) and an optional description.
- **Edit:** click a day that has a holiday, or **Edit** in the list.
- **Delete:** inside the edit window, after confirmation.
- Only one holiday is allowed per date.
- Every add, change and delete notifies all employees.

### 13.3 Effect on payroll

Holidays are not working days, so they never count as loss of pay and they reduce the working-day count used in the LOP calculation.

---

## 14. Announcements

**Page:** `announcements.html` (everyone) · **API:** `/api/announcements/`, `/api/announcements/<id>/`

- Everyone sees a feed of announcements, newest first, each with its title, author, date/time and full message (line breaks are kept).
- **Admins** click **New announcement**, enter a title and message, and **Publish**. Every employee is notified, and the notification includes the start of the message.
- **Admins** can **Delete** an announcement after confirmation; it disappears for everyone.
- The three latest announcements also appear on both dashboards.

---

## 15. Private messages

**Page:** `chat.html` (everyone) · **API:** `/api/chat/employees/`, `/api/chat/conversations/`, `/api/chat/conversations/<id>/messages/`

One-to-one conversations between an administrator and an employee.

**How it works**
1. **Admins** choose an active employee from **Start a conversation…** (shown with their department). If a conversation with that person already exists, it is reopened instead of duplicated. The employee is notified.
2. **Employees** see conversations that administrators have started with them. They can reply but can't start new conversations.
3. The left column lists conversations with the other person's name, a preview of the last message and an **unread count** badge.
4. Opening a conversation shows the message history in chat bubbles (your own messages on the right), each with a timestamp, and marks the other person's messages as read.
5. Type a message (up to 4000 characters) and send. The other person gets a notification that opens this conversation directly.
6. While the conversation is open and the tab is visible, new messages are fetched automatically every 8 seconds.

**Rules**
- Only the two participants can read or write in a conversation. Anyone else gets "not found".
- Empty messages are refused.
- On phones, the conversation list and the open conversation take turns on screen, with a back button.

---

## 16. Notifications

**Bell icon** in the top bar on every page · **Page:** `notifications.html` · **API:** `/api/notifications/`, `/api/notifications/<id>/read/`, `/api/notifications/read-all/`

### 16.1 How it works

- The bell shows a dot when you have unread notifications. It refreshes every minute while the tab is visible.
- The Notifications page lists your latest 100 notifications with an icon for the type, title, message and relative time ("5 minutes ago"). Unread ones are highlighted.
- Clicking a notification marks it as read and opens the related page.
- **Mark all as read** clears every unread notification at once.
- You are never notified about your own actions.

### 16.2 What creates a notification

| Event | Who is notified | Opens |
| --- | --- | --- |
| Account registered (form or Google) | The new user | Employee dashboard |
| Employee record created by admin | The employee | Employee dashboard |
| Leave request submitted | All admins | Admin leave page |
| Leave approved / rejected (with reason) | The employee | Employee leave page |
| WFH requested / cancelled | All admins | Admin WFH page |
| WFH approved / rejected (with note) | The employee | Employee WFH page |
| Document uploaded | All admins | Admin documents page |
| Document verified / rejected (with note) | The employee | Employee documents page |
| Employee checked in / out | All admins | Admin attendance page |
| Holiday added / updated / removed | All employees | Employee holidays page |
| Announcement published | All employees | Announcements |
| Conversation started / new message | The other participant | That conversation |
| Salary structure set or changed | The employee | Payslips page |
| Payslip finalised | The employee | Payslips page |

---

## 17. Audit log

**Page:** `admin-audit.html` (Admin) · **API:** `GET /api/audit-logs/`

A permanent record of sensitive administrative actions. Entries are created automatically and can't be edited or deleted from the app.

**Each entry records:** date and time, who did it (username kept even if the user is later removed), the action, the record type and ID, a readable summary, and the IP address.

**Actions recorded**
| Record type | Actions |
| --- | --- |
| Employee | CREATE, UPDATE (lists changed fields), DEACTIVATE |
| SalaryStructure | CREATE, UPDATE (includes the new monthly gross) |
| Payroll | RUN (count and attendance mode), FINALIZE (count), EXPORT |
| Payslip | ADJUST (fields changed), RECALCULATE, DELETE |

**On the page:** search by summary text or username, filter by record type (Employee, Salary structure, Payslip, Payroll), 20 per page. The API also filters by action.

---

## 18. Profile

**Pages:** `admin-profile.html`, `employee-profile.html` · **API:** `GET/PUT /api/profile/`

- **Header:** profile photo (or your initials), full name, role and username.
- **Editable details:** first name, last name, email, phone and address. Saving updates the name shown in the top bar straight away.
- **Change photo:** pick a JPG or PNG up to **2 MB**. It is uploaded immediately and shown in the profile and the top bar. The server checks the size, type and real image content.
- **Employment card (employees only):** employee ID, department, designation, joining date and status, read-only. These are managed by administrators.
- The email must not be used by another account. The username and role can't be changed here.

---

## 19. Settings

**Page:** `settings.html` (everyone)

- **Signed in as:** your username and a **Sign out** button
- **Change password:** see [2.5](#25-change-password)
- **Google account:** connect or disconnect, with the connected Google email shown; see [2.8](#28-sign-in-with-google)

---

## 20. Interface and usability

- **Light and dark themes:** a sun/moon toggle in the top bar and on the sign-in page. The choice is remembered in the browser and applied before the page draws, so there is no flash of the wrong theme. First-time visitors get light mode.
- **Responsive layout:** the sidebar collapses into a menu button on phones and tablets; tables and forms adapt to small screens.
- **Grouped navigation:**
  - Admin: *Overview* (Dashboard) · *People* (Employees, Attendance, Leave requests, Work from home, Documents) · *Payroll* (Payroll runs, Salary structures, Reports) · *Company* (Holiday calendar, Announcements, Messages, Audit log)
  - Employee: *Overview* (Dashboard) · *My work* (Attendance, Leave, Work from home, Documents) · *My pay* (Payslips) · *Company* (Holiday calendar, Announcements, Messages)
- **User menu:** avatar and name in the top bar, with links to Profile, Settings and Sign out.
- **Feedback:** loading skeletons while data loads, clear empty states with next steps, error states with a **Try again** button, toast messages after each action, and confirmation dialogs before anything destructive.
- **Forms:** validation messages from the server are shown next to the form; buttons show a spinner while working, to prevent double submits.
- **Search boxes** wait briefly after you stop typing before searching, to avoid needless requests.
- **Indian formats:** amounts in ₹ with Indian digit grouping (and compact forms like ₹4.2L on cards); dates like "19 Oct 2026". The server time zone is Asia/Kolkata.
- **Accessibility:** keyboard-friendly dialogs (Escape closes menus and dialogs), labelled icon buttons, `aria` states on toggles, sort buttons and the current page, and live regions for chat and previews.

---

## 21. Security features

| Area | Protection |
| --- | --- |
| Sessions | HttpOnly, SameSite=Lax cookies; Secure cookies, HTTPS redirect and HSTS when `DJANGO_DEBUG=False` |
| CSRF | Every POST/PUT/PATCH/DELETE needs the CSRF token; an expired token shows a friendly "refresh and try again" message |
| Secrets | Stored in `backend/.env` (git-ignored); the server refuses to start in production without a secret key |
| Access control | Role checks on the server for every admin action; employees see only their own data |
| Passwords | Django's strength validators and hashing; generic error messages that don't reveal which accounts exist |
| Brute force | Lockout after repeated failed logins, reset-code requests and Google failures |
| Reset codes | Random 6 digits, stored hashed, 10-minute expiry, 5 attempts, single use |
| Uploads | Size limits plus real file-signature checks; employee documents never publicly served |
| Payroll integrity | Paid payslips are locked; employee details are snapshotted; database locks prevent double processing |
| Exports | Spreadsheet formula injection neutralised |
| Google sign-in | PKCE, state and nonce; server-side token exchange; full ID-token verification; never links by email; never creates admins |
| Accountability | Audit log with user and IP address for every sensitive admin action |
| Output | All text shown in the browser is HTML-escaped to prevent script injection |

---

## 22. Shift management

**Page:** `admin-shifts.html` (Admin), *Attendance & shift* (Employee) · **API:** `/api/shifts/`, `/api/shifts/<id>/`, `/api/shifts/assignments/`, `/api/shifts/assignments/<id>/`, `/api/shifts/my/`

**Shift definitions.** Each shift has a unique name, start and end time (an end before the start is an overnight shift), a grace period (0–240 min), an unpaid break, an optional description, an *active* flag and a *default* flag. The **standard day** is the shift length minus the break (for example 09:30–18:30 with a 60-minute break = 8 h). Only one shift can be the default; it applies to employees who have no assignment on a given day. A shift that has assignments cannot be deleted (it is kept for the employees' records); deactivate it instead.

**Assigning shifts.** *Assign shift* takes a shift, one or more employees (searchable checklist with *Select shown*), a start date, an optional end date and notes. Assignments for the same employee may not overlap. Ticking *Replace current shift* ends the employee's earlier assignment the day before the new one starts. Each assigned employee is notified.

**Employee shift records.** The *Employee shift records* table lists every assignment, current and past, with search, a shift filter and an *Active today* filter; assignments can be edited or removed. Employees see their current shift (and whether it is assigned or the company default), grace period, break, standard day and their full assignment history on *Attendance & shift*.

All shift changes are written to the audit log (module *Shifts*).

## 23. Late minutes

When an employee checks in, PayrollPro stores the shift in force that day, its scheduled start time and the **late minutes**:

- Arriving at or before the start, or within the grace period → **0** (on time).
- Arriving after the grace period → the full minutes since the scheduled start (09:52 against a 09:30 start with 10 minutes' grace = **22** minutes late).
- No shift and no default shift → not applicable (shown as "—").

Where it is reported: the employee's *Today* card and history; the admin attendance table (with a *Late only / On time only* filter, department filter and date range); the **Late & hours summary** tab (days present, late days, late minutes, average lateness, hours worked per employee); the admin dashboard (late today, late this month, average lateness); the employee dashboard; the attendance Excel report; and the AI Attendance Insight Generator. Admin notifications for a late check-in say how late it was.

## 24. Overtime management

**Page:** `overtime.html` (both roles) · **API:** `/api/overtime/`, `/api/overtime/<id>/`, `/api/overtime/<id>/review/`, `/api/overtime/generate/`

| Field | Meaning |
| --- | --- |
| Date, hours | A day that has already started; 0.25–16 hours in quarter-hour steps |
| Rate, amount | Pay per hour (defaults to the salary structure's overtime rate; only admins can change it); amount = hours × rate |
| Source | *Employee claim*, *Admin entry* or *From attendance* |
| Status | Pending → Approved / Rejected (reason required), or Cancelled |

- **Employees** claim overtime with a reason, edit or cancel it while it is pending, and see approved hours and amount for the month.
- **Admins** record overtime for any employee (optionally approving it immediately), approve or reject claims, edit pending records, and use **From attendance**, which creates pending records for each check-in/check-out longer than the employee's standard day, rounded down to a quarter hour. Days that already have overtime are skipped, so it can be run again safely.
- Only one pending/approved record per employee per day.
- **Payroll integration:** payroll pays the sum of **approved** records in the month. The payroll-run result shows how many records for that month are still pending; after approving more, *Recalculate* the draft. Once a month's payslip is finalised, overtime for that month is locked.
- Monthly totals, Excel export, notifications to employees/admins and audit entries (module *Overtime*).

## 25. Excel reports

**Pages:** *Reports → Excel reports*, plus Excel buttons on Attendance, Employees and Overtime · **API:** `GET /api/reports/excel/<kind>/`

| Report | Sheets | Filters |
| --- | --- | --- |
| Employees | Employees (ID, name, contact, department, designation, joining date, status, shift today, monthly gross, bonus); By department | status, department, search, joining date range |
| Attendance | Attendance (date, shift, scheduled start, check-in/out, hours, late minutes, distances); Summary per employee | date range (default this month), department, employee, late only |
| Leave | Leave requests (type, dates, days, status, paid/unpaid, reason, response); Summary of approved/pending/rejected days per employee and type | date range, status, leave type, department, employee |
| Overtime | Overtime (date, hours, rate, amount, status, source, reason, reviewer) | date range, status, department, employee |
| Payroll | Payroll register (every earning and deduction incl. DA, overtime hours, bonus; net, status, paid date); By department | year, month (or whole year), status, department, employee |

Each sheet has the company name, the filters used and the generation time, a green header row, frozen headers, auto-filter, alternating row shading, ₹ number formats and a totals row using live `SUM` formulas. Text from the database is always written as text so it can never run as a formula. Reports are admin-only and every export is audited.

## 26. Sending notifications with expiry

**Page:** `notifications.html` (Admin: *Send notification*) · **API:** `/api/notifications/broadcasts/`

Admins send a notification with a title, message, target (**all active employees**, **one department** or **selected employees**) and an optional **expiry date and time** (must be in the future). Recipients get it in their inbox (with "Expires …" shown) and the bell count; after the expiry it disappears from the inbox and unread count. The *Sent notifications* table shows the target, delivered and read counts, expiry status, and a **Withdraw** action that removes it from every inbox. Sending and withdrawing are audited.

## 27. AI-powered assistance

**Page:** `ai-assistant.html` (both roles) · **API:** `/api/ai/…` · **Service:** Google Gemini `generateContent` (model set by `GEMINI_MODEL`, default `gemini-flash-latest`)

| Assistant | What it uses | Example questions |
| --- | --- | --- |
| **AI Chatbot** | How PayrollPro works, the knowledge base, the user's employee details and pending items, upcoming holidays, latest announcements | "How do I apply for WFH?", "When is the next holiday?" |
| **AI Leave Policy Assistant** | System leave rules and entitlements, the organisation's leave policy text, the user's live balance and this year's requests, holidays | "How many casual days do I have left?", "What if I exceed my balance?" |
| **AI Salary Breakdown Assistant** | Payroll calculation rules, the user's salary structure (incl. DA, bonus, PF %, taxes), recent paid payslips or one chosen payslip, this month's overtime | "Explain my latest payslip", "Why was loss of pay deducted?" |
| **AI Attendance Insight Generator** | Statistics computed from attendance, leave, WFH and shifts for a chosen period (max 6 months): attendance rate, absent days and dates, late days/minutes and by weekday, typical check-in, hours worked, missing check-outs, unapproved overtime | *Generate AI insights* → Summary, Patterns, Punctuality, Working hours, Suggestions; then follow-up questions |

- **Conversation history** is saved in PostgreSQL per user and feature, in two sections: **Pinned** (most recently pinned first) and **Recent chats** (most recent activity first). Each conversation has a **three-dot menu** (closes on outside click, Escape or choosing an option; arrow keys move between options) with:
  - **Rename** – edits the title inline; **Enter** or the tick saves, **Escape** or the cross cancels. Spaces are trimmed, empty names are refused, 120 characters maximum. Messages are untouched and the new name is kept as you keep chatting.
  - **Pin / Unpin** – pinning a chat that is already pinned (or unpinning one that is not) is refused with a clear message, for example after a change in another browser tab.
  - **Delete** – after confirmation.
  Renaming and pinning do not change the "recent activity" order, and the open conversation stays selected.
- **Search** (top of the history sidebar, also on *Previous insights*): finds your conversations by title, your questions or the assistant's answers, across all assistant tabs, as you type (from 2 characters). Results show the title, which tab it belongs to, how many messages match and a snippet with the matching words highlighted. Clicking a result opens that conversation (switching tab if needed). *No conversations found* is shown when nothing matches; the ✕ button or Escape clears the search.
- Only the owner can list, search, open, rename, pin or delete a conversation; anyone else gets *not found*.
- **Admins** can point the salary assistant at an employee (and payslip) and generate attendance insights for one employee or the whole company (department lateness, most-late employees). Admin insights about others are audited.
- **Knowledge base (admin tab):** company overview, leave policy and FAQ, up to 8,000 characters each.
- **Grounding and safety:** the system instruction tells the model to answer only from the supplied context, never invent figures, refuse other people's data and treat record text as data, not instructions. Only the asking user's own records (or the admin's chosen subject) are sent.
- **Without a key** the page shows *AI not configured*; attendance figures still work. Errors (invalid key, unknown model, quota, timeouts, blocked answers) show a clear message and nothing half-finished is saved. Each user is limited to `AI_MAX_REQUESTS_PER_HOUR` AI calls per hour.
- Answers are rendered with safe, minimal formatting (headings, bold, lists) after HTML-escaping.

### 27.1 How answers are grounded (database-connected assistant)

Every question goes through PayrollPro's backend before Gemini sees it (`backend/assistant/retrieval.py`):

1. **Who is asking** comes only from the signed-in session (the conversation owner). Names, user IDs or employee codes typed in a question are never used to look up records.
2. **Privacy guard:** questions about another person ("Show Ravi's payslip", "payslip of EMP002", "what does my colleague earn?") are refused by PayrollPro itself; Gemini is not called and no records are read.
3. **Topic detection** decides which records are relevant: payslip, comparison with the previous payslip, salary structure, leave balance/requests, WFH requests, overtime, attendance this month, shift, documents, holidays. A how-to question ("How do I apply for work from home?") retrieves **no personal records**.
4. **Trusted retrieval and arithmetic:** only the user's **finalised (paid)** payslips are used (drafts are never shown to employees). PayrollPro lists every non-zero component with its stored amount, names the components that are zero, and writes out the calculation (fixed gross, gross, LOP deduction, PF, pro-rated tax, total deductions, net) from the stored values using the payroll rules. It compares the latest payslip with the previous one and lists the reasons it can see in the records (LOP days, working days, overtime, bonus, structure changes). If the stored totals do not add up, it says so instead of hiding it.
5. **Verified knowledge:** the best-matching topics from `backend/assistant/knowledge/guide.md` (written from the implemented pages and rules) plus the administrator's knowledge base are included for how-to questions.
6. **Gemini explains, it does not decide:** the instruction tells the model to classify the question (general, personal, or not available), quote amounts exactly and never invent records or say it lacks access when records were supplied.
7. **When Gemini is unavailable** (no key, network error, quota, hourly limit), personal questions are still answered **directly from the records** (marked "Shown directly from PayrollPro"), and how-to questions show the matching guide section. Questions with nothing reliable to show return a clear error.

Each answer shows **"Based on: …"** with the records used (for example *Payslip September 2026 (paid)*). Try: *Breakdown my payslip*, *Explain my net salary*, *Why was I paid less this month?*, *Show my latest payslip*, *What is my WFH request status?*, *How many leave days do I have left?*

## 28. Departments, designations and analytics

- **Departments (Employees page):** lists every department with headcount, active count and its designations; rename (or merge) a department or designation across all employee records in one step (audited).
- **Admin dashboard analytics:** active employees, latest payroll, pending approvals (leave, WFH, documents, overtime), today's check-ins with late count, a 14-day attendance chart, lateness this month, leave statistics for the year (pending/approved/rejected counts and approved days by type), payroll trend and headcount by department.
- **Employee dashboard:** today's shift and lateness, late days this month and pending overtime alongside pay, leave and holidays.
- **Search and filters** now also cover documents (employee, ID, title, type) and work-from-home requests (employee), in addition to employees, attendance, leave, overtime, payroll, shift records and the audit log (module, date range, IP).
## 29. Payroll variance review

**Who:** administrators. **Where:** *Payroll runs → Review & finalise* (`admin-payroll-review.html`), API `GET payroll/variance/`, `POST payroll/variance/review/`.

**Purpose:** catch mistakes before payslips are published, without changing any salary automatically.

1. Run payroll as before; drafts are created with the existing calculation.
2. Open the review. Every employee paid in this month or the previous one is listed with the previous net, this month's net and the change. *Flagged only* shows rows that need attention.
3. **Details** shows each component side by side (basic, HRA, DA, allowances, overtime, bonus, gross, PF, professional tax, TDS, other deductions, loss of pay, total deductions, net; plus working days, LOP days and overtime hours) with the amount and % change, and the reasons.
4. Click **Mark as reviewed**. If anything is flagged, tick *I have checked the flagged employees* or write a note.
5. **Finalise** is enabled only while the review is current. Adjusting, recalculating, deleting or generating a draft afterwards makes the review out of date; review again. `payroll/finalize/` returns 409 `review_required` otherwise.

| Flag | Severity | Rule |
| --- | --- | --- |
| Net change | check / high | Net salary changed by ≥ 10% / ≥ 20% (`PAYROLL_VARIANCE_THRESHOLD_PERCENT`) |
| Net zero | high | Net salary is zero |
| Missing | high | Paid last month, still active, no payslip this month (with the reason, e.g. no salary structure) |
| LOP high | check / high | Loss-of-pay days rose by 2 or more / at least half the working days |
| Overtime high | check | Overtime pay above 25% of the fixed monthly gross |
| Stale | check | The draft no longer matches current records (e.g. an approved correction or overtime); recalculate |
| Manual | info | The draft was adjusted by hand (who and when) |
| Structure | info | Fixed components, PF %, professional tax or TDS changed |
| New / Left | info | No payslip last month (new joiner) / employee deactivated (so totals still reconcile) |

**Reasons** come from stored data: salary-structure changes with who updated it and when, loss-of-pay days split into unpaid leave, working days without a check-in/approved leave/WFH (with dates) and days before joining, approved overtime records, whether a bonus came from the structure or was set on the payslip, holidays that changed working days, role changes and payslip notes. Reviews and finalisation are recorded in the audit log (module *Payroll*).

## 30. Attendance correction requests

**Who:** employees request; administrators decide. **Where:** *Attendance & shift → Request correction* (employee), *People → Attendance corrections* (`admin-corrections.html`). API `attendance/corrections/`, `…/<id>/review/`, `…/<id>/cancel/`.

**Employee steps:** click *Request correction* (or *Correct* on a day in *Recent attendance*), choose the date and type, enter the correct time(s) and a reason, and send. The *Correction requests* table shows recorded → requested times, the status and the administrator's response; *Cancel* is available while pending.

| Type | Needs |
| --- | --- |
| Missed check-in | No check-in recorded; check-in time (check-out optional) |
| Missed check-out | A check-in and no check-out; check-out time |
| Incorrect check-in or check-out time | A recorded check-in; at least one changed time |
| Worked but no attendance recorded | No check-in recorded; both times |

**Rules:** date not in the future, within the last 60 days (`ATTENDANCE_CORRECTION_WINDOW_DAYS`), not before joining, and not in a month whose payroll is finalised; times not in the future; check-out after check-in and within 24 hours (tick *next day* for overnight shifts); one pending request per day (also a database constraint); reason of at least 5 characters. Administrators cannot submit requests and employees cannot edit attendance directly.

**Administrator steps:** filter by status (pending by default), type, department, attendance dates or search; compare recorded and requested values; **Approve** (optional note) or **Reject** (reason required). Approval updates the attendance record, marks it *Corrected*, and recalculates the shift snapshot and late minutes when the check-in changes. Approval is refused if that month's payroll was finalised in the meantime.

**Audit and notifications:** the audit entry (module *Attendance*) stores the original and corrected times, the approver, the employee's reason, the note and the time. Administrators are notified of new and cancelled requests; the employee is notified of the decision.

## 31. Team calendar

**Who:** everyone. **Where:** *Company → Team calendar* (`calendar.html`), API `GET calendar/`.

- Month grid (Monday first) with today highlighted and holiday days tinted; up to three events per day plus *+N more*; click a day for its full list. Below the grid, an event list for the month. On phones only the list is shown.
- Event types (toggle each): approved leave (amber), approved work from home (blue), shifts (green), holidays (red). Pending or rejected requests are never shown.
- **Administrators** see all active employees; filters for department, employee and a custom date range (up to 62 days, shown as a list). Explicit shift assignments are shown; a note names the default shift used by everyone else.
- **Employees:** *My schedule* shows their own leave (with type), WFH, their shift for each day and holidays. *Team availability* adds colleagues from their own department, shown only as *On leave* or *Working from home* with dates; leave types, reasons and colleagues' shifts are never sent to the browser. Department and employee filters are ignored for employees.

## 32. Analytics and reports

**Who:** administrators. **Where:** *Payroll → Analytics* (`admin-analytics.html`), API `GET reports/analytics/`, Excel `GET reports/excel/analytics/`.

- **Filters:** from/to month (up to 24 months; quick 3/6/12-month buttons) and department.
- **Summary cards** with the change against the previous period of the same length: payroll cost (gross on payslips), average monthly cost and net pay, overtime cost and hours (approved overtime), headcount at the end with joiners and leavers, late check-ins and late rate, absenteeism (loss-of-pay days ÷ working days on payslips), leave days taken.
- **Charts:** payroll cost by month, overtime cost by month, late rate and absenteeism by month, headcount with joiners and leavers.
- **Tables:** departments (active headcount, payroll cost, net pay, overtime, late check-ins, leave days), leave utilisation for the current leave year (entitled days incl. carry-forward and adjustments, used, pending, utilisation %), monthly check-ins, late count with average late minutes, leave days and absenteeism.
- Notes explain drafts included in totals and employees whose deactivation date is unknown. Empty periods show an explanatory empty state.
- **Excel:** three sheets (monthly trends, departments, leave utilisation) with totals; text is always stored as text. Existing employee, attendance, leave, overtime and payroll Excel reports and the CSV payroll register are unchanged.

Headcount uses the *deactivated on* date now recorded when an employee is deactivated (and cleared on reactivation); the migration filled it from earlier audit entries where possible.

## 33. Employee onboarding

**Who:** employees see their checklist; administrators review. **Where:** employee dashboard; *People → Onboarding* (`admin-onboarding.html`). API `onboarding/`, `onboarding/me/`, `onboarding/settings/`, `onboarding/<id>/complete|reopen|remind/`.

**Checklist** (computed live; no extra personal data is stored): first and last name, email, phone, department and designation (admin), postal address (setting, on by default), profile photo (setting, off by default), each required document type (setting; default identity proof and address proof), counted once **verified** and not expired, and the salary structure (admin; setting, on by default).

**States:** *In progress* → *Ready for review* (all items done; administrators are notified once) → *Completed* (an administrator marked it complete; the employee is notified). If an item stops being satisfied (e.g. a document expires) a ready checklist goes back to in progress.

**Administrator actions:** tabs for open, ready, in progress and completed with counts; search and department filter; *Checklist* (each item with its state and who must act); *Remind* (notifies the employee of items they must provide); *Complete* (refused with the list of missing items while anything is missing; optional note); *Reopen* (reason required); *Checklist settings*. All actions are audited (module *Employees*). Employees who existed before this feature were marked completed by the migration so they are not asked again. Creating, editing, deactivating and reactivating employees work as before.

## 34. Document expiry and reminders

**Expiry:** employees can enter an optional *Expiry date* when uploading (it cannot be in the past); administrators can set it while verifying or later with *Expiry* (`PUT documents/<id>/expiry/`, audited). The expiry status (*Valid*, *Expiring soon* within the largest reminder day, *Expired*, *No expiry*) is a separate column from the review status, and both document pages filter by it. Dashboards show expired and expiring counts with links. Files stay private (owner and administrators only).

**Reminders** (`accounts/reminders.py`; Settings → *Automatic reminders*):
- Documents: the employee and administrators are reminded when the days left first reach a reminder day (default 30, 7, 1; configurable) and once when the document expires. If several days were missed, only the nearest is sent.
- Pending approvals: one digest per day to administrators listing leave, WFH, corrections, overtime and documents waiting at least *N* days (default 2).
- Onboarding: one reminder per week to employees with items they must provide.
- Every reminder is recorded (`ReminderLog`) so it is never sent twice. Reminders run automatically when a dashboard is opened (at most every 6 hours), via *Send due reminders now*, or with `python manage.py send_reminders` (schedule daily). Reminders can be switched off.

## 35. Notification preferences and audit improvements

- **Preferences** (*Settings → Notifications*, `notifications/preferences/`): switch off optional kinds: announcements, attendance, chat, attendance corrections, documents, holidays, leave, overtime, reminders, shifts and work from home. Security alerts (password reset or change, Google connected or disconnected), payslip and employee-record messages, onboarding and messages sent by an administrator cannot be switched off. Muted kinds are not created for that user.
- **Notifications page:** *All / Unread* tabs with the unread count, a type filter and *Mark all as read*; opening a notification marks it read. The API also returns unread counts per type.
- **Audit log:** new filters for employee (the person an action was about, e.g. whose leave was approved, or who did it), action and module (options from recorded entries), plus date range and search, and a new *Employee* column. Newly audited: correction decisions, payroll reviews, onboarding complete/reopen/remind, onboarding and reminder settings, reminder runs, expiry changes and reactivation. Entries are append-only: the API is read-only for administrators, employees get 403, and the model refuses to update or delete an entry.

## 36. AI assistant: new topics and evidence

- The assistant now also retrieves, for the signed-in user only, their **attendance correction requests** (status and the administrator's note), their **onboarding checklist**, and the **expiry** of their documents (separate from review status).
- Leave answers include the **leave rules configured by administrators** (leave-year dates, notice period, per-request limit, past dates) alongside the live balance from the database.
- The model is instructed to **name the record or policy** behind each figure; the *Based on:* line lists the records used.
- Unchanged: the employee is identified from the session (IDs typed in a message are ignored), questions about other people are refused before any data is fetched, only the records needed for the question are sent, history, rename, pin and search work as before, and Gemini errors fall back to answers built from the records.
