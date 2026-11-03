# CPJudge &mdash; Offline (LAN-Only) Programming Judge

A production-grade, offline-first programming judge web application built with **Python 3.10+, Flask, SQLAlchemy, and Docker Compose**. Designed specifically for academic computer science laboratories, programming contests, and university courses operating on a Local Area Network (LAN) with **zero internet access**.

---

## Key Highlights

- **100% Offline LAN Operation:** Zero runtime external network calls. Bootstrap 5, Bootstrap Icons, and CodeMirror 5 are completely bundled locally in `/static/`.
- **Two Roles with Server-Side Enforcement:**
  - **Teacher:** Create/manage problems, test cases (visible vs. hidden), bulk-import students via CSV, create single or multi-problem assignments with deadlines and late penalties, view consolidated gradebook matrices, download CSV reports, trigger rejudges, and inspect immutable audit logs.
  - **Student:** Sign in with Roll Number or Username, change password on first login, navigate multi-problem assignments with quick problem switcher tabs, solve problems in an embedded CodeMirror editor, submit code (C, C++, Python), track evaluation with live 2-second background polling, and review past submissions with strict hidden test privacy.
- **Multi-Problem Assignments:**
  - Assignments support linking 1 or more problems in a defined sequence with automatic backward compatibility.
  - Students view an assignment overview showing per-problem attempts, best verdicts, and points earned.
  - Rapid problem switcher toolbar (`P1`, `P2`, ...) inside the solver portal allows switching between problems in the same assignment without leaving the editor.
  - Per-problem submission scoping: attempt limits (`max_attempts`) are enforced independently per problem.
  - Gradebooks and CSV exports automatically compute total possible marks and student earned scores as the sum across all problems in that assignment.
- **Robust Sandboxed Execution Engine:**
  - Isolated Linux worker daemon atomically claims FIFO work and renews five-minute leases for crash recovery.
  - Hardened sandboxing using Linux **bubblewrap (`bwrap`)**: no network access (`--unshare-net`), read-only filesystem mounts (`--ro-bind`), ephemeral tmpfs `/tmp`, non-root execution, process table isolation, and dropped Linux capabilities.
  - Resource limits: `RLIMIT_CPU` (with monitored fractional CPU limits), `RLIMIT_AS` (virtual address space limit), `RLIMIT_NPROC` (process-count defense), and `RLIMIT_FSIZE` (output size defense).
  - Compiler, checker, and student processes receive restricted environments and resource limits; production refuses to run when Bubblewrap is unavailable.
- **Flexible Scoring & Checkers:**
  - Checkers: `exact`, `token` (whitespace/newline agnostic), `float` (configurable tolerance e.g. `1e-6`), and `custom` (Python checker script).
  - Scoring modes: `per_test` (proportional marks), `all_or_nothing` (all tests must pass for credit), and `grouped` (each subtask group earns marks only when every test in that group passes; prerequisite dependencies are not configured).
  - Late submission penalties (e.g. -20% deduction computed automatically).
- **Test Versioning & Automatic Staleness Detection:**
  - Modifying tests automatically increments problem `tests_version`.
  - Prior submissions are flagged as `is_stale = True` until rejudged.
- **Enterprise Gradebook & Audit Trail:**
  - Class gradebook matrix and single assignment gradebooks.
  - One-click RFC-compliant CSV exports.
  - Immutable audit logs capturing every administrative action, IP address, and details.
- **Database Portability & Hot Backups:**
  - Defaults to SQLite with zero-configuration setup.
  - Swappable with PostgreSQL by setting `DATABASE_URL` (the PostgreSQL driver is installed from `requirements.txt`).
  - Hot, transactionally consistent online backup utility using `sqlite3.Connection.backup()`.

---

## Architecture

