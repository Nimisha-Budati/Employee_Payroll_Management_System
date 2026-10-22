# Deploying PayrollPro on Render

This guide explains how to deploy PayrollPro to [Render](https://render.com) with a managed PostgreSQL database and a unified web service serving both the Django backend and the frontend.

---

## Method 1: Automatic 1-Click Deployment (Recommended via Blueprint)

The repository includes a ready-to-use `render.yaml` blueprint.

### Step 1: Push your latest code to GitHub
Make sure all your latest changes are pushed to your GitHub repository:
[https://github.com/Nimisha-Budati/Employee_Payroll_Management_System](https://github.com/Nimisha-Budati/Employee_Payroll_Management_System)

### Step 2: Connect to Render
1. Go to [https://render.com](https://render.com) and sign in (or sign up with your GitHub account).
2. On your Render Dashboard, click the blue **New +** button in the top right.
3. Select **Blueprint**.
4. Connect your GitHub repository `Nimisha-Budati/Employee_Payroll_Management_System`.
5. Render will automatically detect `render.yaml` and display the resources it will create:
   - **Database:** `payrollpro-db` (Managed PostgreSQL)
   - **Web Service:** `payrollpro` (Python Web Service running Gunicorn & WhiteNoise)
6. Click **Apply**.

Render will now:
- Provision your PostgreSQL database.
- Build the web service using `build.sh` (installing dependencies, collecting static files, and applying database migrations).
- Launch the application with Gunicorn.

---

## Method 2: Manual Setup on Render

If you prefer to configure the services manually on Render:

### Step 1: Create the PostgreSQL Database
1. On your Render dashboard, click **New +** -> **PostgreSQL**.
2. Name: `payrollpro-db`
3. Database: `employee_payroll`
4. User: `payroll_user`
5. Plan: **Free** (or Starter)
6. Click **Create Database**.
7. Once created, copy the **Internal Database URL** (e.g. `postgresql://payroll_user:...@dpg-...:5432/employee_payroll`).

### Step 2: Create the Web Service
1. On your Render dashboard, click **New +** -> **Web Service**.
2. Connect your repository `Nimisha-Budati/Employee_Payroll_Management_System`.
3. Configure settings:
   - **Name:** `payrollpro`
   - **Region:** Closest to you (e.g. Singapore or Frankfurt)
   - **Branch:** `main`
   - **Runtime:** `Python 3`
   - **Build Command:** `./build.sh`
   - **Start Command:** `gunicorn --chdir backend config.wsgi:application`
   - **Plan:** **Free** (or Starter)
4. Under **Environment Variables**, add:
   - `DATABASE_URL`: *(paste the Internal Database URL from Step 1)*
   - `DJANGO_SECRET_KEY`: *(click Generate or enter a long random string)*
   - `DJANGO_DEBUG`: `False`
   - `PYTHON_VERSION`: `3.12.0`
   - `GEMINI_API_KEY`: *(optional, paste your Google Gemini API key for AI features)*
5. Click **Create Web Service**.

---

## Initializing Your Live Application

Once your deployment status displays **Live**:

### Option A: Register your organization via UI
1. Open your live URL: `https://<your-subdomain>.onrender.com/company-register.html`.
2. Fill in your Company Name, Administrator credentials, and password.
3. Click **Create company workspace**. You will be logged in immediately to your live admin dashboard.

### Option B: Create a superuser via the Render Web Shell
1. Go to your Render Web Service dashboard.
2. Click **Shell** in the left sidebar.
3. Run:
   ```bash
   python backend/manage.py createsuperuser
   ```
4. Enter your desired username, email, and password.
5. Log in at `https://<your-subdomain>.onrender.com/index.html` choosing the **Administrator** role.

---

## Architecture in Production

- **Unified Origin:** Django serves the REST API (`/api/`) and WhiteNoise serves the frontend HTML/CSS/JS files directly at the root (`/`, `/index.html`, etc.).
- **Cookies & Security:** Because the frontend and backend share the exact same domain, session cookies (`SameSite=Lax`, `HttpOnly`, `Secure`) and CSRF protection work seamlessly without cross-origin configuration.
- **Uploaded Media:** Profile photos are served under `/media/profile_photos/`. Employee documents are never publicly accessible and are streamed privately through authenticated API endpoints.
