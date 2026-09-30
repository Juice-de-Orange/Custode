.DEFAULT_GOAL := help
COMPOSE := docker compose -f docker-compose.dev.yml

.PHONY: help dev down logs migrate seed-demo openapi lint lint-imports test format install web

help:
	@echo Custode make targets:
	@echo   make dev          - bring up dev stack (api worker scheduler postgres redis minio mailpit radicale)
	@echo   make down         - stop dev stack
	@echo   make logs         - follow dev stack logs
	@echo   make migrate      - alembic upgrade head (in api container, owner role)
	@echo   make seed-demo    - seed demo household (in api container)
	@echo   make openapi      - export schema + regenerate web client
	@echo   make lint         - ruff + mypy (backend), eslint + tsc (web)
	@echo   make lint-imports - import-linter (module boundaries)
	@echo   make test         - pytest (backend) + vitest (web)
	@echo   make format       - ruff format + fix (backend)
	@echo   make install      - uv sync (backend) + npm install (web)
	@echo   make web          - run web dev server

dev:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(COMPOSE) run --rm api alembic upgrade head

seed-demo:
	$(COMPOSE) run --rm api python -m app.scripts.seed_demo

openapi:
	uv --directory backend run python -m app.scripts.export_openapi
	npm --prefix web run openapi

lint:
	uv --directory backend run ruff check .
	uv --directory backend run ruff format --check .
	uv --directory backend run mypy
	npm --prefix web run lint
	npm --prefix web run typecheck

lint-imports:
	uv --directory backend run lint-imports

test:
	uv --directory backend run pytest
	npm --prefix web run test

format:
	uv --directory backend run ruff format .
	uv --directory backend run ruff check --fix .

install:
	uv --directory backend sync
	npm --prefix web install

web:
	npm --prefix web run dev
