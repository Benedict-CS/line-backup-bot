# Lightweight image for LINE → Nextcloud backup bot
FROM python:3.11-slim

WORKDIR /app

# Install deps: use binary aiohttp to avoid building (no gcc in slim), then line-bot-sdk without deps
COPY requirements.txt .
RUN pip install --no-cache-dir 'aiohttp>=3.9' --only-binary aiohttp && \
    pip install --no-cache-dir line-bot-sdk==2.4.3 --no-deps && \
    pip install --no-cache-dir fastapi==0.109.2 uvicorn==0.27.1 python-dotenv==1.0.1 requests python-multipart future

COPY main.py config.py source_map.py nextcloud.py auth.py handlers.py stats.py hash_store.py .
COPY templates/ templates/

# Run as non-root (security)
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
