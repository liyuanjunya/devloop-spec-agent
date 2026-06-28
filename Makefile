.PHONY: install test test-unit test-integration lint fmt typecheck clean coverage run-cli

# Default: show help
help:
	@echo "DevLoop common tasks:"
	@echo "  make install         Install in editable mode with dev+test extras"
	@echo "  make test            Run full test suite"
	@echo "  make test-unit       Run only unit tests"
	@echo "  make test-integration Run only integration tests"
	@echo "  make lint            Run ruff lint"
	@echo "  make fmt             Auto-format with ruff"
	@echo "  make typecheck       Run mypy"
	@echo "  make coverage        Run tests with coverage report"
	@echo "  make clean           Remove caches and build artifacts"

install:
	pip install -e ".[test,dev]"

test:
	ANTHROPIC_API_KEY=mock OPENAI_API_KEY=mock PYTHONPATH=. pytest tests --tb=short

test-unit:
	ANTHROPIC_API_KEY=mock OPENAI_API_KEY=mock PYTHONPATH=. pytest tests/unit --tb=short

test-integration:
	ANTHROPIC_API_KEY=mock OPENAI_API_KEY=mock PYTHONPATH=. pytest tests/integration --tb=short

lint:
	ruff check devloop tests

fmt:
	ruff format devloop tests

typecheck:
	mypy devloop

coverage:
	ANTHROPIC_API_KEY=mock OPENAI_API_KEY=mock PYTHONPATH=. pytest tests --cov=devloop --cov-report=term --cov-report=html

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
