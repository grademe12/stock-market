# stock-exchange — local development Makefile
# See docs/IMPLEMENTATION_PLAN.md and docs/UBUNTU_SETUP.md

export PATH := $(abspath bin):$(PATH)

CLUSTER_NAME ?= stock-exchange
KIND_CONFIG  ?= deploy/kind/cluster.yaml
NAMESPACE    ?= exchange
MONITORING_NS ?= monitoring
HELM_CHART   ?= deploy/helm/stock-exchange
PROM_RELEASE ?= prometheus
PROM_CHART   ?= prometheus-community/kube-prometheus-stack
PROM_VALUES  ?= deploy/helm/observability/values-prometheus.yaml

.PHONY: help
help: ## Show available targets
	@echo "stock-exchange — make targets"
	@echo ""
	@grep -E '^[a-zA-Z0-9_.-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-22s %s\n", $$1, $$2}'
	@echo ""
	@echo "Quick start: make backend-setup && make backend-run"

# --- Django backend (Stage 0) ---

BACKEND_DIR ?= backend
BACKEND_PYTHON ?= $(BACKEND_DIR)/.venv/bin/python
TRADER_COUNT ?= 100
TRADER_SEED ?= 42
TRADER_STRATEGY ?= noise
ORDER_RATE ?= 10
TEST_DURATION ?= 30s
LOADTEST_ARTIFACTS_DIR ?= .artifacts/loadtest
TRADE_DATE ?=

.PHONY: backend-setup backend-migrate backend-test backend-run participant-runner-test db-up db-status db-migrate import-krx-top100 container-build container-backend-up container-down demo-up demo-seed demo-runner-up demo-logs demo-down load-backend-up load-backend-stats load-steady test run
backend-setup: ## Create backend virtualenv and install dependencies
	python3 -m venv $(BACKEND_DIR)/.venv
	$(BACKEND_PYTHON) -m pip install --upgrade pip
	$(BACKEND_PYTHON) -m pip install -r $(BACKEND_DIR)/requirements.txt

backend-migrate: ## Apply local Django SQLite migrations
	cd $(BACKEND_DIR) && .venv/bin/python manage.py migrate

backend-test: ## Run Django backend tests
	cd $(BACKEND_DIR) && .venv/bin/python manage.py test

backend-run: ## Start Django development server
	cd $(BACKEND_DIR) && .venv/bin/python manage.py runserver

participant-runner-test: ## Run external participant runner tests
	cd participant-runner && PYTHONPATH=../backend python3 -m unittest discover

db-up: ## Start the PostgreSQL container
	docker compose up -d postgres

db-status: ## Show PostgreSQL container status
	docker compose ps postgres

db-migrate: ## Apply Django migrations to PostgreSQL
	docker compose run --rm --entrypoint python backend manage.py migrate

import-krx-top100: ## Import the latest confirmed KOSPI top 100 by trading value
	docker compose run --rm backend python manage.py import_krx_top100 $(if $(TRADE_DATE),--trade-date $(TRADE_DATE),)

container-build: ## Build backend and participant-runner container images
	docker compose build

container-backend-up: ## Start only the packaged backend container
	docker compose up --build backend

container-down: ## Stop and remove project containers (keeps PostgreSQL volume)
	docker compose down

demo-up: ## Start the packaged backend for the reproducible demo
	docker compose up --build -d backend

demo-seed: ## Create deterministic demo trader profiles in the running backend
	docker compose exec -T backend python manage.py seed_traders --strategy $(TRADER_STRATEGY) --count $(TRADER_COUNT) --seed $(TRADER_SEED)

demo-runner-up: ## Start the external participant runner with the local .env settings
	docker compose --profile runner up --build -d participant-runner

demo-logs: ## Follow backend and runner logs for the demo
	docker compose --profile runner logs -f backend participant-runner

demo-down: ## Stop the reproducible demo containers (keeps PostgreSQL volume)
	docker compose --profile runner down

load-backend-up: ## Start backend with execution logs disabled for a load test
	TRADE_EXECUTION_LOG_ENABLED=0 docker compose up --build -d backend

load-backend-stats: ## Print one backend CPU and memory snapshot during a load test
	@backend_id=$$(docker compose ps -q backend); \
	test -n "$$backend_id" || { echo "backend is not running; run make load-backend-up first"; exit 1; }; \
	docker stats --no-stream --format 'cpu={{.CPUPerc}} memory={{.MemUsage}}' "$$backend_id"

