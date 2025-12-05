FROM python:3.10-slim

RUN pip install --no-cache-dir requests

WORKDIR /opt/app

COPY opensearch_init.py /opt/app/opensearch_init.py
COPY data/ /opt/app/data/

# create embeddings dir inside opt/app/
RUN mkdir -p /opt/app/embeddings \
 && chmod 755 /opt/app/embeddings


RUN chmod +x /opt/app/opensearch_init.py

CMD ["python", "/opt/app/opensearch_init.py"]

