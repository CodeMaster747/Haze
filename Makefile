# Haze -- canonical entrypoints. CI runs exactly these targets, so a green
# `make check` locally means a green build on GitHub.

PY      := .venv/bin/python
PIP     := .venv/bin/pip
WEBUI   := agent/src/haze/webui

.DEFAULT_GOAL := help
.PHONY: help setup check check-agent check-web build build-web build-demo verify-wheel verify-demo-bundle run devnet clean

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the venv and install both toolchains
	python3.12 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e "./agent[dev]"
	cd web && npm ci

# --- verification -----------------------------------------------------------

check: check-agent check-web  ## Everything CI runs

check-agent:  ## ruff + mypy strict + pytest
	$(PY) -m ruff check agent
# mypy MUST run from agent/. It resolves its config relative to the working
# directory, so `mypy agent/src/haze` from here finds no pyproject.toml and
# silently runs in DEFAULT mode -- reporting success while checking almost
# nothing. Verify with `mypy src/haze -v | grep 'Config File'`.
	cd agent && ../$(PY) -m mypy src/haze
	$(PY) -m pytest agent/tests -q

check-web:  ## eslint + tsc + vitest
	cd web && npx eslint . && npx tsc --noEmit && npx vitest run --passWithNoTests

# --- build ------------------------------------------------------------------

build: build-web  ## Build the dashboard into the agent package

build-web:  ## Build web/ and copy it into the Python package
	cd web && npm run build
	rm -rf $(WEBUI)
	cp -R web/dist $(WEBUI)
	@echo "  dashboard -> $(WEBUI) ($$(du -sh $(WEBUI) | cut -f1))"

build-demo:  ## Build the Firebase-hosted demo bundle (simulated cluster, no backend)
	cd web && npm run build:demo

verify-demo-bundle: build-demo  ## Prove the hosted bundle cannot reach a local agent
	@$(PY) scripts/verify_demo_bundle.py

verify-wheel: build-web  ## Prove the wheel actually contains the dashboard
	@rm -rf dist && $(PY) -m pip wheel --no-deps -q -w dist ./agent
	@$(PY) -c "import zipfile,glob,sys; \
	  w=glob.glob('dist/haze_agent-*.whl')[0]; \
	  n=[x for x in zipfile.ZipFile(w).namelist() if 'webui/index.html' in x]; \
	  print('  wheel:', w.split('/')[-1]); \
	  print('  webui/index.html present:', bool(n)); \
	  sys.exit(0 if n else 1)"

# --- running ----------------------------------------------------------------

run:  ## Start an agent on this machine
	$(PY) -m haze up

devnet:  ## Start 4 agents with simulated hardware profiles (M2)
	$(PY) -m haze devnet up -n 4 --open

clean:
	rm -rf $(WEBUI) web/dist dist .pytest_cache .ruff_cache .mypy_cache
