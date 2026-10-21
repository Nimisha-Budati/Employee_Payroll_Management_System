# PayrollPro verified knowledge base
<!-- Each "## " section is one retrievable topic. "Keywords:" lines help retrieval and are not shown to users.
     Every statement here is checked against the implemented pages, API rules and payroll code. -->

## Applying for work from home (WFH)
Keywords: wfh work from home remote apply request how submit cancel home office
1. In the sidebar open **My work → Work from home**.
2. Click **Request WFH**.
3. Choose the **From** and **To** dates and type a **Reason** (up to 500 characters), then click **Submit request**.
4. The request is saved as **Pending** and every administrator is notified.
Rules the system enforces:
- The end date cannot be before the start date.
- A new request cannot overlap one of your requests that is already Pending or Approved.
- While a request is **Pending** you can click **Cancel** on the Work from home page; it becomes Cancelled and administrators are notified. Approved or rejected requests cannot be cancelled.
- An administrator approves it, or rejects it with a required note. You get a notification either way and the note is shown under the request ("Response: …").
- Approved WFH days count as paid working days in payroll. WFH does not use leave balance.

## Applying for leave
Keywords: leave apply request how holiday off casual sick earned other unpaid submit
1. Open **My work → Leave** and click **Apply for leave**.
2. Choose the **Leave type** (the list shows each type your administrator has set up, with the days you can still request), the **From** and **To** dates and a **Reason**, then click **Submit request**.
3. The request is **Pending** until an administrator approves or rejects it. You are notified either way; a rejection may include a reason.
Rules the system enforces:
- Days are counted as calendar days from the start date to the end date, inclusive.
- A request cannot overlap one of your Pending or Approved leave requests.
- For leave types with an annual limit, the requested days cannot exceed what you can still request this leave year (pending requests are reserved, so they count against it). If your balance is used up, apply for an unlimited unpaid type if your administrator offers one.
- While a request is **Pending** you can click **Cancel** on the Leave page; cancelled and rejected requests never reduce your balance.
- The Leave page shows a card for each leave type: total allowed, used (approved), pending and available days.

## Leave balance and entitlements
Keywords: leave balance left remaining entitlement days casual sick earned quota how many policy carry forward year
{leave_entitlements}
- Leave types, their annual days, whether they are paid and carry-forward rules are set by administrators and can change.
- Total allowed = annual days + days carried forward + any adjustment by an administrator.
- Used = approved days; pending requests are shown separately. Available = total − used. You can still request available − pending days.
- Rejected and cancelled requests do not use any balance.
- Approved paid leave days are paid in payroll; approved unpaid leave days are loss of pay.

## Payslips: where to find and download them
Keywords: payslip download pdf view salary slip where find latest month paid
- Open **My pay → Payslips**. Choose a year to list your payslips.
- Only **finalised (Paid)** payslips are shown. A month's payslips appear after an administrator runs payroll for the finished month and finalises it; draft payslips are never visible to employees.
- **View** opens the full breakdown on screen; **PDF** downloads an A4 payslip.
- You are notified ("Payslip available") when a payslip is published.

## How a payslip is calculated
Keywords: salary calculation net gross deduction lop loss of pay pf provident fund tax tds professional da hra bonus overtime formula how calculated
- **Working days** = weekdays (Mon–Fri by default) minus company holidays in the month.
- A working day is **paid** when you checked in, were on approved paid leave or had approved WFH. Approved "Other" leave and days before your joining date are not paid. Unpaid working days are **loss of pay (LOP) days**.
- **Fixed gross** = Basic + HRA + DA + Conveyance + Medical + Special allowance + Other allowance.
- **Gross earnings** = fixed gross + overtime pay + bonus.
- **LOP deduction** = fixed gross × LOP days ÷ working days.
- **Provident fund (PF)** = PF % × (Basic + DA), reduced in proportion to LOP days.
- **Professional tax** and **income tax (TDS)** are fixed monthly amounts from your salary structure, reduced in proportion to LOP days. PayrollPro does not calculate tax slabs.
- **Other deductions** (for example a loan instalment) are taken in full.
- **Overtime pay** = approved overtime hours × the hourly rate on each approved record. Unapproved overtime is not paid.
- **Bonus**: the monthly bonus in your salary structure is paid in full (not reduced for LOP); an administrator may change it on a draft payslip for one-off awards.
- **Total deductions** = PF + professional tax + TDS + other deductions + LOP deduction. **Net salary** = gross earnings − total deductions.

## Salary components explained
Keywords: basic hra da dearness allowance conveyance medical special allowance meaning what is component
- **Basic pay**: the core fixed part of salary; PF is calculated on Basic + DA.
- **HRA (house rent allowance)**: a fixed monthly allowance for housing.
- **DA (dearness allowance)**: a fixed monthly allowance; it is part of fixed gross and of the PF wage.
- **Conveyance, medical, special and other allowances**: fixed monthly allowances set in your salary structure.
- **Overtime pay**: payment for approved overtime hours.
- **Bonus**: a monthly or one-off bonus paid in full.
- **PF (provident fund)**: retirement savings deduction, PF % of Basic + DA.
- **Professional tax**: a state tax deducted monthly.
- **TDS (income tax)**: income tax deducted at source, a fixed monthly amount set by an administrator.
- **LOP deduction**: salary reduction for unpaid working days.

