# NNFX beta service image. Build context: repository root.
#   docker build -f deploy/Dockerfile -t nnfx-beta .
# On an Iranian server where Docker Hub / PyPI are unreachable, build elsewhere and
# move the image:  docker save nnfx-beta | ssh server docker load   (see deploy/README.fa.md)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app

COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY nnfx ./nnfx
COPY config ./config
COPY research ./research
COPY data/sample ./data/sample
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 nnfx && mkdir -p /app/runs/beta /app/data/cache && chown -R nnfx /app/runs /app/data/cache
USER nnfx
EXPOSE 8765
CMD ["/app/.venv/bin/nnfx", "ui", "--host", "0.0.0.0", "--port", "8765", "--auth-db", "/app/runs/beta/beta.db", "--secure-cookies", "--trust-proxy"]
