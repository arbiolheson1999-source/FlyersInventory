FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir flask psycopg2-binary gunicorn

ENV PORT=5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]