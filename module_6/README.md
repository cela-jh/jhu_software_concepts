# Module 6: Deploy Anywhere

GradCafe admissions analytics as a containerized microservice stack.

## Stack

| Service  | Description                              | Port  |
|----------|------------------------------------------|-------|
| `web`    | Flask analysis app                       | 8080  |
| `worker` | RabbitMQ consumer, data ingestion        |       |
| `db`     | PostgreSQL 16                            | 5432  |
| `rabbitmq` | RabbitMQ 3.13 with management UI      | 15672 |

## Prerequisites

- Docker Engine (or Docker Desktop) with the Compose plugin
- A `.env` file at `module_6/` (copy `.env.example` and fill in values)

## Run

```bash
cd module_6
docker compose up --build
```

- Flask app: http://localhost:8080
- RabbitMQ management: http://localhost:15672 (guest/guest, dev only)

## Environment Variables

| Variable        | Used by     | Description                          |
|-----------------|-------------|--------------------------------------|
| `POSTGRES_USER` | db          | PostgreSQL superuser name            |
| `POSTGRES_PASSWORD` | db      | PostgreSQL superuser password        |
| `POSTGRES_DB`   | db          | Database name                        |
| `DATABASE_URL`  | web, worker | Full PostgreSQL connection string    |
| `RABBITMQ_URL`  | web, worker | Full AMQP connection string          |
| `FLASK_ENV`     | web         | `development` or `production`        |
| `FLASK_SECRET`  | web         | Flask secret key                     |
| `SEED_JSON`     | worker      | Path to applicant data JSON in container |
| `TARGET_TABLE`  | worker      | Target table name (`applicants`)     |
| `ID_KEY`        | worker      | Primary-key column (`p_id`)          |

## Docker Hub

Images are published at:

- `<dockerhub-user>/module_6_web:v1`
- `<dockerhub-user>/module_6_worker:v1`

Pull and run:

```bash
docker pull <dockerhub-user>/module_6_web:v1
docker pull <dockerhub-user>/module_6_worker:v1
docker compose up
```

## Architecture Notes

### Why `database/` lives under `src/web/` and not `src/db/`

Docker's build context is the directory passed to `build:` in docker-compose (e.g., `./web`). The daemon can only see files inside that directory, so a `COPY ../db/database .` instruction would fail. The alternatives are widening the build context (sends every file under `src/` to the daemon, including large data files) or multi-stage builds (an earlier `FROM` stage holds shared code and a later stage copies selectively from it), both of which add complexity the project does not need. Instead, each service owns its own copy of the code it uses: the web service has `src/web/database/` for read queries and ORM access, and the worker has `src/worker/etl/` for write operations and analytics. The duplication is intentional and keeps each service self-contained within its build context.

## Local Development (without Docker)

```bash
cd module_6
pip install -e ".[dev]"
# Set DB_* or DATABASE_URL, then:
python src/web/run.py
```
