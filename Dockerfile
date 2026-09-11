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

# [postgres] is included unconditionally, not just when DATABASE_URL is
# set at runtime -- psycopg[binary] needs no extra build tooling in the
# image (precompiled wheel), and api/dependencies.py only imports it at
# all once DATABASE_URL is actually set, so there's no cost to always
# having it available and no reason to make the image build conditional
# on how a given deployment will be configured.
RUN pip install --no-cache-dir ".[connectors,postgres]"

ENV APM_STATE_DIR=/app/state
RUN mkdir -p /app/state

EXPOSE 8000

CMD ["uvicorn", "apm_connectors.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
