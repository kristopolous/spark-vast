.PHONY: dev test lint format build publish clean

dev: # Create .venv with all dependency groups
	uv sync --all-groups

test: # Run unit tests (no network)
	uv run pytest

lint: # Ruff lint
	uv run ruff check src tests

format: # Ruff format
	uv run ruff format src tests

build: clean # Build wheel + sdist
	uv build

publish: build # Upload dist/ to PyPI with twine (REPO=testpypi to dry-run)
	uvx twine check dist/*
	uvx twine upload $(if $(REPO),-r $(REPO)) dist/*

clean:
	rm -rf dist build src/*.egg-info .pytest_cache
