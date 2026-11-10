.PHONY: up down logs test lint install eval

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f middleware

install:
	cd middleware && pip install -c constraints.txt -e '.[dev]'

test:
	cd middleware && python -m pytest

lint:
	cd middleware && ruff check . && ruff format --check .

eval:
	cd middleware && python scripts/eval_prompt.py
