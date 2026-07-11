# Architecture

UK Sponsor Finder is a read-heavy Streamlit application with an optional Companies House enrichment
path. The application deliberately keeps filtering logic independent from Streamlit so it can be
tested without a browser.

## Data flow

```text
UKVI sponsor CSV
        |
        v
load and validate -> clean locations -> build sponsor/location view
        |                                      |
        |                                      v
        +----------------------------> attach sector cache
                                               |
                                               v
                                  search and route-aware filters
                                               |
                                               v
                                  table, metrics, and CSV export
```

The Companies House path is separate:

```text
sponsor name + location -> candidate search -> confidence checks -> company profile
                                                        |
                                           cache only accepted matches
```

## Components

- `app.py` owns presentation, session state, data-source selection, and user-facing errors.
- `sponsor_filter.py` owns schema detection, normalization, sponsor identity, SIC classification, and
  filtering.
- `companies_house.py` owns HTTP behavior and candidate matching.
- `cache_store.py` owns safe local persistence when present.
- `export_utils.py` owns spreadsheet-safe CSV serialization.
- `build_sector_dictionary.py` performs resumable batch enrichment.

## Trust boundaries

- Uploaded CSV files are untrusted input. Validate their headers and size before processing.
- Companies House search results are candidates because the sponsor register has no company number.
- CSV exports may be opened in spreadsheet applications; values that can be interpreted as formulas
  should be neutralized.
- API credentials are deployment secrets and must never enter source control, logs, or downloads.

## Scaling notes

The bundled CSV design works well for a single Streamlit process. Multiple replicas should not write
to a shared CSV. A larger deployment should move sponsor snapshots and enrichment records into a
versioned database or object store, run enrichment as a background job, and serve the Streamlit UI
from immutable snapshots.
