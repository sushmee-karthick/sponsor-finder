# Contributing

Thank you for improving UK Sponsor Finder. Keep pull requests focused, explain any data-quality
trade-offs, and include regression tests for behavior changes.

## Local setup

UK Sponsor Finder supports Python 3.11 and newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip -r requirements-dev.txt
cp .env.example .env
```

Add a Companies House API key to `.env` only when exercising live enrichment. Unit tests must not
make live network calls.

## Development checks

Run the same checks as CI before opening a pull request:

```bash
ruff check .
ruff format --check .
pytest
```

Run the application with:

```bash
streamlit run app.py
```

## Pull requests

- Create a feature branch from the latest `main`.
- Avoid mixing generated CSV updates with application changes.
- Do not commit `.env`, Streamlit secrets, API keys, or user-uploaded data.
- Preserve the relationship between sponsor location, visa route, and rating.
- Treat Companies House search results as candidates, not verified matches.
- Include the source and as-of date for generated data changes.

The repository owner should choose and document the project's licence. Source datasets may have
their own terms and attribution requirements.