```
                       [ LAN Client Browser ]
                                |
               +----------------+----------------+
               | (Port 5000: HTTP, LAN-Only)     |
               v                                 v
    [ Teacher Web UI ]                  [ Student Web UI ]
               |                                 |
               +----------------+----------------+
                                |
                                v
               [ Flask Web Application Process ]
               * CSRF (Flask-WTF)
               * Rate Limiter (Flask-Limiter)
               * Auth & Role Decorators
               * Bleach Markdown Sanitizer
                                |
                                v
                   [ Database (SQLite / Postgres) ]
                      submissions: status='queued'
                                |
                                v
                   [ Judge Worker Daemon ]
                   * Startup Crash Recovery
                   * Atomic FIFO Queue Claiming (queued -> judging)
                   * DB-Backed Evaluation
                                |
                                v
             +-------------------------------------+
             |     Sandboxed Execution Engine      |
             |-------------------------------------|
             | - bubblewrap (bwrap, no net)        |
             | - setrlimit (CPU, RAM, PROC, FSIZE) |
             | - G++ / GCC / Python 3              |
             | - Exact / Token / Float / Custom    |
             +-------------------------------------+
                                |
                                v
                   [ Update Results & Scores ]
                   submissions: status='done', verdict='AC'
                   scores: raw_score, late_penalty, final_score
```

> [!IMPORTANT]
> **Process Separation & Security Guarantee:** Student code is **never** executed inside the web application process. All compilations and executions occur exclusively within the isolated judge worker process wrapped inside Bubblewrap sandboxes.

---

## Install and Run from a Fresh Clone

Docker Compose is the recommended way to run CPJudge. It starts the web application and the separate judge worker, and includes the Linux compilers and Bubblewrap needed to evaluate student programs. The commands below work in PowerShell on Windows, or in a terminal on Linux/macOS unless noted otherwise.

### 1. Install prerequisites

- Install **Git**.
- Install and start **Docker Desktop** on Windows (with its WSL 2 backend enabled), or install **Docker Engine and the Docker Compose plugin** on Linux.
- Confirm Docker is running:

```text
docker --version
docker compose version
```

For Windows, use Docker Desktop with Linux containers. Do not run student submissions directly on a Windows Python installation; the judge's sandbox and compilers are provided by the Linux container.

### 2. Clone the repository and enter its folder

On the repository's GitHub page, click **Code**, copy its HTTPS clone URL, then run:

```text
git clone https://github.com/OWNER/REPOSITORY.git
cd REPOSITORY
```

Replace `OWNER` and `REPOSITORY` with the values from the copied GitHub URL. Run all following commands from the repository root—the directory containing `docker-compose.yml`.

### 3. Create the local environment file

Compose requires a private `SECRET_KEY` when starting the production-configured web and worker services. Generate a random 64-character hexadecimal key and save it in `.env` beside `docker-compose.yml`.

**PowerShell:**

```powershell
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$secret = -join ($bytes | ForEach-Object { $_.ToString('x2') })
$rng.Dispose()
"SECRET_KEY=$secret" | Set-Content -Encoding ascii .env
```

**Linux/macOS:**

```bash
printf 'SECRET_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
```

Keep `.env` private and do not commit it. The default web address is `http://localhost:5050`. To use another host port, add a line such as `PORT=5000` to `.env`; then use `http://localhost:5000`.

### 4. Build and start the application

From the repository root:

```text
docker compose up --build -d
```

The first build downloads the base image and Python packages, so it requires internet access. Once built, the app's static browser assets are served locally. The web service listens inside the container on port `5000`; Compose publishes it on host port `5050` by default.

Check that both services are running:

```text
docker compose ps
```

You should see the `web` and `worker` services running. To inspect startup or judging errors:

```text
docker compose logs --tail=100 web worker
```

### 5. Create the database and optional demo accounts

On a fresh database, initialize the tables and demo content by running:

```text
docker compose exec web python seed.py
```

The seeder is safe to run again; it creates missing demo records and does not reset existing users or data. It provisions the following demo accounts:

| Role | Username / Identifier | Password | Notes |
| :--- | :--- | :--- | :--- |
| **Teacher** | `teacher` | `Teacher@123` | Full administrative access |
| **Student 1** | `bcsf20m001` | `Student@123` | Active student (Alice Johnson) |
| **Student 2** | `bcsf20m002` | `Student@123` | Active student (Bob Smith) |
| **Student 3** | `bcsf20m003` | `Student@123` | Forces password change on login |

These are public demo credentials, not secure production accounts. Change the teacher password after your first sign-in and replace or remove demo accounts before exposing the service to other users. To discard **all** existing database tables and recreate the demo data, run `docker compose exec web python seed.py --drop`; this permanently deletes current users, classes, assignments, and submissions.

