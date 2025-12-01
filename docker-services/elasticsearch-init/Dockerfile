FROM python:3.10-slim

RUN pip install --no-cache-dir requests

WORKDIR /opt/app

COPY elasticsearch_init.py /opt/app/elasticsearch_init.py
COPY data/ /opt/app/data/

# create embeddings dir inside the image
RUN mkdir -p /opt/app/embeddings \
 && chmod 755 /opt/app/embeddings


RUN chmod +x /opt/app/elasticsearch_init.py

CMD ["python", "/opt/app/elasticsearch_init.py"]

