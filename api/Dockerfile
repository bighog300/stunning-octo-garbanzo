FROM python:3.11-slim

WORKDIR /opt/artio

COPY api/requirements.txt /opt/artio/api/requirements.txt
RUN pip install --no-cache-dir -r /opt/artio/api/requirements.txt

COPY api /opt/artio/api
COPY artio_cli /opt/artio/artio_cli
COPY scraper /opt/artio/scraper

WORKDIR /opt/artio/api

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
