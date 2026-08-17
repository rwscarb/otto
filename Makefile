.PHONY: help install install-dev test lint keygen node aggregator clean

PYTHON  ?= python3
VENV    := .venv
BIN     := $(VENV)/bin

# ── Default ───────────────────────────────────────────────────────────────────

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
	     /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ── Install ───────────────────────────────────────────────────────────────────

$(VENV):
	$(PYTHON) -m venv $(VENV)

install: $(VENV) ## Install runtime dependencies
	$(BIN)/pip install -q -e .

install-dev: $(VENV) ## Install dev + runtime dependencies
	$(BIN)/pip install -q -e ".[dev]"

install-sensor: $(VENV) ## Install with seismic-sensor extras (obspy, torch)
	$(BIN)/pip install -q -e ".[dev,sensor]"

# ── Test / lint ───────────────────────────────────────────────────────────────

test: ## Run tests
	$(BIN)/pytest tests/ -v

test-watch: ## Run tests in watch mode (requires pytest-watch)
	$(BIN)/ptw tests/ -v

lint: ## Lint with ruff (install separately: pip install ruff)
	ruff check otto/ tests/

# ── Node tools ────────────────────────────────────────────────────────────────

keygen: $(VENV) ## Generate a new otto node keypair
	$(BIN)/python tools/generate_keypair.py

node: $(VENV) ## Run an otto node (requires OTTO_PRIVKEY, OTTO_PUBKEY, OTTO_LAT, OTTO_LON)
	@test -n "$(OTTO_PRIVKEY)" || (echo "Error: OTTO_PRIVKEY not set"; exit 1)
	@test -n "$(OTTO_PUBKEY)"  || (echo "Error: OTTO_PUBKEY not set";  exit 1)
	$(BIN)/python -c "\
import asyncio, os; \
from otto.node import OttoNode, NodeConfig; \
c = NodeConfig( \
    node_id=os.environ['OTTO_PUBKEY'], \
    privkey=os.environ['OTTO_PRIVKEY'], \
    lat=float(os.environ.get('OTTO_LAT','0')), \
    lon=float(os.environ.get('OTTO_LON','0')), \
    station=os.environ.get('OTTO_STATION'), \
); \
asyncio.run(OttoNode(c).run())"

aggregator: $(VENV) ## Run the otto aggregator (requires OTTO_PRIVKEY, OTTO_PUBKEY)
	@test -n "$(OTTO_PRIVKEY)" || (echo "Error: OTTO_PRIVKEY not set"; exit 1)
	@test -n "$(OTTO_PUBKEY)"  || (echo "Error: OTTO_PUBKEY not set";  exit 1)
	$(BIN)/python -c "\
import asyncio, os; \
from otto.aggregator import OttoAggregator; \
asyncio.run(OttoAggregator( \
    pubkey=os.environ['OTTO_PUBKEY'], \
    privkey=os.environ['OTTO_PRIVKEY'], \
    reputation_path='reputation.json', \
).run())"

leaderboard: $(VENV) ## Show node reputation leaderboard
	$(BIN)/python -c "\
from otto.reputation import ReputationRegistry; \
import json; \
r = ReputationRegistry(path='reputation.json'); \
rows = r.leaderboard(20); \
[print(f'{i+1:>3}. {row.node_id[:16]}...  score={row.score:.2f}  confirmed={row.confirmed}  loc=({row.lat:.2f},{row.lon:.2f})') \
 for i, row in enumerate(rows)] or print('No reputation data yet.')"

# ── Clean ─────────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts and venv
	rm -rf $(VENV) __pycache__ otto/__pycache__ tests/__pycache__ *.egg-info dist build
