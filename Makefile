# stock-exchange — local development Makefile
# See docs/IMPLEMENTATION_PLAN.md and docs/UBUNTU_SETUP.md

export PATH := $(abspath bin):$(PATH)

CLUSTER_NAME ?= stock-exchange
KIND_CONFIG  ?= deploy/kind/cluster.yaml
NAMESPACE    ?= exchange
HELM_CHART   ?= deploy/helm/stock-exchange

.PHONY: help
help: ## Show available targets
	@echo "stock-exchange — make targets"
	@echo ""
	@grep -E '^[a-zA-Z0-9_.-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-22s %s\n", $$1, $$2}'
	@echo ""
	@echo "Quick start: make kind-up && make cluster-info"

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

# --- stubs (implemented in later PRs) ---

.PHONY: helm-install install-infra install-apps tilt-up
helm-install install-infra install-apps tilt-up:
	@echo "$@: not implemented yet — see docs/IMPLEMENTATION_PLAN.md Phase 0.2+"

.PHONY: test-steady test-symbol-spike test-market-open test-flash-event
test-steady test-symbol-spike test-market-open test-flash-event:
	@echo "$@: not implemented yet — see PR-0.4"

.PHONY: ingest-bootstrap ingest-daily ingest-backfill
ingest-bootstrap ingest-daily ingest-backfill:
	@echo "$@: not implemented yet — see Phase 0.5"