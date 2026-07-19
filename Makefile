# Agentic Graph RAG — common tasks.
# Run `make help` to see everything.

PROFILE ?= production
COMPOSE := docker compose

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev extras (editable)
	pip install -e ".[dev,extras]"

setup: ## Pick a config profile: make setup PROFILE=production (or local / api)
	@test -f .env || cp .env.example .env
	@grep -v '^GRAPHRAG_PROFILE=' .env > .env.tmp && \
		echo "GRAPHRAG_PROFILE=$(PROFILE)" >> .env.tmp && mv .env.tmp .env
	@echo "Profile set to '$(PROFILE)' in .env. Edit .env for secrets, then: make up"

migrate: ## Apply database migrations (needs GRAPHRAG_DATABASE_URL)
	alembic upgrade head

serve: ## Run the API bare (no Docker) with uvicorn
	GRAPHRAG_PROFILE=$(PROFILE) uvicorn graphrag.api.app:create_app --factory --reload --port 8000

worker: ## Run the optional ingest worker (needs Redis; not for the duckdb provider)
	GRAPHRAG_PROFILE=$(PROFILE) arq graphrag.worker.WorkerSettings

# FILE, not PATH: overriding PATH would clobber the shell's executable search
# path and the recipe couldn't find `graphrag` at all.
ingest: ## Ingest a file or folder: make ingest FILE=./data/mydoc.pdf
	GRAPHRAG_PROFILE=$(PROFILE) graphrag ingest $(FILE)

admin: ## Grant an account the admin role: make admin EMAIL=you@example.com
	$(COMPOSE) exec api graphrag promote-admin $(EMAIL)

up: ## One command: bring up the whole stack, then apply migrations
	$(COMPOSE) up -d --build
	$(COMPOSE) exec -T api alembic upgrade head
	@echo "API:      http://localhost:8000  (docs: http://localhost:8000/docs)"
	@echo "Frontend: http://localhost:5173"
	@echo "Neo4j:    http://localhost:7474"

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail all container logs
	$(COMPOSE) logs -f

test: ## Run unit tests (fast, no services)
	pytest -m "not integration"

# The integration fixtures create and drop the schema, so they refuse any
# database whose name doesn't look disposable.
test-integration: ## Run integration tests (needs Postgres; set GRAPHRAG_TEST_DATABASE_URL)
	pytest -m integration

test-all: ## Run every test (needs Postgres + Neo4j + Redis up)
	pytest

eval: ## Score retrieval + answers against the golden set (needs the stack up)
	GRAPHRAG_PROFILE=$(PROFILE) python scripts/eval.py

frontend: ## Build the web UI (type-checks it too)
	cd frontend && npm ci && npm run build

lint: ## Lint & type-check
	ruff check src tests migrations
	mypy src

fmt: ## Auto-format & fix
	ruff check --fix src tests migrations
	ruff format src tests migrations

.PHONY: help install setup migrate serve worker ingest admin up down logs \
        test test-integration test-all eval frontend lint fmt
