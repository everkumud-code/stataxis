FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-all.txt .
RUN pip install --no-cache-dir -r requirements-all.txt

COPY . .

RUN useradd --create-home --uid 10001 stataxis
USER stataxis

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3   CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3).read()"

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8000} web:application"]
