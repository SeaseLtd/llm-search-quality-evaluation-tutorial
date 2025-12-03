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
from typing import Optional, Any

import requests

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
    log.info("Waiting for Vespa Config server at %s ...", health_url)

    start_time = time.time()
    deadline = start_time + timeout

    while time.time() < deadline:
        try:
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                log.info("Vespa Config server is ready.(Took %.2fs)", time.time() - start_time)
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

    log.info("Zipping application from %s ...", app_path)

    # Create an in-memory zip of the application folder
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, _, files in os.walk(app_path):
            for file in files:
                file_path = os.path.join(root, file)
                archive_name = os.path.relpath(file_path, app_path)
                zip_file.write(file_path, archive_name)

    zip_buffer.seek(0)
    log.info("Deploying (uploading zip) to %s ...", deploy_url)

    try:
        response = requests.post(deploy_url, headers={"Content-Type": "application/zip"}, data=zip_buffer,
                                 timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        log.info("Deployment successful. Response: %s", response.json())
    except requests.RequestException as e:
        log.error("Vespa deployment failed: %s", e)
        raise


def wait_for_vespa_app(host_endpoint: str, timeout: int, interval: float = 1.0) -> None:
    """ Waits until the Vespa app/container returns 200 at /status.html."""
    health_url = f"{host_endpoint.rstrip('/')}/status.html"
    log.info("Waiting for Vespa app at %s ...", health_url)

    start_time = time.time()
    deadline = start_time + timeout

    while time.time() < deadline:
        try:
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                log.info("Vespa app is ready. (Took %.2fs)", time.time() - start_time)
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
        log.error("Unable to get document count from Vespa: %s", e)
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
        log.info("Embeddings file not found: %s", path)
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
                    log.debug("Skipping embeddings line %d: missing id or vector", i)
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
        log.info("Wrote merged dataset to %s", output_path)
    return merged


def feed_vespa_documents(host_endpoint: str, schema: str, docs: list[dict[str, Any]], timeout: int = 10) -> None:
    """
    Feeds documents to /document/v1/default/{schema}/docid/{doc_id} Vespa
    Function iterates through the batch and sends individual POST requests using requests.Session()
    """

    total_docs = len(docs)
    if total_docs == 0:
        log.warning("No documents provided for indexing.")
        return

    log.info("Started indexing %d documents into Vespa schema '%s'", total_docs, schema)

    num_batches = (total_docs + INDEX_BATCH_SIZE - 1) // INDEX_BATCH_SIZE

    session = requests.Session()

    feed_url_base = f"{host_endpoint.rstrip('/')}/document/v1/default/{schema}/docid"

    index_success: bool = True

    for i in range(num_batches):
        start_index = i * INDEX_BATCH_SIZE
        end_index = min((i + 1) * INDEX_BATCH_SIZE, total_docs)

        batch = docs[start_index:end_index]

        if not batch:
            continue

        log.info(f"Processing Batch {i + 1}/{num_batches} ({len(batch)} docs)")

        for doc in batch:
            doc_id = str(doc.pop("id"))
            current_url = f"{feed_url_base}/{doc_id}"

            # authors is defined as a 'list' in the schema
            if "authors" in doc and isinstance(doc["authors"], str):
                doc["authors"] = [doc["authors"]]

            payload = {"fields": doc}

            try:
                response = session.post(current_url, json=payload, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as e:
                log.error(f"Failed to feed document {doc_id}: {e}")
                raise

        log.debug(f"Batch {i + 1} indexing successful")

    log.info("Successfully processed %d documents in %d batches.", total_docs, num_batches)
    session.close()


def main() -> int:
    log.info("Starting vespa_init.py")
    try:
        wait_for_vespa_config_server(config_endpoint=CONFIG_ENDPOINT, timeout=DEFAULT_TIMEOUT, interval=1.0)
        deploy_vespa_app(app_path=APP_PATH, config_endpoint=CONFIG_ENDPOINT)
        wait_for_vespa_app(host_endpoint=HOST_ENDPOINT, timeout=DEFAULT_TIMEOUT, interval=1.0)
    except Exception as e:
        log.error("Vespa is not available: %s", e)
        sys.exit(1)

    count_docs = get_vespa_doc_count(host_endpoint=HOST_ENDPOINT, timeout=DEFAULT_TIMEOUT)
    log.info("Vespa has doc count = %d docs", count_docs)

    if count_docs == 0 or FORCE_REINDEX:
        docs = load_dataset_to_dict(DATASET)
        embeddings = load_embeddings_to_dict(EMBEDDINGS_FILE)

        if embeddings:
            log.info("Using merged dataset with embeddings")
            merged_docs = merge_docs_with_embeddings(docs, embeddings, output_path=TMP_FILE)
            feed_vespa_documents(host_endpoint=HOST_ENDPOINT, schema=SCHEMA_NAME,
                                 docs=merged_docs, timeout=DEFAULT_TIMEOUT)
        else:
            log.info("Using plain dataset without embeddings")
            feed_vespa_documents(host_endpoint=HOST_ENDPOINT, schema=SCHEMA_NAME, docs=docs, timeout=DEFAULT_TIMEOUT)
            Path(TMP_FILE).unlink(missing_ok=True)
    else:
        log.info("Skipping indexing as there are already docs indexed. Use FORCE_REINDEX=true to force re-indexing")

    return 0


if __name__ == "__main__":
    sys.exit(main())
