# UK Sponsor Finder

[![CI](https://github.com/sushmee-karthick/sponsor-finder/actions/workflows/ci.yml/badge.svg)](https://github.com/sushmee-karthick/sponsor-finder/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-2563EB.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-app-FF4B4B.svg)](https://streamlit.io/)

UK Sponsor Finder turns the UK Visas and Immigration sponsor register into a searchable Streamlit
application. Explore organisations by company name, visa route, sponsorship rating, location, and a
candidate industry sector enriched from Companies House.

> **Important:** a sponsor-list entry does not mean that an organisation has an open job or will
> sponsor a particular application. Companies House matches are probabilistic because the official
> sponsor register does not contain company numbers. Verify decisions against the
> [official UKVI register](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers)
> and the organisation itself. This project does not provide immigration or legal advice.

## Highlights

- Bundled sponsor snapshot with optional CSV upload
- Route-aware rating filters that preserve the relationship between visa route and rating
- Sponsor locations kept separate instead of collapsing same-name organisations across towns
- Company-name search, location and sector filters, summary metrics, and full CSV export
- Explicit unknown and ambiguous sector states instead of silent guessing
- Confidence-aware Companies House matching with retry and rate-limit handling
- Cached data preparation for responsive Streamlit interactions
- Automated tests, linting, data-integrity checks, dependency updates, and Docker deployment

## Quick start

UK Sponsor Finder supports Python 3.11 and newer.

```bash
git clone https://github.com/sushmee-karthick/sponsor-finder.git
cd sponsor-finder
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip -r requirements.txt
streamlit run app.py
```

On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1`.

The application uses `latest_sponsors.csv` by default. You can also upload a compatible UKVI CSV in
the sidebar without replacing repository files.

## Optional Companies House enrichment

Filtering works without an API key. A key is needed only for live sector lookup or batch enrichment.

1. Create a key through the
   [Companies House developer service](https://developer.company-information.service.gov.uk/).
2. Copy the safe template and add the key locally:

   ```bash
   cp .env.example .env
   # Edit .env and set CH_API_KEY. Never commit this file.
   ```

3. To enrich a sponsor CSV in a resumable batch:

   ```bash
   python build_sector_dictionary.py path/to/sponsors.csv
   ```

Search results are treated as candidates. Low-confidence, ambiguous, and transiently failed lookups
must not be persisted as verified matches. Companies House enforces
[API rate limits](https://developer.company-information.service.gov.uk/developer-guidelines/), so a
complete refresh can take more than a day.

## Data quality

The committed snapshot is described by `data_manifest.json`. Validate its row counts and checksums
with:

```bash
python scripts/validate_data.py
```

The current snapshot predates the manifest and has no recorded retrieval date; its sector cache uses
a legacy, unverified matching policy. See [DATA_SOURCES.md](DATA_SOURCES.md) for provenance,
limitations, and the review process required for snapshot updates.

## Development

Install development dependencies and run the complete local gate:

```bash
python -m pip install -r requirements-dev.txt
make check
```

Equivalent commands are:

```bash
ruff check .
ruff format --check .
python scripts/validate_data.py
pip-audit -r requirements.txt
pytest
```

CI runs these checks on Python 3.11 and 3.13. Tests must mock Companies House and must never depend on
a live API key or network access.

## Deployment

Run the production container locally:

```bash
docker build -t sponsor-finder .
docker run --rm -p 8501:8501 --env-file .env sponsor-finder
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Streamlit Community Cloud, health checks, secret
configuration, and the changes required for multi-replica deployment.

## Project structure

| Path | Responsibility |
|---|---|
| `app.py` | Streamlit presentation, data-source selection, and user workflow |
| `sponsor_filter.py` | CSV validation, sponsor identity, SIC mapping, and filtering |
| `companies_house.py` | API client, retries, and confidence-aware candidate matching |
| `cache_store.py` | Atomic, keyed local cache updates |
| `export_utils.py` | Formula-safe CSV export serialization |
| `build_sector_dictionary.py` | Resumable batch enrichment |
| `data_manifest.json` | Snapshot provenance, row counts, and checksums |
| `tests/` | Unit and Streamlit application tests |
| `docs/` | Architecture and deployment guidance |

The detailed component and trust-boundary design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Keep generated-data updates
separate from application changes and include regression tests for filtering or matching changes.

The repository owner has not yet selected a project licence. The owner should choose and document one
before a release; source datasets may have separate terms and attribution requirements.
