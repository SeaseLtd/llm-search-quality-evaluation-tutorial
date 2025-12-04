"""
vespa_init.py
"""
import io
import json
import logging
import os
import sys
import time
import zipfile
from pathlib import Path
from threading import Lock
from typing import Optional, Any

import requests
from vespa.application import Vespa

HOST_ENDPOINT = os.getenv("VESPA_ENDPOINT", "http://vespa:8080")
CONFIG_ENDPOINT = os.getenv("CONFIG_ENDPOINT", "http://vespa:19071")
APP_PATH = "/opt/app/app"
SCHEMA_NAME = "doc"

DATASET = os.getenv("DATASET", "/opt/app/data/dataset.json")

EMBEDDINGS_FOLDER = "/opt/app/embeddings"
os.makedirs(EMBEDDINGS_FOLDER, exist_ok=True)

EMBEDDINGS_FILE = os.path.join(EMBEDDINGS_FOLDER, "documents_embeddings.jsonl")
TMP_FILE = os.getenv("TMP_FILE", "/tmp/merged_dataset.json")

DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "600"))
FORCE_REINDEX = os.getenv("FORCE_REINDEX", "false").lower() == "true"
INDEX_BATCH_SIZE = 1000

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vespa_init")


def wait_for_vespa_config_server(config_endpoint: str, timeout: int, interval: float = 1.0) -> None:
    """Waits until the Vespa Config server is up."""
    health_url = f"{config_endpoint.rstrip('/')}/state/v1/health"
    log.info(f"Waiting for Vespa Config server at {health_url} ...")

    start_time = time.time()
    deadline = start_time + timeout

    while time.time() < deadline:
        try:
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                log.info(f"Vespa Config server is ready. It took {time.time() - start_time:.2f} seconds.")
                return
        except (requests.RequestException, ValueError):
            pass

        time.sleep(interval)
    raise RuntimeError(f"Vespa Config server did not become ready after {timeout} seconds: {health_url}")


