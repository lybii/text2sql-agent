# Local development helpers. Docker users only need: cp .env.example .env && docker compose up --build
-include .env
export

PG_OWNER_URL = postgresql+asyncpg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@127.0.0.1:$(POSTGRES_PORT)/$(POSTGRES_DB)?ssl=disable
BACKEND = cd backend &&

.PHONY: up down db-up migrate seed api web test lint typecheck check eval eval-openai chaos observability

up:            ## full stack in Docker
	docker compose up --build -d

down:
	docker compose down

db-up:         ## PostgreSQL only (for local dev)
	docker compose up -d db

migrate:
	$(BACKEND) MIGRATION_DATABASE_URL="$(PG_OWNER_URL)" uv run alembic upgrade head

seed:
	$(BACKEND) MIGRATION_DATABASE_URL="$(PG_OWNER_URL)" uv run python -m scripts.seed

api:           ## backend with reload on :8000
	$(BACKEND) uv run uvicorn app.main:app --reload --port 8000

web:           ## frontend dev server on :5173
	cd frontend && npm run dev

test:
	$(BACKEND) uv run pytest -q
	cd frontend && npm test

lint:
	$(BACKEND) uv run ruff check app tests eval scripts migrations && uv run ruff format --check app tests eval scripts migrations

typecheck:
	$(BACKEND) uv run mypy app eval
	cd frontend && npx tsc -b

check: lint typecheck test

eval:          ## golden + red-team with the configured provider (demo by default)
	$(BACKEND) uv run python -m eval.run --suite all

eval-openai:   ## same suite against the real model (needs OPENAI_API_KEY)
	$(BACKEND) LLM_PROVIDER=openai uv run python -m eval.run --suite all

chaos:         ## primary provider fails 100% → circuit opens → fallback still answers
	$(BACKEND) LLM_CHAOS_FAILURE_RATE=1.0 uv run python -m eval.run --suite golden --out eval/reports/chaos.json

observability: ## Prometheus :9090 + Grafana :3000
	docker compose --profile observability up -d
