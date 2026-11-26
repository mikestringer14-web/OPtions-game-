FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx
COPY app ./app
COPY scripts ./scripts
RUN useradd -m ea && mkdir -p /data && chown ea /data
USER ea
ENV EA_DB_PATH=/data/assistant.db
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
