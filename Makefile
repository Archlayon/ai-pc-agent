.PHONY: help install dev test lint clean run run-tray run-voice run-hotkey run-widget run-hud audit status

help:
	@echo "AI PC Agent - Available targets:"
	@echo "  make install    - Install system deps and package"
	@echo "  make dev       - Install in development mode"
	@echo "  make test      - Run unit tests"
	@echo "  make lint      - Syntax check all Python files"
	@echo "  make clean     - Remove build artifacts and venv"
	@echo "  make run       - Run CLI mode"
	@echo "  make run-hud   - Run Jarvis arc reactor HUD (main mode)"
	@echo "  make run-tray  - Run system tray daemon"
	@echo "  make run-voice - Run CLI voice mode"
	@echo "  make run-hotkey - Run hotkey listener only"
	@echo "  make run-widget - Run floating GUI widget"
	@echo "  make audit     - Run the security self-audit"
	@echo "  make status    - Print current agent status"

install:
	@./install.sh

dev:
	python3 -m venv venv
	venv/bin/pip install --upgrade pip setuptools wheel
	venv/bin/pip install -e ".[dev]"

test:
	python3 -m unittest tests.py -v

# Vendored trees and build artifacts to skip: they are not our code and the
# hindsight checkout alone is ~1GB / 1900 files. compileall matches this with
# re.search against each path, so a trailing "/" anchors the directory name.
LINT_EXCLUDE := (hindsight|\.git|venv|\.venv|node_modules|build|dist|__pycache__|\.mypy_cache|\.pytest_cache|\.ruff_cache|htmlcov)/

lint:
	@python3 -m compileall -q -x '$(LINT_EXCLUDE)' . && echo "All files OK"

clean:
	rm -rf venv build dist *.egg-info
	find . -name "__pycache__" -type d -not -path "./hindsight/*" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "./hindsight/*" -delete 2>/dev/null || true

run:
	./run.sh cli

run-tray:
	./run.sh tray

run-voice:
	./run.sh voice

run-hotkey:
	./run.sh hotkey

run-widget:
	./run.sh widget

run-hud:
	./run.sh hud

audit:
	./run.sh audit

status:
	./run.sh status
