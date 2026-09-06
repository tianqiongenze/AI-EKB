FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -e .

EXPOSE 8080

CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8080", "enterprise_ekb.app:app"]
