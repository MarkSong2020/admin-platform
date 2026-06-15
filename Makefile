# 集成测试排除约定（2026-06-14 收口）：`-m "not integration"` 不再放在 pyproject 全局
# addopts（曾导致点名跑集成测试被静默 deselect、假绿）。排除现显式收口在下列 target：
# test / coverage / check。裸 `pytest`（无参）默认**含**集成测试，跑前需 `make compose-up`
# + `make migrate`；只想跑集成用 `make test-integration`（`-m integration`）。
.PHONY: help init dev test test-integration coverage lint format format-files typecheck audit migrate migration new-module smoke-generator check check-openapi-contract check-layer-boundaries check-db schema-doc compose-up compose-up-cache compose-down docker-build

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

init:  ## Install all deps and sync env (uv)
	uv sync --all-extras --dev

dev:  ## Run FastAPI dev server (uses [tool.fastapi] entrypoint)
	uv run fastapi dev

test:  ## Run unit + API tests (excludes integration)
	uv run pytest -m "not integration"

test-integration:  ## Run integration tests (requires compose-up + migrate)
	uv run pytest -m integration

coverage:  ## Run unit + API tests with coverage report (fail under per pyproject.toml [tool.coverage.report] fail_under)
	uv run pytest -m "not integration" --cov --cov-report=term-missing

lint:  ## Lint with Ruff
	uv run ruff check .

format:  ## Format with Ruff
	uv run ruff format .

format-files:  ## Format specific files. Usage: make format-files files="src/a.py tests/b.py"
	@test -n "$(files)" || (echo "Error: files= is required" && exit 1)
	uv run ruff format $(files)

typecheck:  ## Type check with Pyright (Errata #2)
	uv run pyright

audit:  ## Dependency vulnerability scan (Errata #1: uvx, not 'uv pip audit'). Note: `.` scans project deps, not pip-audit's own venv.
	uvx pip-audit .

migrate:  ## Apply migrations (requires compose-up)
	uv run alembic upgrade head

migration:  ## Create new migration. Usage: make migration name=create_xxx
	uv run alembic revision --autogenerate -m "$(name)"

new-module:  ## Generate a domain module. Usage: make new-module name=order [with-model=1] [plural=xxx] [dry-run=1] [force=1]
	@test -n "$(name)" || (echo "Error: name= is required (e.g. make new-module name=order)" && exit 1)
	uv run python scripts/new_module.py --name $(name) \
		$(if $(with-model),--with-model) \
		$(if $(plural),--plural $(plural)) \
		$(if $(dry-run),--dry-run) \
		$(if $(force),--force)

smoke-generator:  ## E2E smoke: run new-module + make check on smoke_probe module, then clean up
	@bash scripts/smoke_generator.sh

check:  ## Full quality gate excluding integration tests (mirror of CI fast lane)
	uv run ruff format --check .
	uv run ruff check .
	uv run pyright
	uv run pytest -m "not integration"
	uv run lint-imports
	uv run python scripts/dump_schema.py --check

check-openapi-contract:  ## OpenAPI 契约规则表（pytest 子集）
	uv run pytest tests/unit/test_openapi_contract.py

check-layer-boundaries:  ## 分层边界静态契约（import-linter，C1–C7）
	uv run lint-imports

check-db:  ## Alembic migration drift detection (Errata #3, requires compose-up)
	uv run alembic check

schema-doc:  ## Regenerate docs/architecture/DATA_MODEL.md from ORM models (no DB needed)
	uv run python scripts/dump_schema.py

compose-up:  ## Bring up local Postgres and wait until healthy (Errata #5: redis is opt-in)
	docker compose up -d --wait db

compose-up-cache:  ## Bring up Postgres + Redis (cache profile), wait until healthy
	docker compose --profile cache up -d --wait

compose-down:  ## Tear down compose stack (incl. opt-in profiles like cache)
	docker compose --profile cache down --remove-orphans

docker-build:  ## Build runtime container image (multi-stage, non-root)
	docker build -t admin-platform:dev .