load-steady: ## Run the steady order-rate k6 scenario and save its JSON summary
	@mkdir -p $(LOADTEST_ARTIFACTS_DIR)
	@set -eu; \
	backend_id=$$(docker compose ps -q backend); \
	test -n "$$backend_id" || { echo "backend is not running; run make load-backend-up first"; exit 1; }; \
	host_user="$$(id -u):$$(id -g)"; \
	result_file=/results/steady-$(ORDER_RATE)ops-$(TEST_DURATION)-summary.json; \
	TRADE_EXECUTION_LOG_ENABLED=0 docker compose --profile loadtest run --rm --no-deps \
		--user "$$host_user" \
		-e ORDER_RATE=$(ORDER_RATE) \
		-e TEST_DURATION=$(TEST_DURATION) \
		k6 run --quiet --summary-export "$$result_file" /scripts/scenarios/steady.js

test: backend-test ## Alias for backend-test

run: backend-run ## Alias for backend-run

# --- kind cluster (PR-0.1) ---

.PHONY: kind-up
kind-up: ## Create kind cluster (3 nodes)
	@command -v kind >/dev/null 2>&1 || { echo "kind not found — see docs/UBUNTU_SETUP.md"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "docker not found — see docs/UBUNTU_SETUP.md"; exit 1; }
	@if kind get clusters 2>/dev/null | grep -qx '$(CLUSTER_NAME)'; then \
		echo "kind cluster '$(CLUSTER_NAME)' already exists"; \
	else \
		kind create cluster --name $(CLUSTER_NAME) --config $(KIND_CONFIG); \
	fi
	@kubectl config use-context kind-$(CLUSTER_NAME)
	@echo "Cluster ready. Context: kind-$(CLUSTER_NAME)"

.PHONY: kind-down
kind-down: ## Delete kind cluster
	@kind delete cluster --name $(CLUSTER_NAME) 2>/dev/null || true
	@echo "Cluster '$(CLUSTER_NAME)' deleted (if it existed)"

.PHONY: cluster-info
cluster-info: ## Show nodes and current kubectl context
	@kubectl config current-context
	@kubectl get nodes -o wide

# --- helm repos (PR-0.1: add only) ---

.PHONY: deps
deps: ## Add helm repositories (no install)
	@command -v helm >/dev/null 2>&1 || { echo "helm not found — see docs/UBUNTU_SETUP.md"; exit 1; }
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
	helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
	helm repo add redpanda https://charts.redpanda.com 2>/dev/null || true
	helm repo add kedacore https://kedacore.github.io/charts 2>/dev/null || true
	helm repo update
	@echo "Helm repos ready"

# --- observability (PR-0.2) ---

.PHONY: install-observability
install-observability: deps ## Install kube-prometheus-stack + Grafana dashboards
	@command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found"; exit 1; }
	kubectl get namespace $(MONITORING_NS) >/dev/null 2>&1 || kubectl create namespace $(MONITORING_NS)
	helm upgrade --install $(PROM_RELEASE) $(PROM_CHART) \
		-n $(MONITORING_NS) \
		-f $(PROM_VALUES) \
		--wait --timeout 10m
	chmod +x deploy/helm/observability/scripts/apply-dashboards.sh
	MONITORING_NAMESPACE=$(MONITORING_NS) deploy/helm/observability/scripts/apply-dashboards.sh
	@echo "Grafana: kubectl port-forward -n $(MONITORING_NS) svc/prometheus-grafana 3000:80"
	@echo "Login: admin / admin"

.PHONY: grafana-port-forward
grafana-port-forward: ## Port-forward Grafana to localhost:3000
	kubectl port-forward -n $(MONITORING_NS) svc/prometheus-grafana 3000:80

.PHONY: observability-status
observability-status: ## Show monitoring stack pod status
	kubectl get pods -n $(MONITORING_NS)
	kubectl get servicemonitor -A 2>/dev/null | head -20 || true

# --- stubs (implemented in later PRs) ---

.PHONY: helm-install install-infra install-apps tilt-up
helm-install: install-observability ## Alias: observability only until PR-0.3
install-infra install-apps tilt-up:
	@echo "$@: not implemented yet — see docs/IMPLEMENTATION_PLAN.md Phase 0.3+"

.PHONY: test-steady test-symbol-spike test-market-open test-flash-event
test-steady test-symbol-spike test-market-open test-flash-event:
	@echo "$@: not implemented yet — see PR-0.4"

.PHONY: ingest-bootstrap ingest-daily ingest-backfill
ingest-bootstrap ingest-daily ingest-backfill:
	@echo "$@: not implemented yet — see Phase 0.5"
