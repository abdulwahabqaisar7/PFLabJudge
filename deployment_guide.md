# CPJudge &mdash; Lab Deployment & Implementation Guide

A practical, step-by-step guide for Computer Science instructors, Teaching Assistants (TAs), and Lab Administrators to deploy and run **CPJudge** across university computer lab workstations over a Local Area Network (LAN) with **zero internet access**.

---

## Table of Contents

1. [Lab Architecture Overview](#1-lab-architecture-overview)
2. [Prerequisites & System Requirements](#2-prerequisites--system-requirements)
3. [Server Machine (Host) Setup](#3-server-machine-host-setup)
   - [Method A: Windows Host with Docker Desktop (Recommended for Windows Labs)](#method-a-windows-host-with-docker-desktop)
   - [Method B: Linux Server / Host (Ubuntu / Debian)](#method-b-linux-server--host-ubuntu--debian)
4. [LAN Network & Firewall Configuration](#4-lan-network--firewall-configuration)
   - [Step 4.1: Find the Server's LAN IP Address](#step-41-find-the-servers-lan-ip-address)
   - [Step 4.2: Open Inbound Port in Windows Firewall](#step-42-open-inbound-port-in-windows-firewall)
   - [Step 4.3: Open Inbound Port on Linux (ufw / iptables)](#step-43-open-inbound-port-on-linux-ufw--iptables)
   - [Step 4.4: Recommended: Set a Static LAN IP for the Host](#step-44-recommended-set-a-static-lan-ip-for-the-host)
5. [Student Lab PCs Configuration (Clients)](#5-student-lab-pcs-configuration-clients)
   - [Zero Client Software Installation](#zero-client-software-installation)
   - [Creating a Desktop Shortcut on Student PCs](#creating-a-desktop-shortcut-on-student-pcs)
   - [Optional: Local DNS / Hosts Entry](#optional-local-dns--hosts-entry)
6. [Pre-Lab Workflow (Teacher Setup)](#6-pre-lab-workflow-teacher-setup)
   - [Step 6.1: Initial Database Seeding](#step-61-initial-database-seeding)
   - [Step 6.2: Sign In & Change Default Teacher Password](#step-62-sign-in--change-default-teacher-password)
   - [Step 6.3: Create Class Section & Bulk Import Students](#step-63-create-class-section--bulk-import-students)
   - [Step 6.4: Prepare Problems & Test Cases (Visible vs. Hidden)](#step-64-prepare-problems--test-cases-visible-vs-hidden)
   - [Step 6.5: Publish Multi-Problem Assignment](#step-65-publish-multi-problem-assignment)
7. [Conducting the Lab Session (Exam / Contest / Lab Task)](#7-conducting-the-lab-session-exam--contest--lab-task)
   - [Student Experience](#student-experience)
   - [Teacher Live Monitoring & Rejudging](#teacher-live-monitoring--rejudging)
8. [Post-Lab Workflow: Gradebook Export & Hot Backups](#8-post-lab-workflow-gradebook-export--hot-backups)
   - [Exporting Gradebook to CSV](#exporting-gradebook-to-csv)
   - [Taking an Offline Database Hot Backup](#taking-an-offline-database-hot-backup)
   - [Restoring from Backup](#restoring-from-backup)
9. [Troubleshooting & Frequently Asked Questions](#9-troubleshooting--frequently-asked-questions)

---

## 1. Lab Architecture Overview

CPJudge is designed specifically for academic labs where internet access may be restricted, slow, or disabled during exams to prevent cheating.

```
                              [ Lab Switch / Wi-Fi Router (LAN) ]
                                               |
                     +-------------------------+-------------------------+
                     |                                                   |
           [ Teacher / Server PC ]                             [ 30-60+ Student Lab PCs ]
         Runs CPJudge Docker Engine                       Only require any Web Browser!
        IP: 192.168.1.100 (Example)                         Point to: http://192.168.1.100:5050
                     |
       +-------------+-------------+
       |                           |
  [ Web Process ]           [ Worker Daemon ]
  - Flask App               - Isolated Sandbox
  - Port 5050                 - Docker-backed disposable sandboxes
  - SQLite/PostgreSQL       - G++ / GCC / Python 3
  - Pakistan Time (PKT)     - Submissions Queue
```

### Key Principles for Lab Deployment
- **Zero Internet Requirement:** All CSS (Bootstrap 5), Icons (Bootstrap Icons fonts), and JavaScript editor libraries (CodeMirror 5) are stored locally on the server. No CDN or external URL is ever requested.
- **Client Zero-Install:** Student computers require **no software installation** (no Python, no compilers, no judge client). Any web browser (Chrome, Firefox, Edge) works out of the box.
- **Sandboxed Security:** Student code compiles and executes in disposable Linux containers with no network, a read-only root filesystem, a non-root identity, and resource limits. The Docker socket is available only to the trusted worker, never to the web or student containers.
- **Pakistan Standard Time (PKT, UTC+5):** All deadlines, timers, submission timestamps, and gradebook exports are synchronized to Pakistan Standard Time.

---

## 2. Prerequisites & System Requirements

### Host / Server PC (Only 1 Machine Needed)
This can be the instructor's PC in the lab, a designated lab server, or a laptop connected to the lab switch.

| Component | Minimum Specification | Recommended Specification (for 40-60 students) |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11 (64-bit) with Docker Desktop Linux containers **OR** Ubuntu 20.04/22.04/24.04 LTS | Ubuntu 22.04 LTS or Windows 11 Pro with Docker Desktop |
| **CPU** | Quad-core CPU (Intel i5/AMD Ryzen 5) | 6+ Cores (Intel i7/AMD Ryzen 7 or Server Xeon) |
| **RAM** | 8 GB RAM | 16 GB RAM |
| **Disk Space** | 10 GB free space | 20 GB free space (SSD recommended for fast compilation) |
| **Software** | Docker Desktop (Windows) or Docker Engine + Compose plugin (Linux) | Docker Desktop (Windows) or Docker Engine + Compose plugin (Linux) |

### Student Lab PCs (30 to 60+ Machines)
- Any operating system: Windows 7/10/11, Ubuntu, Linux Mint, macOS.
- Any modern web browser: Google Chrome, Mozilla Firefox, Microsoft Edge, or Brave.
- Connected via Ethernet or Wi-Fi to the same local network subnet as the Host PC.

---

## 3. Server Machine (Host) Setup

### Method A: Windows Host with Docker Desktop

If your lab instructor machine runs Windows 10 or Windows 11:

1. **Install Docker Desktop for Windows:**
   - Enable the **WSL 2 backend** and use **Linux containers**.
   - Start Docker Desktop and wait until its engine is running.
   - No separate host installation of Python, GCC/G++, Linux, or Bubblewrap is required; Compose builds the sandbox image.

2. **Download / Copy CPJudge Repository:**
   - Copy the project folder (e.g. `LabJudge`) to your host machine:
     ```text
     D:\PUCIT\TAship\LabJudge
     ```

3. **Configure the production secret:**
   - In PowerShell, generate a random key:
     ```powershell
     python -c "import secrets; print(secrets.token_hex(32))"
     ```
   - Save the value as `SECRET_KEY=<generated-value>` in a local `.env` file beside `docker-compose.yml`. Do not share or commit this file.

4. **Start CPJudge Containers:**
   - Open PowerShell or Windows Terminal in `D:\PUCIT\TAship\LabJudge`.
   - Run:
     ```powershell
     docker compose up --build -d
     ```
   - Docker will build the application/sandbox image and start the web application and worker. The worker creates a new restricted sandbox container for each compile and run.

5. **Verify Container Status:**
   ```powershell
   docker compose ps
   ```
   You should see:
   - `labjudge-web-1` (running on port `0.0.0.0:5050->5000/tcp`)
   - `labjudge-worker-1` (running judge evaluation daemon)
   - The worker must start successfully with the Docker socket mounted. If it reports a missing daemon or image, check that Docker Desktop is running in Linux-container mode.

6. **Test in Browser on the Host:**
   - Open `http://localhost:5050` in Chrome/Edge on the host computer. You should see the CPJudge login portal.

---

### Method B: Linux Server / Host (Ubuntu / Debian)

If using a dedicated Ubuntu Linux lab server:

1. **Install Docker & Docker Compose Plugin:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y docker.io docker-compose-v2
   sudo systemctl enable --now docker
   sudo usermod -aG docker $USER
   ```
   *(Log out and back in for group membership to take effect)*

2. **Navigate to Project Directory & Start:**
   ```bash
   cd /path/to/LabJudge
   python3 -c "import secrets; print(secrets.token_hex(32))"
   # Save the generated value as SECRET_KEY=<generated-value> in .env; keep it private.
   docker compose up --build -d
   ```

3. **Verify Execution:**
   ```bash
   docker compose ps
   ```

---

## 4. LAN Network & Firewall Configuration

For student PCs to access the judge, the Server machine must be accessible over the lab network on port `5050`.

### Step 4.1: Find the Server's LAN IP Address

On the **Server PC**:

- **On Windows (PowerShell / Command Prompt):**
  ```powershell
  ipconfig
  ```
  Look for your active Ethernet adapter or Wi-Fi adapter IPv4 address:
  ```text
  IPv4 Address. . . . . . . . . . . : 192.168.1.100
  ```
  *(In this example, your server LAN IP is `192.168.1.100`)*

- **On Linux:**
  ```bash
  ip -4 addr show scope global | grep inet
  ```

---

### Step 4.2: Open Inbound Port in Windows Firewall

By default, Windows Defender Firewall blocks inbound connections on port 5050 from other lab computers. You must allow port 5050 once:

#### Option 1: Using PowerShell (Run as Administrator) &mdash; Fastest!
Open **PowerShell as Administrator** on the Server PC and run:
```powershell
New-NetFirewallRule -DisplayName "CPJudge Lab Port 5050" -Direction Inbound -LocalPort 5050 -Protocol TCP -Action Allow
```

#### Option 2: Using Windows GUI:
1. Press `Win + R`, type `wf.msc` and press Enter (opens Windows Defender Firewall with Advanced Security).
2. Click **Inbound Rules** in the left sidebar $\to$ Click **New Rule...** in the right sidebar.
3. Select **Port** $\to$ Click **Next**.
4. Select **TCP** and enter Specific local ports: `5050` $\to$ Click **Next**.
5. Select **Allow the connection** $\to$ Click **Next**.
6. Check **Domain**, **Private**, and **Public** $\to$ Click **Next**.
7. Name the rule `CPJudge Port 5050` $\to$ Click **Finish**.

---

### Step 4.3: Open Inbound Port on Linux (ufw / iptables)

On Ubuntu Linux servers running `ufw`:
```bash
sudo ufw allow 5050/tcp comment 'CPJudge Lab LAN Access'
sudo ufw status
```

---

### Step 4.4: Recommended: Set a Static LAN IP for the Host

To ensure the server IP does not change when the lab router or switch reboots:
1. Open Windows Network Settings $\to$ Change adapter options $\to$ Ethernet Properties.
2. Select **Internet Protocol Version 4 (TCP/IPv4)** $\to$ Click **Properties**.
3. Set a static IP within your lab range (e.g. `192.168.1.100`, Subnet mask: `255.255.255.0`, Gateway: `192.168.1.1`).
4. Alternatively, configure a DHCP reservation on your lab router for the instructor PC's MAC address.

---

## 5. Student Lab PCs Configuration (Clients)

### Zero Client Software Installation
Student computers do **not** require any compilers, software, or Python installed.

### Creating a Desktop Shortcut on Student PCs
To make it effortless for students to open the judge:

1. **On Windows Student PCs:**
   - Right-click Desktop $\to$ **New** $\to$ **Shortcut**.
   - In location, enter:
     ```text
     http://192.168.1.100:5050
     ```
     *(Replace `192.168.1.100` with your Server's actual LAN IP)*
   - Name the shortcut: `CPJudge - Lab Portal`.
   - Click **Finish**.

2. **Distributing Across Lab Machines:**
   - If your lab uses software like NetSupport, DeepFreeze, or Active Directory Group Policy, push the desktop shortcut or browser homepage URL once:
     ```text
     http://192.168.1.100:5050
     ```

### Optional: Local DNS / Hosts Entry
If you prefer students type a human-friendly URL like `http://judge.lab:5050`:
1. On each student PC, open `C:\Windows\System32\drivers\etc\hosts` as Administrator.
2. Add the line:
   ```text
   192.168.1.100    judge.lab
   ```
3. Students can now navigate to:
   ```text
   http://judge.lab:5050
   ```

---

## 6. Pre-Lab Workflow (Teacher Setup)

Before students arrive at the lab, perform these 5 quick preparation steps:

### Step 6.1: Initial Database Seeding
To initialize the database with demo accounts and verify everything works:
```powershell
docker exec labjudge-web-1 python seed.py
```
*(Use `python seed.py --drop` if you want a clean reset of all tables)*

Default initial credentials:
- **Teacher Account:** Username `teacher` / Password `Teacher@123`
- **Demo Students:** `bcsf20m001`, `bcsf20m002`, `bcsf20m003` / Password `Student@123`

---

### Step 6.2: Sign In & Change Default Teacher Password
1. Open `http://localhost:5050` (or `http://192.168.1.100:5050`).
2. Log in with `teacher` / `Teacher@123`.
3. Click your username in the top right navbar $\to$ **Profile** $\to$ **Change Password**.
4. Set a strong password known only to instructors and TAs.

---

### Step 6.3: Create Class Section & Bulk Import Students

1. **Create Class:**
   - In the top navbar, click **Classes** $\to$ **+ Create New Class**.
   - Enter Class Name (e.g. `Programming Fundamentals - Section A`) and Class Code (e.g. `CS101-FA24`).
   - Click **Save Class**.

2. **Bulk Import Student Roster (via CSV):**
   - Click **Manage Students** for your new class.
   - Click **+ Bulk Import Students**.
   - You can either upload a `.csv` file or paste text directly.
   - CSV format:
     ```csv
     roll_no,name
     BCSF24M001,Muhammad Ali
     BCSF24M002,Fatima Zahra
     BCSF24M003,Usman Tariq
     BCSF24M004,Ayesha Khan
     ```
   - Click **Import Students**.
   - CPJudge will automatically create user accounts with their roll number, generate a default password (`Student@123`), and flag them to **force change their password upon first login**.

---

### Step 6.4: Prepare Problems & Test Cases (Visible vs. Hidden)

1. **Create a Problem:**
   - In navbar, click **Problems** $\to$ **+ Create Problem**.
   - Fill in:
     - **Title:** e.g., `Reverse an Array`
     - **Statement:** Write markdown explaining the problem, constraints, input format, and output format.
     - **Time Limit:** e.g., `1.0` second.
     - **Memory Limit:** e.g., `256` MB.
     - **Checker Type:** Select `Token` (whitespace/line-ending insensitive, best for CP) or `Exact`.
     - **Scoring Mode:** Select `Per-Test Partial Marks` or `All or Nothing`.
   - Click **Save Problem**.

2. **Add Test Cases:**
   - Click **Manage Tests** on the problem.
   - **Manual Entry:** Click **+ Add Test Case**.
     - Enter `Standard Input` and `Expected Output`.
     - Assign marks (e.g. `25.0`).
     - Check **Hidden Test** if you want to keep the input/output hidden from students during evaluation.
   - **Bulk ZIP Upload:** If you have existing test packages:
     - Click **Bulk Upload (ZIP)**.
     - Upload a `.zip` file containing paired `.in` and `.ans` files:
       ```text
       01.in       01.ans
       02.in       02.ans
       03_hidden.in  03_hidden.ans
       ```
     - Visibility mode can automatically detect hidden tests from file names!

---

### Step 6.5: Publish Multi-Problem Assignment

1. In navbar, click **Assignments** $\to$ **+ Create Assignment**.
2. Select your **Class**.
3. In **Problems in Assignment**, select one or multiple problems (hold `Ctrl` or `Cmd` to select multiple problems, e.g. `Problem 1` and `Problem 2`).
4. Set **Open Date & Time** and **Due Date & Time** in **Pakistan Standard Time (PKT)**.
5. Set **Max Attempts** (e.g. `5` attempts per problem, or `0` for unlimited).
6. Configure Late Policy (Allow late submissions with e.g. 15% penalty, or disable late submissions).
7. Click **Save Assignment**.

---

## 7. Conducting the Lab Session (Exam / Contest / Lab Task)

### Student Experience

1. Student opens browser and navigates to `http://192.168.1.100:5050`.
2. Student logs in using their **Roll Number** (e.g. `BCSF24M001`) and initial password (`Student@123`).
3. On first login, the student is prompted to set their personal private password.
4. From their Dashboard, the student clicks **View Problems** on the active assignment.
5. In the **Assignment Overview**, they see all problems, their individual point values, attempts made, and current scores.
6. When solving a problem:
   - The student reads the statement and visible sample test cases.
   - They write code directly in the embedded **CodeMirror Editor** (with syntax highlighting, line numbers, and indentation) or upload their source file (`.c`, `.cpp`, `.py`).
   - Top problem switcher tabs (`P1`, `P2`, ...) allow fast jumping between assignment problems.
   - The student clicks **Submit Solution**.
7. The student is taken to the **Submission Detail** page:
   - Live 2-second polling automatically tracks queue status (`Queued` $\to$ `Judging` $\to$ `Done`).
   - Test results display pass/fail verdicts, execution time, and memory.
   - Hidden tests strictly conceal inputs and expected outputs, showing only the verdict.

---

### Teacher Live Monitoring & Rejudging

During the lab, instructors and TAs have real-time visibility:

- **Live Submissions Stream:**
  Click **Submissions** in the navbar to watch student submissions roll in with live execution times, memory usage, and scores.
- **Audit Logs:**
  Click **Audit Logs** to view immutable records of all logins, submissions, and administrative events.
- **Mid-Lab Rejudging (Fixing a Test Case):**
  If an instructor discovers a flaw in a test case during the lab:
  1. Go to **Problems** $\to$ edit the test case $\to$ save.
  2. CPJudge automatically increments `tests_version` and flags all previous submissions as **Stale**.
  3. Go to the Assignment Gradebook and click **Rejudge All**. The judge worker will re-evaluate every student's code against the updated test case and recompute scores automatically!

---

## 8. Post-Lab Workflow: Gradebook Export & Hot Backups

### Exporting Gradebook to CSV

Once the lab deadline has passed:
1. In the teacher navbar, click **Classes** $\to$ click **Gradebook** for your class section.
2. The **Class Gradebook Matrix** shows:
   - Student Roll Number, Name, Username.
   - Scores earned for each assignment (with sum across all problems in multi-problem assignments).
   - Total score earned vs. Total maximum possible score.
   - Overall percentage.
3. Click **Export CSV** in the top right corner.
4. An RFC-compliant `.csv` file will download instantly (e.g. `gradebook_CS101-FA24_20261102_0005.csv`), ready to open in Microsoft Excel, Google Sheets, or university grading portals.

---

### Taking an Offline Database Hot Backup

To protect student submission records and grade history after every lab session:

Run the backup utility inside the running container (or on the host):
```powershell
docker exec labjudge-web-1 python -m cpjudge.utils.backup --backup
```

Output:
```text
[SUCCESS] Database backup created at: /app/instance/backups/cpjudge_backup_20261102_000512.db
Size: 184,320 bytes
```

To list all existing backups with file sizes and PKT timestamps:
```powershell
docker exec labjudge-web-1 python -m cpjudge.utils.backup --list
```

> [!TIP]
> The hot backup utility uses the official SQLite Online Backup API (`sqlite3.Connection.backup()`). It takes transactionally consistent snapshots safely without stopping the web server or interrupting student submissions.

### Restoring from Backup
If you ever need to restore database state from a previous backup file:
```powershell
docker exec labjudge-web-1 python -m cpjudge.utils.backup --restore /app/instance/backups/cpjudge_backup_20261102_000512.db
```

---

## 9. Troubleshooting & Frequently Asked Questions

### Q1: Student PCs receive "This site can't be reached" (ERR_CONNECTION_TIMED_OUT)
1. **Check Server Firewall:** 
   Verify Inbound Port 5050 is allowed in Windows Defender Firewall (run the PowerShell command in [Step 4.2](#step-42-open-inbound-port-in-windows-firewall)).
2. **Verify Correct IP:**
   Double check the server IP by running `ipconfig` on the host machine. Ensure students are typing `http://<SERVER_IP>:5050` (not `https`).
3. **Check Network Connectivity:**
   From a student PC, open Command Prompt and test connectivity:
   ```cmd
   ping 192.168.1.100
   ```
   If ping fails, the student PC is on a different VLAN, subnet, or Wi-Fi network with **AP Isolation** enabled. Ensure all PCs are connected to the same lab switch or router.

---

### Q2: "Bind for 0.0.0.0:5050 failed: port is already allocated"
Another application on the server PC is using port 5050.
- Change the host port in `docker-compose.yml` or set the `PORT` environment variable:
  ```powershell
  $env:PORT="8080"
  docker compose up -d
  ```
  Students would then connect to `http://192.168.1.100:8080`.

---

### Q3: A student forgot their password
1. Log in as **Teacher**.
2. Click **Classes** $\to$ click **Manage Students** for the class.
3. Find the student in the roster and click **Reset Password**.
4. The password resets to `Student@123`, and the student will be required to choose a new password upon their next login.

---

### Q4: The server computer was restarted
Docker containers are configured with `restart: unless-stopped`. 
Once Docker Desktop starts after a reboot, the containers will resume automatically.
To manually verify or restart:
```powershell
docker compose up -d
```

---

### Q5: Submissions are stuck in "Queued" status
1. Check that the judge worker container is running:
   ```powershell
   docker compose ps
   ```
2. If `labjudge-worker-1` is stopped or exited, inspect worker logs:
   ```powershell
   docker compose logs worker
   ```
3. Restart the worker:
   ```powershell
   docker compose restart worker
   ```
   *(The worker requeues expired judging claims after five minutes; active jobs renew their leases. Recovery runs on startup and periodically while the worker is running.)*

---

### Quick Reference Card for the Lab Whiteboard

Write this on the classroom / lab whiteboard before the lab begins:

```text
======================================================
           CPJudge Programming Lab Portal
======================================================
1. Open Chrome or Edge.
2. Navigate to:  http://192.168.1.100:5050
3. Sign In:
     - Username:  Your Roll Number (e.g., BCSF24M001)
     - Password:  Student@123  (Change on first login)
4. Select active assignment and submit your solutions!
======================================================
```
