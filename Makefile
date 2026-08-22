.PHONY: install install-browsers format format-check lint typecheck test test-unit test-integration test-e2e coverage docs-check actionlint build check dev-server dev-web

install:
	npm install
	npm run build --workspace web
	uv sync --all-groups

install-browsers:
	npx playwright install chromium

format:
	uv run ruff format .
	uv run ruff check --fix .
	npm run format

format-check:
	uv run ruff format --check .
	npm run format:check

lint:
	uv run ruff check .
	npm run lint

typecheck:
	uv run mypy server/src server/tests
	npm run typecheck

test: test-unit test-integration

test-unit:
	uv run pytest server/tests -m "not integration"
	npm run test

test-integration:
	uv run pytest server/tests -m integration

test-e2e:
	npm run build:chrome --workspace extension
	npm run test:e2e:extension

coverage:
	mkdir -p coverage/python
	uv run pytest server/tests --cov=elsewise --cov-report=term-missing --cov-report=xml:coverage/python/coverage.xml --cov-report=html:coverage/python/html
	npm run coverage --workspaces --if-present

docs-check:
	uv run python scripts/check-docs.py

actionlint:
	@command -v actionlint >/dev/null 2>&1 || { echo "actionlint is not installed; see https://github.com/rhysd/actionlint" >&2; exit 2; }
	actionlint .github/workflows/*.yml

build:
	npm run build
	uv build
	uv run python scripts/verify-wheel.py

check: format-check lint typecheck docs-check test build test-e2e

dev-server:
	uv run uvicorn elsewise.main:app --app-dir server/src --reload --port 38473

dev-web:
	npm run dev --workspace web
