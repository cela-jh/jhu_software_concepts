# Module 6: Deploy Anywhere

Cameron Ela, cela1@jh.edu
GradCafe admissions analytics as a containerized microservice stack.

## Stack

| Service    | Description                              | Port  |
|------------|------------------------------------------|-------|
| `web`      | Flask analysis app                       | 8080  |
| `worker`   | RabbitMQ consumer, data ingestion        |       |
| `loader`   | One-shot seed loader (exits after run)   |       |
| `db`       | PostgreSQL 16                            | 5432  |
| `rabbitmq` | RabbitMQ 3.13 with management UI         | 15672 |

## Prerequisites

- **Docker Engine >= 24** or **Docker Desktop** with the Compose v2 plugin (`docker compose`, not `docker-compose`). Install at https://docs.docker.com/get-docker/.
- A `.env` file at `module_6/` — copy `.env.example` and fill in real values

## Run

```bash
cd module_6
docker compose up --build
```

- Flask app: http://localhost:8080/analysis
- RabbitMQ management: http://localhost:15672 (guest/guest, dev only)

## Usage

The analysis page has two action buttons:

| Button | Task published | What the worker does |
|---|---|---|
| **Pull Data** | `scrape_new_data` | Reads `applicant_data.json`, inserts records whose `p_id` exceeds the stored watermark, advances the watermark |
| **Update Analysis** | `recompute_analytics` | Re-runs all analytics queries against the current database contents |

Both buttons return HTTP 202 immediately. The worker processes the task asynchronously; reload the page after a moment to see updated results.

## How It Works

On `docker compose up --build`:

1. **`db`** starts and runs `src/db/init.sql`, creating the `applicants` and `ingestion_watermarks` tables.
2. **`loader`** runs `load_data.py` once, seeding PostgreSQL with `applicant_data.json` via upsert, then exits.
3. **`web`** starts Flask on port 8080. The analysis page reads results directly from PostgreSQL on each page load.
4. **`worker`** starts `consumer.py`, connects to RabbitMQ, and waits for messages.
5. **`rabbitmq`** brokers messages between `web` and `worker`.

When a button is clicked, `web` publishes a JSON task message to a durable RabbitMQ queue and returns HTTP 202 without waiting. `worker` receives the message, opens a database transaction, runs the appropriate handler, commits, and acks. If anything fails, the transaction is rolled back and the message is nacked (not requeued).

## Testing

Install the package in editable mode with dev extras, then run pytest from
`module_6/`. The suite requires a PostgreSQL instance named `cam_db_test`.

```bash
cd module_6
pip install -e ".[dev]"
# DATABASE_URL must point at cam_db_test, e.g.:
export DATABASE_URL=postgresql://user:password@localhost:5432/cam_db_test
pytest tests/
```

`pytest.ini` sets `--cov=src/web --cov=src/worker --cov-fail-under=100`, so
all coverage gaps cause the run to fail.

## Security

### SQL injection defenses

All SQL in this project uses parameterized queries — values are always passed
as bound parameters, never formatted into query strings:

- **psycopg** (worker `etl/`) uses `cursor.execute(sql, params)` with `%s` or
  `%(name)s` placeholders throughout `incremental_scraper.py` and `query_data.py`.
- **SQLAlchemy ORM** (web `database/`) binds values through the ORM layer;
  no raw string interpolation is used in any query.
- **LIKE/ILIKE patterns** are additionally escaped with `escape_like()` in
  `query_data.py` before being passed as bound parameters, preventing `%` or
  `_` wildcards from matching unintended rows.

### LIMIT enforcement

Every SELECT that could return many rows is capped with an enforced LIMIT:

- `query_data.py` defines `QUERY_LIMIT = 50` and `clamp_limit()` to keep the
  value in `[MIN_LIMIT, MAX_LIMIT]`. Every query in `QUESTION_QUERY` is
  composed through `_limited_query()`, which appends `LIMIT %(limit)s` as a
  bound parameter.
- The web ORM layer applies equivalent limits through SQLAlchemy's `.limit()`
  on every query in `orm_queries.py`.

### Snyk dependency scanning

The CI workflow (`module_6_ci.yml`) runs Snyk against both service
`requirements.txt` files after installing packages. This catches known
CVEs in Flask, psycopg, pika, and their transitive dependencies before
they reach a container image.

### Error handling

- Database connection errors (`OperationalError`, `DatabaseUnavailableError`)
  are caught at the route level and returned as generic 503 messages. No raw
  libpq error text (host, port, user) is ever sent to the client.
- `DatabaseConfigError` messages describe only which environment variable is
  missing, never its value.
- Flask runs with `debug=False`; the Werkzeug interactive debugger is never
  exposed.

## CI/CD

GitHub Actions (`module_6_ci.yml`) runs on every push or PR that touches
`module_6/`:

| Job        | What it checks                                          |
|------------|---------------------------------------------------------|
| `pylint`   | 10/10 lint score across `src/web/` and `src/worker/`   |
| `pytest`   | 100% coverage gate against a live Postgres service      |
| `snyk`     | Known CVEs in both service dependency sets              |
| `pydeps`   | Dependency graph renders without errors                 |

## Environment Variables

| Variable           | Used by         | Description                                    |
|--------------------|-----------------|------------------------------------------------|
| `POSTGRES_USER`    | db              | PostgreSQL superuser name                      |
| `POSTGRES_PASSWORD`| db              | PostgreSQL superuser password                  |
| `POSTGRES_DB`      | db              | Database name                                  |
| `RABBITMQ_URL`     | web, worker     | Full AMQP connection string                    |
| `FLASK_ENV`        | web             | `development` or `production`                  |
| `FLASK_SECRET`     | web             | Flask secret key                               |
| `SEED_JSON`        | worker          | Path to applicant data JSON in container       |
| `TARGET_TABLE`     | worker          | Target table name (`applicants`)               |
| `ID_KEY`           | worker          | Primary-key column (`p_id`)                    |

`DATABASE_URL` is not stored in `.env`; it is constructed by `docker-compose.yml`
from `POSTGRES_*` vars so credentials are defined in exactly one place.

## Docker Hub

Images are published at:

- https://hub.docker.com/r/celajh/module_6_web
- https://hub.docker.com/r/celajh/module_6_worker

Pull and run:

```bash
docker pull celajh/module_6_web:v1
docker pull celajh/module_6_worker:v1
docker compose up
```

## Architecture Notes

### Why `database/` lives under `src/web/` and not `src/db/`

Docker's build context is the directory passed to `build:` in docker-compose.
The daemon can only see files inside that directory, so a `COPY ../db/database .`
instruction would fail. The alternatives — widening the build context or
multi-stage builds — add complexity the project does not need. Instead, each
service owns its own copy of the code it uses: the web service has
`src/web/database/` for read queries and ORM access, and the worker has
`src/worker/etl/` for write operations and analytics. The duplication is
intentional and keeps each service self-contained within its build context.

## Local Development (without Docker)

```bash
cd module_6
pip install -e ".[dev]"
# Set DATABASE_URL (or POSTGRES_* vars), then:
python src/web/run.py
```

## Citations

### CLAUDE

- Helped refactor code away from scraping
- Wrote new test cases
- Considered edge cases and helped develop error-catching methods
- Error-checked new functions in `load_data.py` and `publisher.py`, among other files
- Modified .env.example to fit this assignment's scope
- Created most of this README
