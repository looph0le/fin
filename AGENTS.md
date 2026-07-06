# Fin — Personal Finance MCP Server

## Architecture
- **`mcp_server.py`** is the sole interface — 28 MCP tools + 10 resources
- Shared core: `helpers.py`, `db.py`, `models.py`, `seed.py`, `services/amortization.py`, `services/onboarding.py`
- All amounts in rupees (negative = expense, positive = income)
- Database auto-created + categories seeded on first run

## Commands
- Activate venv: `source .venv/bin/activate`
- Run MCP server: `fin` (stdio transport, venv or standalone binary)
- Lint: `ruff check src/`
- Tests: `pytest`
- Build binary: `make build` or `make install` (copies to ~/.fin/bin/fin-bin)

## Config
- DB: SQLite at `~/.fin/finances.db` by default
- PostgreSQL via `DATABASE_URL` env var
- .env file in project root is auto-loaded by `python-dotenv`

## Conventions
- `ruff` line-length: 100
- SQLAlchemy ORM with manual `session.query()` (no async)
- Dates: Python `datetime.date`, stored as SQLite `DATE`
- Currency: `Decimal("12.34")`, stored as `Numeric(12, 2)`
- Auto-categorization via keyword matching in `auto_categorize()`

## MCP Server Details
- Uses `mcp` (FastMCP) with `transport="stdio"` only
- Tools return plain dicts/lists (FastMCP serializes to JSON)
- Resources at `fin://` URIs for AI agent context
- Default account is "Cash" (auto-created)

## ⚠️ No CLI
The Typer CLI has been removed. This project is MCP-only.
Do NOT add CLI dependencies (typer, rich, click) back.
