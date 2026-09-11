# AGENTS.md — Commands for Kilo/Claude Code

## Development setup

Install dev dependencies (optional if using system Python 3.12+):

```bash
pip install -e ".[dev]"
```

## Commands

### Run tests
```bash
pytest
```

### Lint
```bash
ruff check src/ tests/
```

### Format
```bash
ruff format src/ tests/
```

### Type check
```bash
mypy src/
```

### Run all checks (lint + type check + tests)
```bash
ruff check src/ tests/ && mypy src/ && pytest
```
