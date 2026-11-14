.PHONY: install lint format typecheck test check build clean docker

install:
	pip install -e ".[dev]"

lint:
	ruff check src tests examples
	ruff format --check src tests examples

format:
	ruff check --fix src tests examples
	ruff format src tests examples

typecheck:
	mypy

test:
	pytest --cov

check: lint typecheck test

build: clean
	python -m build
	python -m twine check dist/*

docker:
	docker build -t bitsopay:local .

clean:
	rm -rf build dist src/*.egg-info .coverage htmlcov
