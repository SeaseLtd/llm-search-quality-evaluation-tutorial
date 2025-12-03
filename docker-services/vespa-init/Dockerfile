# vespa-init/Dockerfile
FROM python:3.10-slim

# keeping vespacli in case of querying vespa inside the vespa docker container
RUN pip install --no-cache-dir vespacli requests

WORKDIR /opt/app

COPY vespa_init.py /opt/app/vespa_init.py
COPY data/ /opt/app/data/
COPY app/ /opt/app/app/


# create embeddings dir inside /opt/app
RUN mkdir -p /opt/app/embeddings \
 && chmod 755 /opt/app/embeddings


RUN chmod +x /opt/app/vespa_init.py


CMD ["python", "/opt/app/vespa_init.py"]
