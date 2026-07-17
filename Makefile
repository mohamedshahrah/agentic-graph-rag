# Agentic Graph RAG — common tasks.
# Run `make help` to see everything.

PROFILE ?= api
COMPOSE := docker compose

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev extras (editable)
	pip install -e ".[dev,extras]"

setup: ## Pick a config profile: make setup PROFILE=local (or api)
	@test -f .env || cp .env.example .env
	@grep -v '^GRAPHRAG_PROFILE=' .env > .env.tmp && \
		echo "GRAPHRAG_PROFILE=$(PROFILE)" >> .env.tmp && mv .env.tmp .env
	@echo "Profile set to '$(PROFILE)' in .env. Edit .env for secrets, then: make up"

serve: ## Run the API bare (no Docker) with uvicorn
	GRAPHRAG_PROFILE=$(PROFILE) uvicorn graphrag.api.app:create_app --factory --reload --port 8000

worker: ## Run the ingest queue worker bare (needs Redis)
	GRAPHRAG_PROFILE=$(PROFILE) arq graphrag.worker.WorkerSettings

# FILE, not PATH: overriding PATH would clobber the shell's executable search
# path and the recipe couldn't find `graphrag` at all.
ingest: ## Ingest a file or folder: make ingest FILE=./data/mydoc.pdf
	GRAPHRAG_PROFILE=$(PROFILE) graphrag ingest $(FILE)

up: ## One command: bring up the whole stack (Neo4j + Redis + API + frontend)
	$(COMPOSE) up -d --build
	@echo "API:      http://localhost:8000  (docs: http://localhost:8000/docs)"
	@echo "Frontend: http://localhost:5173"
	@echo "Neo4j:    http://localhost:7474"

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail all container logs
	$(COMPOSE) logs -f

test: ## Run unit tests
	pytest -m "not integration"

eval: ## Score retrieval + answers against the golden set (needs the stack up)
	GRAPHRAG_PROFILE=$(PROFILE) python scripts/eval.py

test-all: ## Run all tests (needs Neo4j + Redis up)
	pytest

lint: ## Lint & type-check
	ruff check src tests
	mypy src

fmt: ## Auto-format & fix
	ruff check --fix src tests
	ruff format src tests

.PHONY: help install setup serve worker ingest up down logs test test-all eval lint fmt
