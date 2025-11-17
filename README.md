# LLM Search Quality Evaluation Tutorial
Hi there, welcome to our LLM search quality evaluation tutorial!

This tutorial guides you through a complete workflow 
going from relevance-labeled dataset generation to comparing exact and approximate vector search performance evaluations.

##  What You'll Learn
* How to generate a relevance-labeled dataset for search evaluation.
* How to run and evaluate an embedding model with exact vector search.
* How to run an approximate vector search (ANN) and compare its performance against the exact vector search.

## Prerequisites
Before we begin, ensure you have the following tools installed and configured:

* Docker & docker-compose: We use dockerized Solr instance as a search engine.
  * Verify with `docker --version` and `docker-compose --version`
* Python 3.10+: Required for running the evaluation toolkit.
  * Verify `python --version`
* uv: Python package installer. This is used to set up the project's virtual environment. 
  * Install with `pip install uv` (or see official [uv install guide](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer))


## Get Started
Now that you have the prerequisites installed, let's get the project set up and running search evaluation.

What we do next:
* Set up rated ranking evaluator project
* Run Solr and index documents
* Run dataset generator tool for relevance dataset creation
* Run embedding model evaluator for exact vector search performance
* Run approximate search evaluator for ANN search performance

-------
### Set up Rated Ranking Evaluator Project
Set up the project and install the dependencies.

To clone [rated-ranking-evaluator repo](https://github.com/SeaseLtd/rated-ranking-evaluator) to your local machine:
```bash
git clone git@github.com:SeaseLtd/rated-ranking-evaluator.git

rated-ranking-evaluator$ cd rre-tools

```

We use `uv` to create a virtual environment and install all the required packages:
```bash
rre-tools$ uv sync
```
----

### Run Solr and Index Documents

We use Solr and run dockerized Solr locally. There is `docker-services` helper dir to run Solr. 
See [docker-services](https://github.com/SeaseLtd/rated-ranking-evaluator/tree/dataset-generator/rre-tools/docker-services)

In addition to running Solr instance, we need to index some documents for the actual search evaluation. 
We use [this dataset](https://github.com/SeaseLtd/llm-search-quality-evaluation-tutorial/data/dataset.json), (~100k docs) extracted from  [BBC news](https://huggingface.co/datasets/RealTimeData/bbc_news_alltime/viewer/2017-02?row=96]).
The dataset is in this repo in `llm-search-quality-evaluation-tutorial/data/dataset.json`

To copy [this dataset](https://github.com/SeaseLtd/llm-search-quality-evaluation-tutorial/data/dataset.json) to the repo  `rre-tools/docker-services/solr-init/data`:
```bash
rre-tools$ cp $localPath/llm-search-quality-evaluation-tutorial/data/dataset.json  ./docker-services/solr-init/data
```

To run Solr (can be reached at http://localhost:8983/solr) and  index the dataset:
```bash
rre-tools$ cd docker-services

docker-services$ docker-compose -f docker-compose.solr.yml up --build
```
----

### Run Dataset Generator

This is a CLI tool to generate relevance dataset for search evaluation. It retrieves documents from search engine, generates synthetic queries, and scores the relevance of document-query pairs using LLMs.

Before running, we need to set up a configuration file.
* See [dataset_generator_config.yaml](https://github.com/SeaseLtd/rated-ranking-evaluator/blob/dataset-generator/rre-tools/configs/dataset_generator/dataset_generator_config.yaml) for an example.
* For detailed configuration info, see the [README](https://github.com/SeaseLtd/rated-ranking-evaluator/blob/dataset-generator/rre-tools/docs/dataset_generator/README.md)

Before running the dataset generator, we need to either set up a LLM configuration file (e.g. provide LLM model API key) or
use [our temporary datastore](https://github.com/SeaseLtd/llm-search-quality-evaluation-tutorial/data/datastore.json) `llm-search-quality-evaluation-tutorial/data/datastore.json` which contains LLM-generated queries & scores.

To copy the datastore:
```bash
rre-tools$ cp $localPath/llm-search-quality-evaluation-tutorial/data/datastore.json  ./resources/tmp
```

To run the dataset generator:
```bash
rre-tools$ uv run dataset_generator --config <path-to-config-yaml>
```

This produces a relevance dataset file under `resources` dir which will be used in the next modules.


To know more about all the possible CLI parameters:
```bash
uv run dataset_generator --help
```

-----
### Run Embedding Model Evaluator
This tool is an MTEB benchmarking extension designed to evaluate embedding models on custom dataset, with a focus on retrieval and reranking tasks.
It assesses model quality by using an exact vector search to establish a "ground truth" for retrieval performance on custom dataset.

Before running, we need to set up a configuration file.
* See [embedding_model_evaluator_config.yaml](https://github.com/SeaseLtd/rated-ranking-evaluator/blob/dataset-generator/rre-tools/configs/embedding_model_evaluator/embedding_model_evaluator_config.yaml) for an example.
* For detailed configuration info, see the [full documentation](https://github.com/SeaseLtd/rated-ranking-evaluator/blob/dataset-generator/rre-tools/docs/embedding_model_evaluator/README.md).

To run the embedding model evaluator:

```bash
uv run embedding_model_evaluator --config <path-to-config-yaml>
```

This outputs task evaluation result and relevance dataset embeddings (document and query embeddings). 
The embeddings are saved to `resources/embeddings` dir which will be used in the next module.

----
### Run Approximate Search Evaluator
This module tests ANN (approximate nearest neighbour) vector search used by the collection enriched with embeddings
from the search engine.

First, we need to index document embeddings to Solr. To do that, run the command below which
re-indexes documents with embeddings generated from the previous module without stopping Solr:

```bash
rre-tools$ cd docker-services

docker-services$ docker-compose -f docker-compose.solr.yml run --rm -e FORCE_REINDEX=true solr-init
```

Second, we need the relevance dataset with RRE format for this module. We run the Dataset Generator
with `output_format=RRE`. Update the dataset generator config file and re-run:
```bash
rre-tools$ uv run dataset_generator --config <path-to-config-yaml>
```
Once we have the relevance dataset (`ratings.json`) file, we set up a configuration file for this approximate search evaluator.
* See [approximate_search_evaluator_config.yaml](https://github.com/SeaseLtd/rated-ranking-evaluator/blob/dataset-generator/rre-tools/configs/approximate_search_evaluator/approximate_search_evaluator_config.yaml) for an example.
* For detailed configuration info, see the [full documentation](https://github.com/SeaseLtd/rated-ranking-evaluator/blob/dataset-generator/rre-tools/docs/approximate_search_evaluator/README.md).

To run the approximate search evaluator:

```bash
uv run approximate_search_evaluator --config <path-to-config-yaml>
```
This outputs approximate vector search evaluation result which can compared to the previous exact vector search result.

