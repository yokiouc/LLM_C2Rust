# Environment Verification

Date: 2026-03-13
OS: Windows

## 1. Docker Desktop

Docker Engine default endpoint (Windows): `//./pipe/docker_engine` (via Docker Desktop context).

### docker version

```text
Client:
 Version:           29.2.1
 API version:       1.53
 Go version:        go1.25.6
 Git commit:        a5c7197
 Built:             Mon Feb  2 17:20:16 2026
 OS/Arch:           windows/amd64
 Context:           desktop-linux

Server: Docker Desktop 4.64.0 (221278)
 Engine:
  Version:          29.2.1
  API version:      1.53 (minimum version 1.44)
  Go version:        go1.25.6
  Git commit:        6bc6209
  Built:            Mon Feb  2 17:17:24 2026
  OS/Arch:          linux/amd64
  Experimental:     false
 containerd:
  Version:          v2.2.1
 runc:
  Version:          1.3.4
 docker-init:
  Version:          0.19.0
```

## 2. PostgreSQL container

Command used:

```bash
docker run -d --name proj_postgres -e POSTGRES_USER=root -e POSTGRES_PASSWORD=root -p 5432:5432 pgvector/pgvector:pg15
```

Notes:
- Deviates from `postgres:15` to `pgvector/pgvector:pg15` so that `CREATE EXTENSION vector;` in `db/schema.sql` works.

### docker logs proj_postgres --tail 50 (excerpt)

```text
Data page checksums are disabled.

fixing permissions on existing directory /var/lib/postgresql/data ... ok        
creating subdirectories ... ok
selecting dynamic shared memory implementation ... posix
selecting default max_connections ... 100
selecting default shared_buffers ... 128MB
selecting default time zone ... Etc/UTC
creating configuration files ... ok
running bootstrap script ... ok
performing post-bootstrap initialization ... ok
syncing data to disk ... ok


Success. You can now start the database server using:

    pg_ctl -D /var/lib/postgresql/data -l logfile start

initdb: warning: enabling "trust" authentication for local connections
initdb: hint: You can change this by editing pg_hba.conf or using the option -A, or --auth-local and --auth-host, the next time you run initdb.
waiting for server to start....2026-03-13 11:51:11.172 UTC [48] LOG:  starting PostgreSQL 15.17 (Debian 15.17-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
2026-03-13 11:51:11.174 UTC [48] LOG:  listening on Unix socket "/var/run/postgresql/.s.PGSQL.5432"
2026-03-13 11:51:11.181 UTC [51] LOG:  database system was shut down at 2026-03-13 11:51:10 UTC
2026-03-13 11:51:11.188 UTC [48] LOG:  database system is ready to accept connections
 done
server started
CREATE DATABASE


/usr/local/bin/docker-entrypoint.sh: ignoring /docker-entrypoint-initdb.d/*     

waiting for server to shut down...2026-03-13 11:51:11.373 UTC [48] LOG:  received fast shutdown request
.2026-03-13 11:51:11.375 UTC [48] LOG:  aborting any active transactions        
2026-03-13 11:51:11.378 UTC [48] LOG:  background worker "logical replication launcher" (PID 54) exited with exit code 1
2026-03-13 11:51:11.378 UTC [49] LOG:  shutting down
2026-03-13 11:51:11.379 UTC [49] LOG:  checkpoint starting: shutdown immediate  
2026-03-13 11:51:11.454 UTC [49] LOG:  checkpoint complete: wrote 918 buffers (5.6%); 0 WAL file(s) added, 0 removed, 0 recycled; write=0.028 s, sync=0.042 s, total=0.076 s; sync files=301, longest=0.003 s, average=0.001 s; distance=4222 kB, estimate=4222 kB
2026-03-13 11:51:11.468 UTC [48] LOG:  database system is shut down
 done
server stopped

PostgreSQL init process complete; ready for start up.

2026-03-13 11:51:11.506 UTC [1] LOG:  starting PostgreSQL 15.17 (Debian 15.17-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
2026-03-13 11:51:11.506 UTC [1] LOG:  listening on IPv4 address "0.0.0.0", port 5432
2026-03-13 11:51:11.506 UTC [1] LOG:  listening on IPv6 address "::", port 5432 
2026-03-13 11:51:11.510 UTC [1] LOG:  listening on Unix socket "/var/run/postgresql/.s.PGSQL.5432"
2026-03-13 11:51:11.516 UTC [64] LOG:  database system was shut down at 2026-03-13 11:51:11 UTC
2026-03-13 11:51:11.524 UTC [1] LOG:  database system is ready to accept connections
```

## 3. Business container (API)

### docker compose up --build -d

Result: `c2rust-api-1` started and port 8000 mapped.

### docker compose ps

```text
time="2026-03-13T19:59:40+08:00" level=warning msg="project has been loaded without an explicit name from a symlink. Using name \"c2rust\""
NAME           IMAGE        COMMAND                   SERVICE   CREATED         STATUS         PORTS
c2rust-api-1   c2rust-api   "uvicorn main:app --…"   api       2 minutes ago    Up 2 minutes   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
```

## 4. DB schema initialization

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
```

Result: schema executed successfully (idempotent).

## 5. make test (inside business container)

```bash
docker exec c2rust-api-1 bash -lc "cd /app && make test"
```

Output:

```text
python -m py_compile main.py db.py crud.py cli.py
python -m pytest -q
.......                                                                  [100%]
7 passed in 1.67s
```

## 6. /health integration

```bash
curl.exe -s http://localhost:8000/health
```

Response:

```json
{"ok":true,"db":"ok"}
```

## 7. docker ps (containers)

```text
NAMES           IMAGE                    STATUS          PORTS
c2rust-api-1    c2rust-api               Up 56 seconds   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
proj_postgres   pgvector/pgvector:pg15   Up 6 minutes    0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp
```
