.PHONY: backend-install backend-run backend-test backend-check frontend-install frontend-run check up logs down

backend-install:
	python -m pip install -e "./backend[dev]"

backend-run:
	uvicorn app.main:app --reload --app-dir backend/src

backend-test:
	cd backend && pytest --cov=app

backend-check:
	cd backend && ruff check .
	cd backend && ruff format --check .
	cd backend && mypy

frontend-install:
	cd frontend && npm install

frontend-run:
	cd frontend && npm run dev

check: backend-check backend-test
	cd frontend && npm run typecheck

up:
	docker compose up --build -d

logs:
	docker compose logs -f

down:
	docker compose down
