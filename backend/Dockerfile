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

FROM python AS model-prepare
COPY --from=uv /uv /usr/local/bin/uv
COPY backend/requirements-v32-cuda.lock /tmp/requirements-v32-cuda.lock
RUN uv pip install --system --no-cache --constraint /tmp/requirements-v32-cuda.lock huggingface-hub
WORKDIR /app
COPY backend/docker/prepare-v32-model.py ./
CMD ["python", "/app/prepare-v32-model.py"]

FROM python AS document-build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
COPY backend/requirements-v32-cuda.lock ./
RUN uv venv /opt/doccheck-v32 \
    && uv pip sync --python /opt/doccheck-v32/bin/python --only-binary :all: requirements-v32-cuda.lock
COPY backend/pyproject.toml ./
COPY backend/src ./src
COPY backend/ml_module/pyproject.toml backend/ml_module/README.md ./ml_module/
COPY backend/ml_module/src ./ml_module/src
RUN uv pip install --python /opt/doccheck-v32/bin/python --no-deps . ./ml_module \
    && uv pip check --python /opt/doccheck-v32/bin/python

FROM runtime AS document-runtime
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates libgl1 libglib2.0-0t64 libportaudio2 \
       tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*
COPY --from=document-build /opt/doccheck-v32 /opt/doccheck-v32
ENV PATH="/opt/doccheck-v32/bin:$PATH" PYTHONPATH=/app \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY bench/__init__.py ./bench/
COPY bench/e2e_v32_20261114/__init__.py \
     bench/e2e_v32_20261114/classification.py \
     bench/e2e_v32_20261114/decision_rules.py \
     bench/e2e_v32_20261114/document_identity.py \
     bench/e2e_v32_20261114/native_report.py \
     bench/e2e_v32_20261114/runtime.py \
     ./bench/e2e_v32_20261114/
USER 10001:10001
RUN python -m doccheck_backend.run_worker --help \
    && python -c "from doccheck_ml.qwen import QwenReader; from doccheck_backend.v32_processor import create_processor; from bench.e2e_v32_20261114 import classification, native_report, runtime" \
    && tesseract --list-langs | grep -x eng \
    && tesseract --list-langs | grep -x rus

FROM runtime AS default
