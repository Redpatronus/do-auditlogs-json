.PHONY: setup test lint check scrape
setup:
	./scripts/setup.sh
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check src tests
check:
	.venv/bin/do-audit check
scrape:
	.venv/bin/do-audit scrape
