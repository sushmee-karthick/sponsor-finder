# 🔎 UK Sponsor Finder

A website where anyone can upload the UK sponsor list (CSV) and filter it by
**visa route**, **rating**, **town/city**, and **sector** — with sectors coming
from official Companies House data, *not* guessed from the company name.

## What's in the folder

| File | What it is | Plain words |
|---|---|---|
| `app.py` | The website | The screen people see and click |
| `sponsor_filter.py` | The logic | The "brain" that does the filtering |
| `build_sector_dictionary.py` | The enrichment script | "Machine 1" — looks up real sectors |
| `sector_cache.csv` | The sector data | The saved answers the website reads (demo data for now) |
| `sample_sponsors.csv` | A tiny test file | So you can try it without downloading the big file |
| `requirements.txt` | The library list | What to install |

## Step 1 — Install the tools (one time)

Open a terminal in this folder and run:

```
pip install -r requirements.txt
```

## Step 2 — Run the website

```
streamlit run app.py
```

Your browser opens. Tick **"try it with the small sample file"** and play with the
filters in the left sidebar. Everything works right away using the demo sector data.

## Step 3 — Use the real list

1. Download the real CSV from GOV.UK: search **"Register of licensed sponsors: workers"**.
2. In the website, upload that file instead of using the sample.
3. The visa, rating and town filters work immediately on the real file.

## Step 4 — Get REAL sectors (the important part)

The demo sectors only cover the sample companies. To get real sectors for the
whole list:

1. Get a **free** Companies House API key:
   https://developer.company-information.service.gov.uk/
2. Tell your computer the key (do this in the terminal):
   - Mac/Linux: `export CH_API_KEY="your-key-here"`
   - Windows: `set CH_API_KEY=your-key-here`
3. Run the background script on the real file:
   ```
   python build_sector_dictionary.py sponsors.csv
   ```
   This is slow (it can take a few hours for the full list) because the free API
   has a speed limit. **You can stop it and run it again later** — it remembers
   what it already did. When it finishes, `sector_cache.csv` is updated and the
   website's sector filter works on the real data.

## Good to know

- Being on the list means a company **can** sponsor — not that it has a job open
  right now. Always check the company's own careers page.
- Only **A-rated** sponsors can issue new visas, so the rating filter matters.
- Companies appear once per visa they hold; the app removes those duplicates.

## What comes next (not built yet)

- **Find each company's website + careers page** (Phase 2).
- **Check if they're hiring** by reading their job listings (Phase 3 — the hardest).
- Put the website online for free with **Streamlit Community Cloud** or
  **Hugging Face Spaces** so anyone can use it.