### 6. Open CPJudge and check judging

Open [http://localhost:5050](http://localhost:5050) in a browser on the host. Sign in with the teacher demo account, then change its password. The demo class, problems, assignment, and student accounts let you try the workflow. Submit a test program as a student and check `docker compose logs -f worker` to confirm that the worker evaluates it.

To let other machines on your LAN connect, use the host machine's LAN IP and configure its firewall to allow the chosen port. See [deployment_guide.md](./deployment_guide.md) for step-by-step Windows/Linux firewall and lab setup instructions. Do not expose the service directly to the public internet.

### 7. Stop or restart CPJudge

Stop the containers while keeping the database:

```text
docker compose down
```

Start them again later:

```text
docker compose up -d
```

The Compose file bind-mounts the project directory, so the SQLite database under `instance/` remains on the host across container restarts and `docker compose down`. Back up this directory before removing or replacing the clone.

### Troubleshooting

- **Compose says `SECRET_KEY` is not set:** Check that `.env` is in the same folder as `docker-compose.yml`, contains `SECRET_KEY=<your-random-key>`, and that commands are being run from the repository root.
- **The browser cannot connect:** Confirm both containers are running with `docker compose ps`; check `docker compose logs web`; verify the URL uses the configured host port (`5050` by default).
- **Submissions stay queued:** Confirm the `worker` service is running and inspect `docker compose logs worker`.
- **Worker reports Bubblewrap or user-namespace errors:** Run the worker on a Linux host/kernel that permits Bubblewrap user namespaces. Do not disable sandboxing for a production deployment.
- **Docker cannot build or pull images:** Start Docker Desktop/Engine and ensure the machine has internet access for the initial image and package download.

---

## Native Linux Setup (Without Docker)

Use this option only on a Linux host. The judge worker needs Linux tooling, GCC/G++, Python 3, and Bubblewrap for program execution. Docker is still recommended for a repeatable setup. On Windows, use Docker Desktop with its Linux/WSL 2 backend instead of this native setup.

### 1. Install system packages

On Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv gcc g++ bubblewrap procps
```

### 2. Clone the repository and install Python dependencies

Clone the repository as described above, change to its root directory, then run:
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure production and initialize the database

Create a persistent local environment file with a private secret:
```bash
printf 'SECRET_KEY=%s\nFLASK_ENV=production\nAPP_TIMEZONE=Asia/Karachi\n' \
  "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
chmod 600 .env
```

Initialize the database:
```bash
set -a
. ./.env
set +a
source .venv/bin/activate
python seed.py
```

The seed command creates the SQLite database in `instance/cpjudge.db` and adds the demo records listed above. Change the demo teacher password before using the instance with real students.

### 4. Run the web app and worker

Start each process in a separate terminal. In **both** terminals, change to the repository root, activate the virtual environment, and load the same environment file:

```bash
source .venv/bin/activate
set -a
. ./.env
set +a
```

**Web Server:**

```bash
gunicorn -w 4 -b 0.0.0.0:5000 "run:app"
```

**Judge Worker Daemon:**

```bash
python -m cpjudge.worker
```

For local development only, you can instead run `python run.py` with `FLASK_ENV=development`; the built-in server is not intended for production. The development config supplies an insecure fallback secret, so do not use it for a network-accessible deployment.

---

## Teacher Workflows Guide

### 1. Creating Problems
1. Navigate to **Problems** &rarr; **Create Problem**.
2. Fill in:
   - **Title** & Unique **Slug**.
   - **Problem Statement:** GitHub-Flavored Markdown (tables, math KaTeX, code blocks, images).
   - **Limits:** Execution Time Limit (0.1s &ndash; 10.0s), Memory Limit (16 MB &ndash; 1024 MB), Output Limit.
   - **Checker Type:** `token` (standard competitive programming whitespace-insensitive), `exact` (byte-for-byte), `float` (numerical tolerance), or `custom` (Python checker).
   - **Scoring Mode:** `per_test`, `all_or_nothing`, or `grouped`.

### 2. Adding Test Cases & ZIP Uploads
From the problem view, click **Manage Test Cases**:
- **Manual Input:** Enter test name, input data, expected output, marks, and visibility toggle (**Visible** vs. **Hidden**).
- **Bulk ZIP Upload:**
  - Create a ZIP archive containing paired test files:
    - `input_01.txt` & `output_01.txt`
    - `in_02.txt` & `out_02.txt`
    - `1.in` & `1.out`
  - Any pair prefixed with `hidden_` (e.g. `hidden_in_03.txt` & `hidden_out_03.txt`) is automatically marked as **Hidden**.
  - Choose whether to **Overwrite** existing tests or append.
  - Problem `tests_version` will automatically increment, marking prior submissions as stale.

### 3. Creating Classes & Bulk-Importing Students (CSV)
1. Navigate to **Classes** &rarr; **New Class** (e.g., Code: `CS201`, Name: `Data Structures`).
2. Open class details. Under **Bulk Import Students (CSV)**, either upload a `.csv` file or paste raw CSV text:
   ```csv
   roll_no,name
   BCSF22M001,Ayesha Khan
   BCSF22M002,Bilal Ahmed
   BCSF22M003,Fatima Zahra
   ```
3. Click **Import and Enroll Students**:
   - Initial secure passwords are automatically generated.
   - Accounts are marked with `force_password_change = True`.
   - A modal displays all generated credentials for distribution or printing.

### 4. Creating Assignments
1. Navigate to **Assignments** &rarr; **Create Assignment**.
2. Select the **Class** and **Problem**.
3. Set **Open Date (UTC)** and **Due Date (UTC)**.
4. Configure policies:
   - **Max Attempts:** `0` for unlimited, or cap at e.g. `5` attempts.
   - **Late Policy:** Toggle `Allow Late Submissions` and specify penalty deduction percentage (e.g., `20%`).

### 5. Gradebook & CSV Exports
- **Class Gradebook (`/teacher/classes/<id>/gradebook`):**
  - Roster matrix showing each student, their best score per assignment, attempt count, overall total earned, and percentage.
  - Click **Export CSV** to download a spreadsheet report.
- **Assignment Gradebook (`/teacher/assignments/<id>/gradebook`):**
  - Granular breakdown of attempts, raw score, late deduction percentage, final calculated score, and verdict.
  - Includes **Rejudge All** button to re-evaluate all submissions after modifying test cases.

### 6. Audit Trail (`/teacher/audit-logs`)
Every administrative operation is captured in an append-only audit log:
- Actions: `create_problem`, `edit_problem`, `delete_problem`, `upload_tests_zip`, `create_class`, `import_students`, `create_assignment`, `rejudge_submission`, `rejudge_assignment`, `rejudge_problem`, `export_gradebook`, etc.
- Filter by action type using the dropdown.

---

## Student Workflows Guide

### 1. Sign-In & First Login
- Sign in with either **Roll Number** (e.g. `BCSF20M001`) or **Username**.
- If imported via CSV, the student is immediately redirected to change their initial password.

### 2. Solving Assignments
- Dashboard lists active, upcoming, and past assignments with countdowns and attempt badges.
- Problem page displays:
  - Formatted problem statement with sample visible test cases.
  - Embedded **CodeMirror 5 editor** with syntax highlighting, line numbers, and indentation.
  - Dynamic language selector: switching between **C**, **C++**, and **Python** automatically switches CodeMirror syntax highlighting.
  - Direct text submission or source file upload (.c, .cpp, .py).
  - Maximum submission code size: **64 KB**.

### 3. Live Evaluation & Hidden Test Privacy
- Upon submission, the student is redirected to the submission detail page.
- **Live Polling:** The page polls `/student/submissions/<id>/status` every 2 seconds without full page refreshes, automatically reloading once evaluation completes.
- **Read-Only Code Viewer:** Displays the exact submitted source code.
- **Compilation Errors:** If compilation fails (`CE`), the complete compiler diagnostic error is rendered.
- **Strict Hidden Test Privacy:**
  - For visible tests: input, expected output, student output, and checker diff are visible.
  - For hidden tests: input, expected output, student output, diff, and execution feedback are **never returned by the server or stored in student-accessible database fields**. Students only see the verdict badge (`AC`, `WA`, `TLE`, etc.) and score awarded.

---

## Database Backup & Restore

CPJudge includes a dedicated database management utility:

### 1. Create a Hot Backup
Safely creates an online, transactionally consistent snapshot while web and worker processes are actively operating:
```bash
python -m cpjudge.utils.backup --backup
```
Backups are saved to `instance/backups/cpjudge_backup_YYYYMMDD_HHMMSS.db`.

### 2. List Existing Backups
```bash
python -m cpjudge.utils.backup --list
```

### 3. Restore from Backup
Restores the database after automatically taking a pre-restore safety copy of the current database:
```bash
python -m cpjudge.utils.backup --restore instance/backups/cpjudge_backup_20261101_214444.db
```

### 4. Swapping SQLite for PostgreSQL
CPJudge uses standard, portable SQLAlchemy data types. To switch to PostgreSQL:
1. Set the environment variable:
   ```bash
   export DATABASE_URL="postgresql://cpjudge:YOUR_DATABASE_PASSWORD@localhost:5432/cpjudge_db"
   ```
   Replace the username, password, host, port, and database name with your PostgreSQL values. URL-encode special characters in the password.
2. Initialize tables:
   ```bash
   python seed.py
   ```

---

## Running the Automated Test Suite

CPJudge has a comprehensive automated test suite covering all layers:

To run all tests inside the Docker environment:
```bash
docker compose run --rm test pytest -v
```
Or directly using pytest:
```bash
pytest -v
```
Sandbox integration tests require Bubblewrap with Linux user-namespace support. They are reported as skipped when the current environment cannot create those namespaces; this often applies to Docker Desktop. The production worker does not skip this requirement and refuses to start without a functional Bubblewrap sandbox. Run the sandbox integration tests on a Linux host with user namespaces enabled.

### Test Suite Coverage Breakdown
- `tests/test_selftests.py`: Sandbox security, C/C++/Python execution, TLE infinite loop, MLE memory limit, OLE output limit, RE segfault, fork-bomb defense, filesystem read protections.
- `tests/test_compiler.py`: GCC, G++, Python compilation and syntax diagnostics.
- `tests/test_checker.py`: Exact, token, float, and custom Python checkers.
- `tests/test_scorer.py`: Per-test, all-or-nothing, grouped subtasks, and late penalties.
- `tests/test_models.py`: Database models, password hashing, enrollments, test versioning.
- `tests/test_auth.py`: Login by username/roll number, password change enforcement, role authorization.
- `tests/test_teacher_ui.py`: Problem CRUD, test case ZIP uploads, student CSV imports, assignments.
- `tests/test_student_ui.py`: CodeMirror editor, 64 KB upload ceiling, attempt limits, hidden test privacy, live polling.
- `tests/test_worker.py`: Worker queue claiming (FIFO), crash recovery, score upserts, staleness detection.
- `tests/test_gradebook_and_rejudge.py`: Matrix gradebook, assignment gradebook, CSV exports, rejudging, audit filtering.
- `tests/test_backup.py`: SQLite hot backup and transactional restore.

---

## Security Hardening Verification Checklist

- [x] **Zero Internet Dependency:** No external CDN links, Google Fonts, or remote scripts anywhere.
- [x] **CSRF Protection:** Flask-WTF CSRF tokens validated on all POST/PUT/DELETE forms.
- [x] **Rate Limiting:** Flask-Limiter protecting authentication and submission endpoints against spam and brute-force.
- [x] **Input Sanitization:** Bleach sanitizes problem statements allowing only safe HTML tags and stripping script/event handlers.
- [x] **Payload Restrictions:** Strict 64 KB source code submission limit; 16 MB maximum for teacher ZIP test archives.
- [x] **Sandboxing:** Linux Bubblewrap (`bwrap`) isolation with `--unshare-net`, restricted mounts, non-root user, and setrlimit resource caps.
- [x] **Hidden Test Data Privacy:** Server never transmits hidden test inputs, outputs, or diffs to students.
- [x] **Stale Score Handling:** Test modifications increment problem version and mark old scores stale until rejudged.
- [x] **Audit Logging:** Administrative actions, exports, imports, and rejudges recorded with IP addresses.
