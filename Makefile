.PHONY: up down psql sftp seed migrate dates test run backfill clean

up:
	docker compose up -d
	@echo "Waiting for Postgres to be ready..."
	@until docker compose exec postgres pg_isready -q -U retail -d retail > /dev/null 2>&1; do \
		printf '.'; sleep 1; \
	done
	@echo " ready."

down:
	docker compose down

# Opens a psql shell inside the running Postgres container
psql:
	docker compose exec postgres psql -U retail -d retail

# Prints the sftp connection command — paste it in your terminal to browse files
sftp:
	@echo "Run: sftp -P 2222 retail@localhost"
	@echo "Password: retail"
	@echo "Then: ls incoming/  to see uploaded store files"

seed:
	@test -f .env || (echo "ERROR: .env not found — copy .env.example first: cp .env.example .env" && exit 1)
	python scripts/seed_sample_data.py

migrate:
	@test -f .env || (echo "ERROR: .env not found — copy .env.example first: cp .env.example .env" && exit 1)
	python scripts/apply_sql.py

dates:
	@test -f .env || (echo "ERROR: .env not found — copy .env.example first: cp .env.example .env" && exit 1)
	python scripts/populate_dim_date.py

test:
	pytest tests/ -v

run:
	python -m src.main

# Usage: make backfill FROM=2026-04-01 TO=2026-04-30
#        make backfill FROM=2026-04-01          (TO defaults to yesterday)
backfill:
	@test -n "$(FROM)" || (echo "Usage: make backfill FROM=YYYY-MM-DD [TO=YYYY-MM-DD]" && exit 1)
	python -m src.main --backfill-from $(FROM) $(if $(TO),--backfill-to $(TO),)

clean:
	docker compose down -v
	@echo "Volumes removed. Data is gone — run 'make up && make seed' to start fresh."
