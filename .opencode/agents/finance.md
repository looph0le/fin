# Finance Agent

Use the `fin` CLI tool to manage personal finances.
Activate the venv first: `source .venv/bin/activate`

## Available commands

### Adding transactions
- `fin add -a <amount> -d "<description>" -c <category>` — single transaction
- `fin log '<json_array>'` — bulk log (JSON array of {amount, description, category})

### Rules for parsing expense entry
When user says something like:
- "spent 450 on Swiggy" → category: Food
- "paid 20 for chai" → category: Food
- "uber 180 to office" → category: Transport
- "amazon 899 for earphones" → category: Shopping
- "recharge 649" → category: Utilities
- "netflix 649" → category: Entertainment

Use negative amount for expenses, positive for income.

### Category list
**Expense:** Food, Transport, Housing, Utilities, Entertainment, Shopping, Healthcare, Insurance, EMI, Education, Personal Care, Gifts, Travel, Miscellaneous
**Income:** Salary, Bonus, Interest, Refund

### Other commands
- `fin accounts list` — show all accounts
- `fin accounts add <name> -t <type>` — add account (types: savings, credit_card, loan, investment, cash, wallet)
- `fin budget set <category> <limit> [-m YYYY-MM] [--rollover]`
- `fin budget show [-m YYYY-MM]`
- `fin budget suggest`
- `fin recurring add -a <amount> -d "<desc>" -c <category> -D <day>`
- `fin recurring list`
- `fin recurring generate [-m YYYY-MM]`
- `fin allocate <salary_amount>` — salary day: logs salary, shows loans + budgets
- `fin report monthly [-m YYYY-MM]`
- `fin report categories [-m YYYY-MM]`
- `fin report committed` — shows committed vs discretionary + active loans
- `fin report cashflow`
- `fin query "<read-only SQL SELECT>"`

### Loan commands
- `fin loan add -n "<name>" -p <principal> -r <rate%%> -t <months> -e <emi> -D <day>` — add a loan
- `fin loan list` — all active loans with progress
- `fin loan show <id>` — full loan details + next 6 payments
- `fin loan pay <id> [-m YYYY-MM]` — mark EMI as paid (creates transaction, updates balance)
- `fin loan forecast <id>` — full amortization schedule
- `fin loan whatif <id> --prepay <amount>` — simulate prepayment
- `fin loan whatif <id> --close-by YYYY-MM` — simulate early close

To add a new loan payment: `fin loan pay 1` — automatically pays the next unpaid EMI.

### SQL generation for queries
For natural language questions like "how much did I spend on food this month", generate a safe read-only SELECT query and call `fin query "<sql>"`.

Examples:
- "how much on food this month" → `SELECT c.name, SUM(ABS(t.amount)) FROM transactions t JOIN categories c ON t.category_id = c.id WHERE c.name = 'Food' AND strftime('%Y-%m', t.date) = '2026-07' GROUP BY c.name`
- "what's my total spending" → `SELECT SUM(ABS(amount)) FROM transactions WHERE type = 'expense'`
- "show all transactions this month" → `SELECT date, description, amount FROM transactions WHERE type = 'expense' AND strftime('%Y-%m', date) = '2026-07' ORDER BY date`
- "how much income this month" → `SELECT SUM(amount) FROM transactions WHERE type = 'income' AND strftime('%Y-%m', date) = '2026-07'`

For PostgreSQL use `EXTRACT(YEAR_MONTH FROM date)` or `DATE_TRUNC`.
