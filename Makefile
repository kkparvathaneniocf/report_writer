# ============================================================
# Project configuration
# ============================================================

PYTHON_VERSION ?= 3.14
APP ?= src.negodeck.background.cli


# ============================================================
# Help
# ============================================================

.PHONY: help

help:
	@echo ""
	@echo "Available commands:"
	@echo ""
	@echo "  make install          Install project dependencies"
	@echo "  make hard-install     Force reinstall all dependencies"
	@echo "  make upgrade          Upgrade dependencies"
	@echo "  make lock             Update uv.lock"
	@echo "  make lock-check       Check uv.lock"
	@echo ""
	@echo "  make run              Run the application"
	@echo ""
	@echo "  make test             Run tests"
	@echo "  make test-cov         Run tests with coverage"
	@echo ""
	@echo "  make lint             Run Ruff linter"
	@echo "  make lint-fix         Run Ruff and fix problems"
	@echo "  make format           Format code"
	@echo "  make format-check     Check formatting"
	@echo "  make type-check       Run MyPy"
	@echo ""
	@echo "  make check            Run all quality checks"
	@echo ""
	@echo "  make build            Build Python package"
	@echo "  make clean            Remove temporary files"
	@echo "  make clean-venv       Remove virtual environment"
	@echo ""


# ============================================================
# Python
# ============================================================

.PHONY: python

python:
	uv python install $(PYTHON_VERSION)


# ============================================================
# Installation
# ============================================================

.PHONY: install

install: python
	uv sync


.PHONY: hard-install

hard-install: python
	uv sync --refresh --reinstall


# Reproduce the exact environment from uv.lock.
# Useful for CI/CD or another developer's machine.

.PHONY: install-locked

install-locked: python
	uv sync --locked


# ============================================================
# Dependency management
# ============================================================

.PHONY: lock

lock:
	uv lock


.PHONY: lock-check

lock-check:
	uv lock --check


.PHONY: upgrade

upgrade:
	uv lock --upgrade
	uv sync


# Usage:
#
# make add PKG=requests
#

.PHONY: add

add:
	uv add $(PKG)


# Usage:
#
# make add-dev PKG=pytest-xdist
#

.PHONY: add-dev

add-dev:
	uv add --dev $(PKG)


# ============================================================
# Run
# ============================================================

.PHONY: run

run:
	uv run python -m $(APP)


# ============================================================
# Testing
# ============================================================

.PHONY: test

test:
	uv run pytest


.PHONY: test-cov

test-cov:
	uv run pytest --cov=src --cov-report=term-missing


# ============================================================
# Lint
# ============================================================

.PHONY: lint

lint:
	uv run ruff check .


.PHONY: lint-fix

lint-fix:
	uv run ruff check . --fix


# ============================================================
# Formatting
# ============================================================

.PHONY: format

format:
	uv run ruff format .


.PHONY: format-check

format-check:
	uv run ruff format --check .


# ============================================================
# Type checking
# ============================================================

.PHONY: type-check

type-check:
	uv run mypy src


# ============================================================
# Run all checks
# ============================================================

.PHONY: check

check: format-check lint type-check test


# ============================================================
# Build
# ============================================================

.PHONY: build

build:
	uv build


# ============================================================
# Clean
# ============================================================

.PHONY: clean

clean:
	powershell -NoProfile -Command "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .pytest_cache, .ruff_cache, .mypy_cache"


.PHONY: clean-venv

clean-venv:
	powershell -NoProfile -Command "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .venv"


# ============================================================
# Completely recreate virtual environment
# ============================================================

.PHONY: reset

reset: clean-venv
	uv sync --locked