.PHONY: help install dev test lint clean run run-tray run-voice run-hotkey run-widget

help:
	@echo "AI PC Agent - Available targets:"
	@echo "  make install    - Install system deps and package"
	@echo "  make dev       - Install in development mode"
	@echo "  make test      - Run unit tests"
	@echo "  make lint      - Syntax check all Python files"
	@echo "  make clean     - Remove build artifacts and venv"
	@echo "  make run       - Run CLI mode"
	@echo "  make run-tray  - Run system tray daemon"
	@echo "  make run-voice - Run CLI voice mode"
	@echo "  make run-hotkey - Run hotkey listener only"
	@echo "  make run-widget - Run floating GUI widget"

install:
	@./install.sh

dev:
	python3 -m venv venv
	venv/bin/pip install --upgrade pip setuptools wheel
	venv/bin/pip install -e ".[dev]"

test:
	python3 -m unittest tests.py -v

lint:
	@find . -name "*.py" -not -path "./venv/*" -exec python3 -m py_compile {} \; && echo "All files OK"

clean:
	rm -rf venv
	rm -rf build
	rm -rf dist
	rm -rf *.egg-info
	rm -rf __pycache__
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +

run:
	~/.local/share/ai-pc-agent/run.sh

run-tray:
	~/.local/share/ai-pc-agent/run.sh --tray

run-voice:
	~/.local/share/ai-pc-agent/run.sh --voice

run-hotkey:
	~/.local/share/ai-pc-agent/run.sh --hotkey

run-widget:
	~/.local/share/ai-pc-agent/run.sh --widget