## Attendance and check-in
Keywords: attendance check in check out gps location radius office mark present
1. Open **My work → Attendance & shift**.
2. Click **Check in**. Your browser asks to share your location; you must be within the office radius set by an administrator.
3. At the end of the day click **Check out** (same location check).
- One record per day; you cannot check in twice, check out twice or check out before checking in.
- If the office location has not been configured, the page says attendance has not been set up yet.
- The page shows today's times, minutes late, your shift and your last 30 records.

## Shifts and late minutes
Keywords: shift late minutes grace period start time punctual on time timing
- Administrators assign shifts; your current shift and history are on **Attendance & shift**. Employees without an assignment use the company's default shift, if one is set.
- Checking in within the shift's **grace period** counts as on time (0 late minutes). After the grace period, late minutes are counted from the shift start (for example 09:52 against a 09:30 start with 10 minutes' grace is 22 minutes late).
- With no shift and no default shift, late minutes are not recorded.

## Overtime claims
Keywords: overtime claim extra hours ot approval rate paid
1. Open **My work → Overtime** and click **Claim overtime**.
2. Enter the **Date worked** (today or earlier), **Hours** (quarter-hour steps, 0.25–16) and a reason, then submit.
- The rate comes from your salary structure; the amount is hours × rate.
- Claims are **Pending** until an administrator approves or rejects them (a rejection includes a reason). You can edit or cancel a pending claim.
- Only **approved** overtime is added to your payslip. Overtime in a month whose payroll is finalised cannot change.

## Documents
Keywords: document upload id proof certificate resume verify file
- Open **My work → Documents**, click **Upload document**, enter a title, choose the type (Identity proof, Address proof, Education certificate, Resume or Other) and a PDF, JPG or PNG file up to 5 MB.
- Documents are **Pending review** until an administrator verifies or rejects them (with a reason). You can delete a document only while it is pending. Files are private to you and administrators.
- Documents such as a passport, visa or licence can have an **Expiry date** (enter it when uploading; an administrator can also set or change it). Expiry is shown separately from the review status: **Valid**, **Expiring soon** or **Expired**.
- PayrollPro reminds you and the administrators before a document expires (by default 30, 7 and 1 days before, set by administrators) and once it has expired. Upload a renewed copy when reminded.

## Attendance corrections
Keywords: attendance correction missed check in forgot check out wrong time fix attendance punch request
- You cannot edit attendance yourself. If you forgot to check in or out, or a time is wrong, open **My work → Attendance & shift** and click **Request correction**.
- Choose the date, the type (**Missed check-in**, **Missed check-out**, **Incorrect check-in or check-out time**, or **Worked but no attendance recorded**), the correct time(s) and a reason. Tick **next day** for a check-out after midnight.
- Rules: the date must be today or earlier, within the last 60 days (unless an administrator changed this), on or after your joining date, and in a month whose payroll is not finalised. Times cannot be in the future and check-out must be after check-in. Only one pending request per day.
- The request is **Pending** until an administrator approves or rejects it (a rejection includes a reason). You can cancel it while it is pending. Your attendance changes only when it is approved; corrected days are marked **Corrected**, and late minutes are recalculated from your shift.

## Team calendar
Keywords: team calendar who is on leave availability schedule month view colleagues
- Open **Company → Team calendar**. **My schedule** shows your approved leave, approved work from home, your shift and holidays. **Team availability** shows who in your department is on leave or working from home (without leave types or reasons).
- Use the arrows to move between months. Administrators can filter by employee, department, date range and event type.

## Onboarding checklist
Keywords: onboarding checklist new joiner joining documents profile complete submit provide
- New employees see an **Onboarding checklist** on their dashboard. It lists what is still needed: name, email, phone, address (and photo, if required) in **My profile**, the required documents (by default identity proof and address proof) in **Documents**, and items an administrator completes (department, designation and salary structure).
- A document counts once an administrator has verified it and it has not expired.
- When everything is provided, administrators are notified and review it. Onboarding is complete only after an administrator marks it complete; you are notified.

## Notification settings
Keywords: notification preferences mute turn off reminders unread bell settings
- Open **Settings → Notifications** to switch optional notification types on or off (for example announcements, chat, attendance or reminders). Security alerts (password and Google sign-in changes), payslip and employee-record messages, onboarding and messages an administrator sends you are always delivered.
- The bell shows your unread count. On **Notifications** you can filter to unread items and mark one or all as read.

## Holidays, announcements, notifications and messages
Keywords: holiday calendar announcement notification bell message chat admin
- **Company → Holiday calendar** shows holidays (Fixed or Tentative). Holidays are not working days in payroll.
- **Company → Announcements** lists company news; **Messages** holds private conversations that administrators start with you.
- The bell shows notifications about your requests, payslips, shifts and announcements; some notifications sent by administrators expire.

## Profile, password and sign-in
Keywords: password reset forgot change otp code profile photo google sign in login email phone
- **My profile**: update your name, email, phone, address and photo (JPG/PNG up to 2 MB).
- **Settings → Change password** needs your current password.
- **Forgot password** on the sign-in page emails a 6-digit code that is valid for 10 minutes (5 attempts), then lets you set a new password.
- **Settings → Google account** connects Google sign-in. Five failed sign-ins lock sign-in for 15 minutes.

## Who to contact
Keywords: contact hr admin help support problem wrong error dispute
- For attendance mistakes use **Request correction** on **Attendance & shift**. For corrections to your payslip, salary structure or other requests, contact an administrator (HR/payroll). You can message them through **Company → Messages** once they start a conversation with you.
- The assistant cannot change any records.
