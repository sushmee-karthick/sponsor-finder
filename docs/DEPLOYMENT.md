# Deployment

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
streamlit run app.py
```

The Companies House API key is optional. Without it, filtering and cached sector data remain
available while live enrichment is disabled.

## Docker

```bash
docker build -t sponsor-finder .
docker run --rm -p 8501:8501 --env-file .env sponsor-finder
```

The container exposes Streamlit on port `8501` and uses `/_stcore/health` for its health check.

## Streamlit Community Cloud

1. Connect the repository and select `app.py` as the entrypoint.
2. Add `CH_API_KEY` in the application's secrets settings if live lookup is required.
3. Do not commit `.streamlit/secrets.toml`.
4. Confirm that the committed sponsor snapshot is within platform storage and memory limits.

## Production considerations

- Serve over HTTPS and restrict secret access to the runtime identity.
- Treat the container filesystem and Streamlit Community Cloud filesystem as ephemeral.
- Disable or replace cache writes when running multiple replicas.
- Refresh sponsor data through a reviewed job, not through a web request.
- Monitor availability, request latency, Companies House `429` responses, ambiguous-match rates, and
  snapshot age.
- Back up versioned data snapshots outside the application container.

For a multi-user or multi-replica service, replace CSV persistence with a transactional datastore and
move Companies House enrichment to a queue-backed worker.
