FROM ghcr.io/astral-sh/uv:0.9.17@sha256:5cb6b54d2bc3fe2eb9a8483db958a0b9eebf9edff68adedb369df8e7b98711a2 AS uv
FROM python:3.12.12-slim-trixie@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c AS python

FROM python AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
RUN groupadd --gid 10001 doccheck \
    && useradd --uid 10001 --gid 10001 --no-create-home doccheck \
    && install -d -m 700 -o doccheck -g doccheck /var/lib/doccheck/runs
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "doccheck_backend.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS document-runtime
ENV PYTHONPATH=/app
COPY bench/__init__.py ./bench/
COPY bench/e2e_v32_20261114 ./bench/e2e_v32_20261114
RUN python -c "from PIL import Image; import pypdfium2; from bench.e2e_v32_20261114 import run; from doccheck_backend.v32_adapter import process"

FROM runtime AS default
