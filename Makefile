SHELL := /bin/bash

UV ?= uv
PYTHON_VERSION ?= 3.11
VENV ?= .venv
PROJECT_NAME ?= BMGateway
CLI_NAME ?= bm-gateway
PACKAGE_NAME ?= bm_gateway
CONFIG_NAME ?= bm-gateway
PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
INSTALL_PATH ?= $(BINDIR)/$(CLI_NAME)
APP_HOME ?= $(HOME)/.local/share/$(CLI_NAME)
APP_VENV ?= $(APP_HOME)/venv
APP_PYTHON ?= $(APP_VENV)/bin/python
CONFIG_DIR ?= $(HOME)/.config/$(CONFIG_NAME)
CONFIG_PATH ?= $(CONFIG_DIR)/config.toml
DEVICES_PATH ?= $(CONFIG_DIR)/devices.toml
PYTHON_SRC ?= python/src
PYTHON_TESTS ?= python/tests
PYTHON_CONFIG ?= python/config
MARKDOWN_FILES := README.md CHANGELOG.md TODO.md AGENTS.md $(shell find docs python home-assistant rpi-setup web -type f -name '*.md' | sort)

.DEFAULT_GOAL := help

.PHONY: help check-deps install-deps sync install install-dev install-link install-config uninstall lint test check run ha-export web-render clean

help: ## Show available targets
	@awk 'BEGIN { FS = ":.*##" } /^[a-zA-Z_-]+:.*##/ { printf "  %-16s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

check-deps: ## Verify required local tools
	@command -v "$(UV)" >/dev/null 2>&1 || { echo "uv not found"; exit 1; }
	@command -v markdownlint >/dev/null 2>&1 || { echo "markdownlint not found"; exit 1; }
	@command -v shellcheck >/dev/null 2>&1 || { echo "shellcheck not found"; exit 1; }
	@mkdir -p "$(BINDIR)" "$(CONFIG_DIR)"
	@if echo "$$PATH" | tr ':' '\n' | grep -Fxq "$(BINDIR)"; then \
		echo "$(BINDIR) is on PATH"; \
	else \
		echo "warning: $(BINDIR) is not on PATH"; \
		echo "add this to your shell profile:"; \
		echo "export PATH=\"$(BINDIR):\$$PATH\""; \
	fi

install-deps: ## Verify required runtime install tools
	@command -v "$(UV)" >/dev/null 2>&1 || { echo "uv not found"; exit 1; }
	@mkdir -p "$(BINDIR)" "$(CONFIG_DIR)"
	@if echo "$$PATH" | tr ':' '\n' | grep -Fxq "$(BINDIR)"; then \
		echo "$(BINDIR) is on PATH"; \
	else \
		echo "warning: $(BINDIR) is not on PATH"; \
		echo "add this to your shell profile:"; \
		echo "export PATH=\"$(BINDIR):\$$PATH\""; \
	fi

$(VENV)/bin/python: pyproject.toml
	@"$(UV)" sync --extra dev

sync: $(VENV)/bin/python ## Sync the project environment

install: install-deps ## Install a standalone user-facing runtime
	@mkdir -p "$(APP_HOME)"
	@"$(UV)" venv --python "$(PYTHON_VERSION)" "$(APP_VENV)"
	@"$(UV)" pip install --python "$(APP_PYTHON)" .
	@$(MAKE) install-link install-config

install-dev: check-deps sync ## Link the dev environment CLI into ~/.local/bin
	@mkdir -p "$(BINDIR)"
	@ln -sf "$(abspath $(VENV)/bin/$(CLI_NAME))" "$(INSTALL_PATH)"
	@$(MAKE) install-config
	@echo "Installed editable dev CLI at $(INSTALL_PATH)"

install-link: ## Link the standalone runtime CLI into ~/.local/bin
	@mkdir -p "$(BINDIR)"
	@ln -sf "$(APP_VENV)/bin/$(CLI_NAME)" "$(INSTALL_PATH)"
	@echo "Installed $(CLI_NAME) -> $(INSTALL_PATH)"

install-config: ## Install the example config file if missing
	@mkdir -p "$(CONFIG_DIR)"
	@if [ ! -f "$(CONFIG_PATH)" ]; then \
		cp "$(PYTHON_CONFIG)/config.toml.example" "$(CONFIG_PATH)"; \
		echo "Installed config template to $(CONFIG_PATH)"; \
	else \
		echo "Config already exists at $(CONFIG_PATH)"; \
	fi
	@if [ ! -f "$(DEVICES_PATH)" ]; then \
		cp "$(PYTHON_CONFIG)/devices.toml.example" "$(DEVICES_PATH)"; \
		echo "Installed devices template to $(DEVICES_PATH)"; \
	else \
		echo "Devices template already exists at $(DEVICES_PATH)"; \
	fi

uninstall: ## Remove the standalone runtime and user-facing symlink
	@rm -f "$(INSTALL_PATH)"
	@rm -rf "$(APP_HOME)"
	@echo "Removed $(INSTALL_PATH)"
	@echo "Removed $(APP_HOME)"

lint: sync ## Run Python, Markdown, and shell quality checks
	@"$(UV)" run ruff check "$(PYTHON_SRC)" "$(PYTHON_TESTS)"
	@"$(UV)" run ruff format --check "$(PYTHON_SRC)" "$(PYTHON_TESTS)"
	@"$(UV)" run mypy "$(PYTHON_SRC)" "$(PYTHON_TESTS)"
	markdownlint --config .markdownlint.json $(MARKDOWN_FILES)
	shellcheck --enable=all scripts/*.sh rpi-setup/scripts/*.sh

test: sync ## Run the test suite
	@"$(UV)" run pytest -q

check: lint test ## Run the full maintainer quality gate

run: sync ## Show the CLI help from the dev environment
	@"$(UV)" run "$(CLI_NAME)" --help

ha-export: sync ## Export Home Assistant discovery examples from the shipped config
	@"$(UV)" run "$(CLI_NAME)" --config python/config/gateway.toml.example ha discovery --output-dir home-assistant/discovery

web-render: sync ## Render the shipped snapshot to HTML
	@"$(UV)" run "$(CLI_NAME)" web render --snapshot-file python/config/data/runtime/latest_snapshot.json

clean: ## Remove local development artifacts
	rm -rf "$(VENV)" .pytest_cache .mypy_cache .ruff_cache build dist "$(PYTHON_SRC)"/*.egg-info *.egg-info
