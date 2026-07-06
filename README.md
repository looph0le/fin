# Fin — Personal Finance MCP Server

An **MCP server** for personal finance management, designed for AI agents and LLMs. Exposes all operations as MCP tools and resources — no CLI, no HTTP, just stdio.

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

### Option 1: Install Script (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/looph0le/fin/main/install.sh | bash
```

### Option 2: Standalone Binary (No Python required)

Download the binary for your platform from [releases](#), or build from source:

```bash
make install
```

This creates `~/.fin/bin/fin` — a single executable with everything bundled.

### Option 3: Python venv (Development)

```bash
git clone <repo> && cd finances
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### MCP Config

Configure your AI agent (Claude, opencode, etc.):

```json
{
  "mcpServers": {
    "fin": {
      "command": "/Users/yourname/.fin/bin/fin"
    }
  }
}
```

The database (`~/.fin/finances.db`) and default categories are auto-created on first run. Use `run_onboarding` to set up accounts, income, recurring expenses, loans, and budgets.

## Onboarding

Fin includes a guided onboarding flow to get you from zero to fully configured in 7 steps:

| Step | What it sets up |
|------|----------------|
| `accounts` | Savings, credit cards, cash, wallets, investments |
| `income` | Salary amount/day and other recurring income |
| `recurring` | Rent, subscriptions, insurance — recurring expenses |
| `loans` | Full amortization schedules for any active loans |
| `budgets` | Monthly spending limits per category |
| `allocation` | Salary distribution rules |
| `catchup` | Backfill recent transactions |

```python
# Check status
run_onboarding()
# Process a step
run_onboarding(step="income", data={"salary_amount": "85000", "salary_day": 1})
```

## 28 Tools Available

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
| `run_onboarding` | Guided setup — accounts, income, budgets, etc. |

## 10 Resources

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
| `fin://onboarding` | Setup progress — what's done and what's next |

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
git clone <repo> && cd finances
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check src/
pytest
```

### Building the Binary

```bash
make build        # Build standalone binary in dist/fin
make install      # Build + copy to ~/.fin/bin/fin
```

## Design Philosophy

Fin is built for **AI-first personal finance management**. Every operation is available as an MCP tool. The structured JSON output and consistent data model make it easy for language models to:

- Query and analyze spending patterns
- Set and track budgets
- Run what-if scenarios on loans
- Generate reports on command
- Execute multi-step financial workflows

The MCP server communicates over stdio — no network ports, no authentication needed. Just pipe it to your AI agent and go.
