# Requires uv (https://docs.astral.sh/uv/). On Windows without make, use `python make.py ...`.

PYTHON_VERSION ?= 3.12
MODEL ?= gemma4:26b
INPUT ?= data/raw
OUTPUT ?= output

.PHONY: help install install-locked upgrade lock test lint lint-fix format format-check \
        type-check check demo run inspect ollama-setup poc poc-llm trace build clean clean-venv reset

help:
	@echo "Setup:     install | install-locked | upgrade | lock | reset"
	@echo "Quality:   test | lint | lint-fix | format | format-check | type-check | check"
	@echo "Run:       demo (no LLM) | run [MODEL=$(MODEL)] | inspect | ollama-setup"
	@echo "PDF POC:   poc (no LLM) | poc-llm [MODEL=$(MODEL)] | trace SLOT=fabric_batch"
	@echo "Misc:      build | clean | clean-venv"

# ---------------------------------------------------------------- setup

install:
	uv sync --python $(PYTHON_VERSION) --extra dev

# Exact environment from uv.lock (CI / other machines).
install-locked:
	uv sync --python $(PYTHON_VERSION) --extra dev --locked

upgrade:
	uv lock --upgrade
	uv sync --extra dev

lock:
	uv lock

reset: clean-venv install-locked

# ---------------------------------------------------------------- quality

test:
	uv run pytest -q

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

type-check:
	uv run mypy src

check: format-check lint type-check test

# ---------------------------------------------------------------- run

# Deterministic fiber calculation on the bundled example, no Ollama needed.
demo:
	mkdir -p $(INPUT)
	cp examples/TR26_C0143_fiber.csv $(INPUT)/
	uv run lab-report run --skip-llm --input-dir $(INPUT) --output-dir $(OUTPUT)

run:
	uv run lab-report run --model $(MODEL) --input-dir $(INPUT) --output-dir $(OUTPUT)

inspect:
	uv run lab-report inspect --input-dir $(INPUT)

ollama-setup:
	uv run python make.py ollama-pull --model $(MODEL)

# PDF -> DOCX pipeline on generated dummy data (see README "PDF pipeline POC").
TR ?= TR26_C0143

poc:
	uv run lab-report make-dummy --folder data/raw/$(TR)
	uv run lab-report build-template
	uv run lab-report report --no-llm --input-dir data/raw/$(TR) --output-dir output/$(TR)

poc-llm:
	uv run lab-report make-dummy --folder data/raw/$(TR)
	uv run lab-report build-template
	uv run lab-report report --model $(MODEL) --input-dir data/raw/$(TR) --output-dir output/$(TR)

trace:
	uv run lab-report trace "$(SLOT)" --output-dir output/$(TR)

# ---------------------------------------------------------------- misc

build:
	uv build

clean:
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -not -path "./.venv/*" -prune -exec rm -rf {} +

clean-venv:
	rm -rf .venv
