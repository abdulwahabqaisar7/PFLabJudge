# CPJudge

CPJudge is a web-based programming judge for classroom and lab use. It supports C, C++, and Python submissions, with a separate worker that compiles and runs submissions in restricted Docker containers.

## Requirements

- Git, or a downloaded copy of this repository.
- Docker Desktop on Windows, configured to use Linux containers; or Docker Engine and the Docker Compose plugin on Linux.
- Internet access for the first image build to download the base image and packages.

The host does not need a separate Python installation or compiler for the Docker deployment.

## 1. Get the code

Clone the repository and change into its directory:

```sh
git clone https://github.com/<owner>/<repository>.git
cd <repository>
```

Replace the URL with the repository's clone URL. Run the following commands from the directory containing `docker-compose.yml`. Start Docker Desktop or Docker Engine and confirm Docker is available:

```sh
docker --version
docker compose version
```

## 2. Configure the application

Create a `.env` file beside `docker-compose.yml` with a private random `SECRET_KEY`. Do not commit or share this file.

**Windows PowerShell** (creates `.env` only if it does not already exist):

```powershell
if (-not (Test-Path .env)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $secret = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    $rng.Dispose()
    "SECRET_KEY=$secret" | Set-Content -Encoding ascii .env
}
```

**Linux/macOS** (also preserves an existing `.env`):

```sh
if [ ! -f .env ]; then
  printf 'SECRET_KEY=%s\n' "$(openssl rand -hex 32)" > .env
  chmod 600 .env
fi
```

SQLite is used by default and needs no additional configuration. Optionally add `PORT=8080` to `.env` to publish the website on a different host port; the default is `5050`.

## 3. Build and start

From the repository root, run:

```sh
docker compose up --build -d
docker compose ps
```

The `web` and `worker` services should be running. Compose builds the application image, which also supplies Python and the C/C++ compilers used by the restricted execution containers.

## 4. Initialize the database and demo content

Seed the database after the services have started:

```sh
docker compose exec web python seed.py
```

The seeder creates missing tables and demo records. It is safe to run again; it does not reset existing records.

Open [http://localhost:5050](http://localhost:5050) (or the port configured in `.env`) and sign in:

| Role | Username | Password |
|---|---|---|
| Teacher | Set in `seed.py` | `Teacher@123` |
| Student | `bcsf20m001` | `Student@123` |
| Student | `bcsf20m002` | `Student@123` |
| Student | `bcsf20m003` | `Student@123` |

The teacher username is configured in `seed.py`; use that username to sign in. These are public demo credentials. Change the teacher password and replace or remove demo accounts before using the service with real users or exposing it to a lab network.

## 5. Try a Python submission

The demo problem, "Sum of Two Numbers," provides both integers on the same line (for example, `5 7`). A compatible Python solution is:

```python
a, b = map(int, input().split())
print(a + b)
```

The worker evaluates submissions in isolated containers. Check its output with:

```sh
docker compose logs -f worker
```

If submissions remain queued, make sure the worker is running with `docker compose ps` and inspect its logs. Do not configure an unsandboxed execution backend.

## Common commands

```sh
# Follow application and worker logs
docker compose logs -f web worker

# Restart services
docker compose restart

# Stop services (keeps the database)
docker compose down

# Run the automated tests
docker compose run --rm test
```

The test service is behind the `test` Compose profile and is not started by the normal `docker compose up`.

The default SQLite database is stored under `instance/` on the host and persists across container restarts and `docker compose down`. Back up this directory before removing or replacing the project folder. To back up the database while the app is running:

```sh
docker compose exec web python -m cpjudge.utils.backup --backup
```

## LAN deployment and security

To let students access the app, use the server's LAN IP and allow the configured host port through its firewall. See [deployment_guide.md](./deployment_guide.md) for network and lab setup guidance. Do not expose CPJudge directly to the public internet.

The worker requires Docker Engine access to create restricted execution containers. The Docker socket is mounted only into the trusted worker; access to it is highly privileged. Keep the host and worker under administrator control.

## Troubleshooting

- **`SECRET_KEY` is not set:** Create `.env` beside `docker-compose.yml` and run Compose from the repository root.
- **The site does not open:** Check `docker compose ps`, the configured host port, and `docker compose logs web`.
- **The worker is not running or submissions stay queued:** Check `docker compose logs worker`. The worker needs the Docker daemon and the `cpjudge:local` image.
- **Docker reports a socket, daemon, or image error:** Start Docker Desktop with Linux containers (Windows) or start Docker Engine (Linux), then run `docker compose up --build -d`.
- **The first build fails while downloading packages:** Check the host's internet connection and retry `docker compose up --build -d`.
