# Dockerfile — NatCat Underwriting Engine
# Build:  docker build -t natcat-underwriting .
# Run:    docker run --rm -p 8501:8501 \
#           -v %cd%/secrets:/app/.streamlit/secrets:ro \
#           -v natcat-data:/app/data \
#           natcat-underwriting

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHERUSAGESTATS=false

# System deps for reportlab (freetype) and folium
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libfreetype6 \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# History DB lives in /app/data so it survives container restarts when mounted
RUN mkdir -p /app/data
ENV NATCAT_DB_PATH=/app/data/history.db

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health').read()" || exit 1

CMD ["streamlit", "run", "app.py"]
