# Database configuration

Docker Compose uses PostgreSQL for the packaged backend. Create the two local
environment files before starting it.

```bash
cp db/.env.example db/.env
cp db/postgres.env.example db/postgres.env
make db-up
```

Both local files are excluded from Git and Docker build contexts. `db/.env`
contains only the KRX key and is injected into the backend. `db/postgres.env`
contains PostgreSQL settings and is injected into PostgreSQL and the backend.

PostgreSQL data is stored in the Docker named volume `postgres-data`. Django
owns the application schema, so model migrations remain under
`backend/exchange/migrations/`; `db/migrations/` is not a second schema source.
