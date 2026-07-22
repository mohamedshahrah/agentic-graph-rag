# llmlens — common tasks. `make help` lists everything.

PROFILE ?= default
COMPOSE := docker compose

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install server + SDK (editable) with dev extras
	pip install -e "./server[dev]" -e "./sdk[dev]"

serve: ## Run the API bare (needs ClickHouse/Postgres/Redis)
	LLMLENS_PROFILE=$(PROFILE) uvicorn llmlens_server.api.app:create_app --factory --reload --port 8000

worker: ## Run the ingest+alert worker bare
	LLMLENS_PROFILE=$(PROFILE) python -m llmlens_server.worker

up: ## One command: bring up the whole stack
	$(COMPOSE) up -d --build
	@echo "Dashboard: http://localhost:5173   API docs: http://localhost:8000/docs"
	@echo "ClickHouse: http://localhost:8123   Postgres: 5432"

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail logs
	$(COMPOSE) logs -f

generate: ## Send synthetic traffic to the running API
	python examples/generate_traffic.py

test: ## Run unit tests
	pytest -m "not integration"

test-e2e: ## Integration tests against a running stack (docker compose up -d first)
	pytest -m integration -q

lint: ## Lint + type-check
	ruff check server/src sdk/src tests
	mypy server/src

fmt: ## Auto-format
	ruff check --fix server/src sdk/src tests
	ruff format server/src sdk/src tests

.PHONY: help install serve worker up down logs generate test test-e2e lint fmt
