.PHONY: install run lint format test check

install:
	python -m pip install --upgrade pip -r requirements-dev.txt

run:
	streamlit run app.py

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

test:
	pytest --cov --cov-report=term-missing

check: lint
	python scripts/validate_data.py
	pip-audit -r requirements.txt
	pytest --cov --cov-report=term-missing