def deploy_vespa_app(app_path: str, config_endpoint: str) -> None:
    """
    Deploys the Vespa application package.
    This zips the folder at `app_path` in-memory and posts it to: /application/v2/tenant/default/prepareandactivate
    """
    deploy_url = f"{config_endpoint.rstrip('/')}/application/v2/tenant/default/prepareandactivate"

    log.info(f"Zipping application from {app_path} ...")

    # Create an in-memory zip of the application folder
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, _, files in os.walk(app_path):
            for file in files:
                file_path = os.path.join(root, file)
                archive_name = os.path.relpath(file_path, app_path)
                zip_file.write(file_path, archive_name)

    zip_buffer.seek(0)
    log.info(f"Deploying (uploading zip) to {deploy_url} ...")

    try:
        response = requests.post(deploy_url, headers={"Content-Type": "application/zip"}, data=zip_buffer,
                                 timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        log.info(f"Deployment successful. Response: {response.json()}")
    except requests.RequestException as e:
        log.error(f"Vespa deployment failed: {e}")
        raise


def wait_for_vespa_app(host_endpoint: str, timeout: int, interval: float = 1.0) -> None:
    """ Waits until the Vespa app/container returns 200 at /status.html."""
    health_url = f"{host_endpoint.rstrip('/')}/status.html"
    log.info(f"Waiting for Vespa app at {health_url} ...")

    start_time = time.time()
    deadline = start_time + timeout

    while time.time() < deadline:
        try:
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                log.info(f"Vespa app is ready. It took {time.time() - start_time:.2f} seconds.")
                return
        except requests.RequestException:
            pass
        time.sleep(interval)
    raise RuntimeError(f"Vespa app did not become ready after {timeout} seconds: {health_url}")


def get_vespa_doc_count(host_endpoint: str, timeout: int = 5) -> int:
    """
    Returns total document count from Vespa /search endpoint or 0 in case of exception.
    Uses YQL: select * from sources * where true limit 0
    """
    search_url = f"{host_endpoint.rstrip('/')}/search/"

    params = {
        "yql": "select * from sources * where true limit 0"
    }

    try:
        response = requests.get(search_url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return int(data.get("root", {}).get("fields", {}).get("totalCount", 0))
    except Exception as e:
        log.error(f"Unable to get document count from Vespa: {e}")
        raise


def load_dataset_to_dict(path: str) -> list[dict[str, Any]]:
    """Loads dataset (json) """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")
    with p.open("r", encoding="utf-8") as file:
        data = json.load(file)
        if isinstance(data, list):
            return data
        else:
            raise ValueError("Expected dataset JSON file to be an array of documents")


def load_embeddings_to_dict(path: str) -> dict[str, list[float]]:
    """
    Loads embeddings from jsonl file to dict. Each line: {"id":"...","vector":[...] }
    Returns dict of (id, [vector])
    """
    vectors: dict[str, list[float]] = {}
    p = Path(path)
    if not p.exists():
        log.info(f"Embeddings file not found: {path}")
        return vectors
    with p.open("r", encoding="utf-8") as file:
        for i, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                _id = row.get("id")
                vector = row.get("vector")
                if _id and isinstance(vector, list):
                    vectors[str(_id)] = vector
                else:
                    log.debug(f"Skipping embeddings line {i}: missing id or vector")
            except Exception as e:
                log.error("Exception in embeddings file", e)
                raise
    log.info("Loaded %d embeddings from %s", len(vectors), path)
    return vectors


def round_vector(vector: list[float], digits: int = 12) -> list[float]:
    """Rounds each value in the vector to digits=12 decimals."""
    return [round(float(x), digits) for x in vector]


def merge_docs_with_embeddings(docs: list[dict[str, Any]], embeddings: dict[str, list[float]],
                               output_path: Optional[str] = None) -> list[dict[str, Any]]:
    """ Merges two dicts one containing the doc fields e.g. title, context, etc.
    while the other one contains <id, vector> fields"""
    merged = []
    for d in docs:
        doc = dict(d)
        doc_id = str(doc.get("id"))
        if not doc_id:
            log.error("Document missing id")
        vector = embeddings.get(doc_id)
        if vector is not None:
            doc["vector"] = round_vector(vector, digits=12)
        merged.append(doc)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(merged, file, ensure_ascii=False)
        log.info(f"Wrote merged dataset to {output_path}")
    return merged


class IndexingCounter:
    def __init__(self, total_docs):
        self.num_docs = total_docs
        self._lock = Lock()

    def count_error(self):
        with self._lock:
            self.num_docs -= 1

    def get_indexed_docs_count(self):
        return self.num_docs


def feed_vespa_documents(host_endpoint: str, schema: str, docs: list[dict[str, Any]]) -> None:
    """
    Feeds documents using pyvespa by streaming over iterable type
    """
    total_docs = len(docs)
    if total_docs == 0:
        log.warning("No documents provided for indexing.")
        return

    running_vespa_app = Vespa(url=host_endpoint)
    indexing_counter = IndexingCounter(total_docs)

    def _callback(response, doc_id):
        if not response.is_successful():
            log.error(f"Failed to feed document {doc_id}: {response.json}")
            indexing_counter.count_error()
        else:
            log.debug(f"Indexed doc with doc_id {doc_id}")

    def _document_generator():
        for doc in docs:
            doc_id = str(doc.pop("id"))

            if "authors" in doc and isinstance(doc["authors"], str):
                doc["authors"] = [doc["authors"]]

            yield {
                "id": doc_id,
                "fields": doc,
                "groupname": None
            }

    start_time = time.time()
    log.info(f"Started indexing {total_docs} docs into Vespa schema {schema}")

    # HTTP/2 with concurrency: 16 workers, 4k memory
    running_vespa_app.feed_iterable(iter=_document_generator(),
                                    schema=schema,
                                    callback=_callback,
                                    max_queue_size=4000,
                                    max_workers=16)

    indexed_docs_count = indexing_counter.get_indexed_docs_count()
    end_time = time.time()
    log.info(f"Indexing finished. It took {(end_time - start_time):.2f} seconds. "
             f"Successfully indexed: {indexed_docs_count} out of {total_docs} docs.")


def main() -> int:
    log.info("Starting vespa_init.py")
    try:
        wait_for_vespa_config_server(config_endpoint=CONFIG_ENDPOINT, timeout=DEFAULT_TIMEOUT, interval=1.0)
        deploy_vespa_app(app_path=APP_PATH, config_endpoint=CONFIG_ENDPOINT)
        wait_for_vespa_app(host_endpoint=HOST_ENDPOINT, timeout=DEFAULT_TIMEOUT, interval=1.0)
    except Exception as e:
        log.error(f"Vespa is not available: {e}")
        sys.exit(1)

    count_docs = get_vespa_doc_count(host_endpoint=HOST_ENDPOINT, timeout=DEFAULT_TIMEOUT)
    log.info(f"Vespa has {count_docs} docs")

    if count_docs == 0 or FORCE_REINDEX:
        docs = load_dataset_to_dict(DATASET)
        embeddings = load_embeddings_to_dict(EMBEDDINGS_FILE)

        if embeddings:
            log.info("Using merged dataset with embeddings")
            merged_docs = merge_docs_with_embeddings(docs, embeddings, output_path=TMP_FILE)
            feed_vespa_documents(host_endpoint=HOST_ENDPOINT, schema=SCHEMA_NAME, docs=merged_docs)
        else:
            log.info("Using plain dataset without embeddings")
            feed_vespa_documents(host_endpoint=HOST_ENDPOINT, schema=SCHEMA_NAME, docs=docs)
            Path(TMP_FILE).unlink(missing_ok=True)
    else:
        log.info("Skipping indexing as there are already docs indexed. Use FORCE_REINDEX=true to force re-indexing")

    return 0


if __name__ == "__main__":
    sys.exit(main())
