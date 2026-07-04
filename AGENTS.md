# Fin — Personal Finance CLI

## Commands
- Before running `fin` commands, always activate the venv: `source .venv/bin/activate`
- The tool auto-creates the database and seeds categories on first use
- All amounts in rupees (negative = expense, positive = income)
- For bulk entry, pass a JSON array to `fin log`

## MCP Server
- Run `fin-mcp` to start the MCP server (stdio transport)
- Exposes tools for all operations: transactions, accounts, budgets, recurring, loans, reports, net worth, cashflow, salary allocation, SQL query
- Exposes resources: `fin://accounts`, `fin://categories`, `fin://transactions/{year}/{month}`, `fin://budgets/{year}/{month}`, `fin://loans`, `fin://reports/*`
- Configure AI agents to use the MCP server for personal finance management
- All tools accept and return structured JSON

## Default account
If no account is specified, transactions go to "Cash" (auto-created).
