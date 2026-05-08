.PHONY: dev prod down test migrate seed lint typecheck shell-db shell-backend generate-client logs clean help

# ─── Local Development ────────────────────────────────────────────────────────

dev:
	docker compose up --build

dev-detach:
	docker compose up --build -d

prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d

down:
	docker compose down

down-volumes:
	docker compose down -v

# ─── Testing ──────────────────────────────────────────────────────────────────

test:
	docker compose run --rm backend pytest tests/ -v --tb=short

test-backend:
	docker compose run --rm backend pytest tests/backend/ -v --tb=short

test-e2e:
	docker compose run --rm backend pytest tests/e2e/ -v --tb=short

test-coverage:
	docker compose run --rm backend pytest tests/ -v --tb=short --cov=app --cov-report=html

# ─── Database ─────────────────────────────────────────────────────────────────

migrate:
	docker compose run --rm backend alembic upgrade head

migrate-down:
	docker compose run --rm backend alembic downgrade -1

migrate-history:
	docker compose run --rm backend alembic history --verbose

migrate-create:
	@read -p "Migration message: " msg; \
	docker compose run --rm backend alembic revision --autogenerate -m "$$msg"

seed:
	docker compose run --rm backend python -m app.tasks.seed_data

# ─── Data Ingestion (Phase 2) ─────────────────────────────────────────────────

ingest-osm:
	@read -p "Place name [Gujarat, India]: " place; \
	place=$${place:-"Gujarat, India"}; \
	docker compose run --rm backend python -m app.tasks.ingest_osm \
		--place "$$place" --tags roads,railways,hospitals,schools,forests,water

ingest-osm-all:
	docker compose run --rm backend python -m app.tasks.ingest_osm \
		--place "India" --tags all

ingest-gadm:
	docker compose run --rm backend python -m app.tasks.ingest_gadm \
		--level 1 --download
	docker compose run --rm backend python -m app.tasks.ingest_gadm \
		--level 2 --download

ingest-census:
	docker compose run --rm backend python -m app.tasks.ingest_census --download

ingest-all:
	$(MAKE) ingest-gadm
	$(MAKE) ingest-census
	@read -p "Place name for OSM [Gujarat, India]: " place; \
	place=$${place:-"Gujarat, India"}; \
	docker compose run --rm backend python -m app.tasks.ingest_osm \
		--place "$$place" --tags all

# ─── Code Quality ─────────────────────────────────────────────────────────────

lint:
	docker compose run --rm backend ruff check app/ tests/
	docker compose run --rm frontend npx eslint src/ --ext .ts,.tsx

lint-fix:
	docker compose run --rm backend ruff check app/ tests/ --fix
	docker compose run --rm frontend npx eslint src/ --ext .ts,.tsx --fix

typecheck:
	docker compose run --rm backend mypy app/ --strict
	docker compose run --rm frontend npx tsc --noEmit

format:
	docker compose run --rm backend ruff format app/ tests/

# ─── Code Generation ──────────────────────────────────────────────────────────

generate-client:
	curl -s http://localhost:8000/openapi.json | \
	docker compose run --rm frontend npx openapi-typescript-codegen \
		--input /dev/stdin \
		--output src/lib/api-client \
		--client axios

# ─── Shell Access ─────────────────────────────────────────────────────────────

shell-db:
	docker compose exec db psql -U gsip gsip

shell-backend:
	docker compose exec backend bash

shell-redis:
	docker compose exec redis redis-cli

# ─── Logs ─────────────────────────────────────────────────────────────────────

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-db:
	docker compose logs -f db

# ─── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/.next frontend/node_modules/.cache

help:
	@echo "GSIP — GatiShakti Intelligence Platform"
	@echo ""
	@echo "Development:"
	@echo "  make dev            Start all services with hot reload"
	@echo "  make dev-detach     Start all services in background"
	@echo "  make down           Stop all services"
	@echo "  make down-volumes   Stop all services and remove volumes"
	@echo ""
	@echo "Database:"
	@echo "  make migrate        Run all pending Alembic migrations"
	@echo "  make migrate-down   Roll back last migration"
	@echo "  make migrate-create Create a new migration (prompts for message)"
	@echo "  make seed           Seed database with sample data"
	@echo "  make shell-db       Open psql shell"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run all tests"
	@echo "  make test-backend   Run backend unit tests only"
	@echo "  make test-e2e       Run Playwright E2E tests"
	@echo "  make test-coverage  Run tests with HTML coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint           Run ruff + eslint"
	@echo "  make lint-fix       Auto-fix lint errors"
	@echo "  make typecheck      Run mypy + tsc"
	@echo "  make format         Run ruff formatter"
	@echo ""
	@echo "Other:"
	@echo "  make generate-client  Regenerate TypeScript API client from OpenAPI"
	@echo "  make logs           Tail all service logs"
	@echo "  make clean          Remove all containers, volumes, caches"
	@echo ""
	@echo "Data Ingestion (Phase 2):"
	@echo "  make ingest-osm     Load OSM data for a place (prompts for place name)"
	@echo "  make ingest-osm-all Load all OSM datasets for entire India"
	@echo "  make ingest-gadm    Download and load GADM state + district boundaries"
	@echo "  make ingest-census  Load Census 2011 population data"
	@echo "  make ingest-all     Run all ingestion in order (gadm → census → osm)"
