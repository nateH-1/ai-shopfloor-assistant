FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# CTranslate2 (local speech recognition) uses the OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt
COPY . ./

# Match start-dev.ps1's repository-root working directory and relative data paths.
WORKDIR /app
ENV PYTHONPATH=/app/backend
EXPOSE 5000
CMD ["python", "-c", "import app; app._initialize_sqlite(); app._init_store(); app._start_guest_cleanup(); app.app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)"]
