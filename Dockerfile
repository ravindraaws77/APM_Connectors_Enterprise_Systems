# Container image for the connector API only (src/apm_connectors/api) --
# no reasoning/orchestration layer, no dashboard. See docs/deployment.md
# for how this gets built and run on AWS App Runner, and
# docs/running-locally.md for running it directly with uvicorn.
FROM python:3.12-slim

WORKDIR /app

# Copy just what the package build needs first so `docker build` can
# cache the (slow) dependency install layer across source-only edits
# that don't touch pyproject.toml.
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir ".[connectors]"

ENV APM_STATE_DIR=/app/state
RUN mkdir -p /app/state

EXPOSE 8000

CMD ["uvicorn", "apm_connectors.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
