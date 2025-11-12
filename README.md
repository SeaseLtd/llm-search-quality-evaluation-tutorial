# Search Quality Evaluation Tutorial
Hey, welcome to our search quality evaluation tutorial!
This tutorial guides you through a complete workflow for evaluating the quality of vector search,
from relevance dataset generation to comparing exact and approximate vector search.

##  What You'll Learn
* How to generate a relevance-labeled dataset for search evaluation.
* How to run and evaluate an embedding model using MTEB with exact vector search.
* How to run an approximate vector search (ANN) and compare its performance against the exact vector search.


## Prerequisites
Before you begin, ensure you have the following tools installed and configured:

* Docker & docker-compose: Used to run search engine.
  * Verify with `docker --version` and `docker-compose --version`
* Python 3.10+: Required for running the toolkit.
  * Verify `python --version` (or `python3 --version`)
* uv: Python package installer. This is used to set up the project's virtual environment. 
  * Install with `pip install uv` (or see official [uv install guide](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer))


## Getting Started
Now that you have the prerequisites installed, let's get the project set up and running.

### Set Up Rated-Ranking-Evaluator project
Set up the project and install the dependencies.

Clone [rated-ranking-evaluator repo](https://github.com/SeaseLtd/rated-ranking-evaluator) to your local machine:
```bash
git clone git@github.com:SeaseLtd/rated-ranking-evaluator.git

rated-ranking-evaluator$ cd rre-tools

```

We use `uv` to create a virtual environment and install all the required packages:

```bash
rre-tools$ uv sync
```

### Run Solr and Index Documents

We use Solr and run dockerized Solr locally. 
Also, we need to index some documents for the search evaluation. 
We use https://github.com/SeaseLtd/llm-search-quality-evaluation-tutorial/data/dataset.json
dataset, (~100k docs) extracted from  [BBC news](https://huggingface.co/datasets/RealTimeData/bbc_news_alltime/viewer/2017-02?row=96])) and `docker-compose.yml`.

Copy the dataset under  `docker-services`:

```bash
rre-tools$ cp $localPath/llm-search-quality-evaluation-tutorial/data/dataset.json  ./docker-services/solr-init/data
```

Run Solr (available at http://localhost:8983/solr) and  index the dataset: 

```bash
rre-tools$ cd docker-services

docker-services$ docker-compose -f docker-compose.solr.yml up --build
```


