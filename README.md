# Fin — Personal Finance Manager

A CLI and MCP server for personal finance management, designed from the ground up for use by AI agents and LLMs.

```
fin add -a -450 -d "Swiggy lunch" -c Food
fin report monthly
fin loan whatif --prepay 50000
```

## Features

- **Transactions** — Log income/expenses with auto-categorization by description keywords
- **Accounts** — Multiple accounts (savings, cash, credit card, wallet, investment) with balance tracking
- **Budgets** — Set monthly budgets per category, get spending suggestions based on history
- **Recurring** — Define recurring items (rent, subscriptions, EMIs) and auto-generate transactions
- **Loans** — Full amortization schedules, EMI payments, what-if simulations (prepayment, close-by date)
- **Reports** — Monthly summaries, category breakdowns, committed vs discretionary, cashflow projections, net worth
- **Salary Allocation** — Allocate salary against budgets and loan EMIs
- **SQL Query** — Read-only SQL queries for ad-hoc analysis
- **Reconciliation** — Mark pending transactions as cleared

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/looph0le/fin/main/install.sh | bash
fin add -a 85000 -d "Salary June" --income -c Salary
```

The database (`~/.fin/finances.db`) and default categories are auto-created on first run.

## CLI Usage

### Transactions
```bash
fin add -a -450 -d "Lunch" -c Food                          # expense
fin add -a 85000 -d "Salary" --income -c Salary              # income
fin log '[{"amount":-120,"description":"Uber","category":"Transport"}]'  # bulk
```

### Accounts
```bash
fin accounts add "HDFC Savings" -t savings -i "HDFC Bank"
fin accounts list
fin accounts balance "HDFC Savings" 50000
```

### Budgets
```bash
fin budget set Food 6000
fin budget show -m 2026-07
fin budget suggest
```

### Loans
```bash
fin loan add -n "Personal Loan" -p 350000 -r 16.34 -t 60 -e 8575 -D 10
fin loan pay 1
fin loan whatif 1 --prepay 50000
fin loan whatif 1 --close-by 2028-06
fin loan forecast 1
```

### Reports
```bash
fin report monthly -m 2026-07
fin report categories -m 2026-07
fin report committed -m 2026-07
fin report networth
fin report cashflow -m 2026-07
```

### Other
```bash
fin allocate 85000                                  # salary allocation
fin reconcile                                       # clear pending transactions
fin query "SELECT description, amount FROM transactions WHERE date >= '2026-07-01'"
```

All amounts in rupees — negative for expenses, positive for income.

## MCP Server (AI Agent Integration)

Fin exposes all functionality through a **Model Context Protocol (MCP)** server, enabling any MCP-compatible AI agent (Claude, opencode, etc.) to manage your finances.

```bash
fin-mcp
```

Configure your AI agent with:

```json
{
  "mcpServers": {
    "fin": {
      "command": "fin-mcp"
    }
  }
}
```

### 27 Tools Available

| Tool | Description |
|---|---|
| `add_transaction` | Log a transaction with auto-categorization |
| `bulk_log` | Batch import multiple transactions |
| `list_transactions` | Query transactions with filters |
| `add_account` | Create a new account |
| `list_accounts` | View all accounts and balances |
| `set_account_balance` | Update an account balance |
| `set_budget` | Set or update a monthly budget |
| `show_budgets` | View budgets with spend vs limit |
| `suggest_budgets` | Get budget suggestions from history |
| `add_recurring` | Define a recurring item |
| `list_recurring` | View recurring items |
| `generate_recurring` | Generate recurring transactions for a month |
| `add_loan` | Add a loan with full amortization |
| `list_loans` | View active loans |
| `pay_loan` | Pay the next EMI |
| `loan_forecast` | Full amortization schedule |
| `loan_whatif` | Prepayment or close-by simulation |
| `list_upcoming_emis` | View upcoming EMI payments |
| `monthly_report` | Income/expense summary |
| `category_breakdown` | Expense breakdown by category |
| `networth` | Assets vs liabilities |
| `cashflow` | Spending rate and projections |
| `committed_report` | Committed vs discretionary analysis |
| `allocate_salary` | Allocate salary against budgets |
| `reconcile` | Clear pending transactions |
| `query` | Run read-only SQL |
| `categories` | List all categories |

### 9 Resources

| URI | Description |
|---|---|
| `fin://accounts` | All accounts with balances |
| `fin://categories` | All categories |
| `fin://loans` | Active loans |
| `fin://reports/networth` | Net worth summary |
| `fin://transactions/{year}/{month}` | Monthly transactions |
| `fin://budgets/{year}/{month}` | Monthly budgets |
| `fin://reports/monthly/{year}/{month}` | Monthly report |
| `fin://reports/cashflow/{year}/{month}` | Cashflow analysis |
| `fin://reports/categories/{year}/{month}` | Category breakdown |

## Configuration

Set via environment variables (`.env` in project root):

```env
DATABASE_URL=sqlite:///finances.db          # SQLite (default)
DATABASE_URL=postgresql://user:pass@localhost:5432/finances  # PostgreSQL
```

## Data Model

- **Accounts** — Savings, credit cards, cash, wallets, investments
- **Categories** — Expense/income categories (Food, Transport, Salary, etc.)
- **Transactions** — Dated entries linked to accounts and categories
- **Budgets** — Monthly spending limits per category
- **Recurring Items** — Templates for recurring transactions
- **Loans** — Principal, rate, tenure, EMI with full amortization schedules
- **Loan Payments** — Individual EMI entries with principal/interest breakdown
- **Net Worth Snapshots** — Historical asset/liability records

## Development

```bash
git clone <repo>
cd finances
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check src/
pytest
```

## Design Philosophy

Fin is built for **AI-first personal finance management**. Every operation is available both as a CLI command and an MCP tool. The structured JSON output and consistent data model make it easy for language models to:

- Query and analyze spending patterns
- Set and track budgets
- Run what-if scenarios on loans
- Generate reports on command
- Execute multi-step financial workflows

The MCP server communicates over stdio — no network ports, no authentication needed. Just pipe it to your AI agent and go.
