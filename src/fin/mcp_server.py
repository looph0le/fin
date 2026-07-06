import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from fin.db import engine, get_session
from fin.helpers import (
    amt_str,
    auto_categorize,
    find_category,
    get_emi_category,
    get_or_create_cash_account,
    init_db,
    parse_amount,
    _tx_dict,
)
from fin.models import (
    Account,
    AccountType,
    AllocationRule,
    Budget,
    Category,
    Frequency,
    Loan,
    LoanPayment,
    LoanStatus,
    LoanType,
    PaymentStatus,
    RecurringItem,
    SalaryAllocation,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from fin.services.amortization import generate_schedule, whatif_prepay, whatif_close_by
from fin.services.onboarding import (
    STEP_HANDLERS,
    STEP_KEYS,
    onboarding_status,
)

mcp = FastMCP("Fin - Personal Finance Manager")


# ─── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def add_transaction(
    amount: str,
    description: str,
    category: Optional[str] = None,
    account: Optional[str] = None,
    transaction_date: Optional[str] = None,
    income: bool = False,
    notes: Optional[str] = None,
) -> dict:
    """Add a single transaction. Use negative amount for expense, positive for income. transaction_date format: YYYY-MM-DD"""
    init_db()
    amt = parse_amount(amount)
    tx_type = TransactionType.INCOME if (income or amt > 0) else TransactionType.EXPENSE
    tx_date = date.fromisoformat(transaction_date) if transaction_date else date.today()

    with get_session() as session:
        acct = None
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                return {"error": f"Account '{account}' not found"}
        else:
            acct = get_or_create_cash_account(session)

        cat = None
        if category:
            cat = find_category(session, category)
            if not cat:
                return {"error": f"Category '{category}' not found"}
        else:
            cat = auto_categorize(session, description)

        tx = Transaction(
            account_id=acct.id,
            date=tx_date,
            description=description,
            amount=amt,
            category_id=cat.id if cat else None,
            type=tx_type,
            notes=notes,
        )
        session.add(tx)
        session.commit()

        return {
            "id": tx.id,
            "description": description,
            "amount": str(amt),
            "amount_formatted": amt_str(amt),
            "category": cat.name if cat else "Uncategorized",
            "type": tx_type.value,
            "date": tx_date.isoformat(),
            "account": acct.name,
        }


@mcp.tool()
def bulk_log(
    transactions: list[dict[str, Any]],
    default_account: Optional[str] = None,
) -> dict:
    """Bulk log multiple transactions. Each item: {amount, description, date?, category?, income?, notes?}"""
    init_db()
    with get_session() as session:
        acct = None
        if default_account:
            acct = session.query(Account).filter(Account.name == default_account).first()
            if not acct:
                return {"error": f"Account '{default_account}' not found"}
        else:
            acct = get_or_create_cash_account(session)

        count = 0
        errors = []
        for item in transactions:
            try:
                amt = parse_amount(str(item["amount"]))
                tx_type = TransactionType.INCOME if (item.get("income") or amt > 0) else TransactionType.EXPENSE
                tx_date = date.fromisoformat(item["date"]) if item.get("date") else date.today()

                cat = None
                if item.get("category"):
                    cat = find_category(session, item["category"])
                if not cat:
                    cat = auto_categorize(session, item["description"])

                tx = Transaction(
                    account_id=acct.id,
                    date=tx_date,
                    description=item["description"],
                    amount=amt,
                    category_id=cat.id if cat else None,
                    type=tx_type,
                    notes=item.get("notes"),
                )
                session.add(tx)
                count += 1
            except Exception as e:
                errors.append({"item": item, "error": str(e)})

        session.commit()
        result = {"logged": count, "errors": len(errors)}
        if errors:
            result["error_details"] = errors
        return result


@mcp.tool()
def list_transactions(
    year: Optional[int] = None,
    month: Optional[int] = None,
    account: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List transactions with optional filters."""
    init_db()
    with get_session() as session:
        query = session.query(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc())

        if year and month:
            start = date(year, month, 1)
            end = date(year + month // 12, month % 12 + 1, 1) if month < 12 else date(year + 1, 1, 1)
            query = query.filter(Transaction.date >= start, Transaction.date < end)

        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if acct:
                query = query.filter(Transaction.account_id == acct.id)

        if category:
            cat = find_category(session, category)
            if cat:
                query = query.filter(Transaction.category_id == cat.id)

        transactions = query.limit(limit).all()
        return [_tx_dict(tx) for tx in transactions]


@mcp.tool()
def add_account(
    name: str,
    account_type: str = "savings",
    institution: Optional[str] = None,
) -> dict:
    """Add a new account. Types: savings, credit_card, loan, investment, cash, wallet"""
    init_db()
    with get_session() as session:
        existing = session.query(Account).filter(Account.name == name).first()
        if existing:
            return {"error": f"Account '{name}' already exists"}
        try:
            atype = AccountType(account_type.lower())
        except ValueError:
            return {"error": f"Invalid type: {account_type}. Choose from: savings, credit_card, loan, investment, cash, wallet"}
        acct = Account(name=name, type=atype, institution=institution)
        session.add(acct)
        session.commit()
        return {"id": acct.id, "name": name, "type": atype.value, "institution": institution}


@mcp.tool()
def list_accounts() -> list[dict]:
    """List all accounts with balances."""
    init_db()
    with get_session() as session:
        accounts = session.query(Account).all()
        return [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type.value,
                "institution": a.institution,
                "balance": str(a.balance) if a.balance else "0.00",
                "balance_formatted": amt_str(a.balance) if a.balance else "₹0.00",
                "is_active": a.is_active,
            }
            for a in accounts
        ]


@mcp.tool()
def set_account_balance(
    name: str,
    amount: str,
) -> dict:
    """Set the balance for an account."""
    init_db()
    amt = parse_amount(amount)
    with get_session() as session:
        acct = session.query(Account).filter(Account.name == name).first()
        if not acct:
            return {"error": f"Account '{name}' not found"}
        acct.balance = amt
        session.commit()
        return {"name": name, "balance": str(amt), "balance_formatted": amt_str(amt)}


@mcp.tool()
def set_budget(
    category: str,
    limit: str,
    month: Optional[str] = None,
    rollover: bool = False,
) -> dict:
    """Set a monthly budget for a category. Month format: YYYY-MM"""
    init_db()
    limit_amt = parse_amount(limit)
    budget_month = date.today().replace(day=1)
    if month:
        budget_month = date.fromisoformat(month + "-01")

    with get_session() as session:
        cat = find_category(session, category)
        if not cat:
            return {"error": f"Category '{category}' not found"}
        existing = session.query(Budget).filter(
            Budget.category_id == cat.id, Budget.month == budget_month
        ).first()
        if existing:
            existing.limit_amount = limit_amt
            existing.rollover = rollover
        else:
            bg = Budget(category_id=cat.id, month=budget_month, limit_amount=limit_amt, rollover=rollover)
            session.add(bg)
        session.commit()
        return {
            "category": cat.name,
            "month": budget_month.strftime("%Y-%m"),
            "limit": str(limit_amt),
            "limit_formatted": amt_str(limit_amt),
            "rollover": rollover,
        }


@mcp.tool()
def show_budgets(month: Optional[str] = None) -> list[dict]:
    """Show budgets for a given month. Month format: YYYY-MM (default: current)"""
    init_db()
    budget_month = date.today().replace(day=1)
    if month:
        budget_month = date.fromisoformat(month + "-01")

    with get_session() as session:
        budgets = session.query(Budget).filter(Budget.month == budget_month).all()
        next_month = date(budget_month.year + budget_month.month // 12, budget_month.month % 12 + 1, 1) if budget_month.month < 12 else date(budget_month.year + 1, 1, 1)

        results = []
        for bg in budgets:
            spent_rows = session.query(Transaction).filter(
                Transaction.category_id == bg.category_id,
                Transaction.date >= budget_month,
                Transaction.date < next_month,
                Transaction.type == TransactionType.EXPENSE,
            ).with_entities(Transaction.amount).all()
            total_spent = abs(sum(t.amount for t in spent_rows if t.amount))
            remaining = bg.limit_amount - total_spent
            results.append({
                "category": bg.category.name if bg.category else "Unknown",
                "budget": str(bg.limit_amount),
                "budget_formatted": amt_str(bg.limit_amount),
                "spent": str(total_spent),
                "spent_formatted": amt_str(total_spent),
                "remaining": str(remaining),
                "remaining_formatted": amt_str(remaining),
                "rollover": bg.rollover,
            })
        return results


@mcp.tool()
def suggest_budgets() -> list[dict]:
    """Suggest monthly budgets based on last 3 months average spending + 10% buffer."""
    init_db()
    with get_session() as session:
        today = date.today()
        three_months_ago = today - timedelta(days=90)

        spending = session.query(
            Transaction.category_id,
            Transaction.amount,
        ).filter(
            Transaction.date >= three_months_ago,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        cat_totals: dict[int, dict] = {}
        for row in spending:
            if row.category_id not in cat_totals:
                cat = session.query(Category).filter(Category.id == row.category_id).first()
                cat_totals[row.category_id] = {"name": cat.name if cat else "Unknown", "total": Decimal("0.0")}
            cat_totals[row.category_id]["total"] += abs(row.amount)

        return [
            {
                "category": data["name"],
                "monthly_avg": str(data["total"] / 3),
                "monthly_avg_formatted": amt_str(data["total"] / 3),
                "suggested_budget": str(data["total"] / 3 * Decimal("1.1")),
                "suggested_budget_formatted": amt_str(data["total"] / 3 * Decimal("1.1")),
            }
            for data in cat_totals.values()
        ]


@mcp.tool()
def add_recurring(
    amount: str,
    description: str,
    category: str,
    day: int,
    account: Optional[str] = None,
    frequency: str = "monthly",
) -> dict:
    """Add a recurring expense/income. Frequency: monthly, quarterly, yearly"""
    init_db()
    amt = parse_amount(amount)
    try:
        freq = Frequency(frequency.lower())
    except ValueError:
        return {"error": f"Invalid frequency: {frequency}"}

    with get_session() as session:
        cat = find_category(session, category)
        if not cat:
            return {"error": f"Category '{category}' not found"}
        acct = None
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                return {"error": f"Account '{account}' not found"}
        else:
            acct = get_or_create_cash_account(session)

        item = RecurringItem(
            description=description,
            amount=amt,
            category_id=cat.id,
            account_id=acct.id,
            frequency=freq,
            day_of_month=day,
            is_active=True,
        )
        session.add(item)
        session.commit()
        return {
            "id": item.id,
            "description": description,
            "amount": str(amt),
            "amount_formatted": amt_str(amt),
            "category": cat.name,
            "day": day,
            "frequency": freq.value,
        }


@mcp.tool()
def list_recurring() -> list[dict]:
    """List all active recurring items."""
    init_db()
    with get_session() as session:
        items = session.query(RecurringItem).filter(RecurringItem.is_active).all()
        return [
            {
                "id": item.id,
                "description": item.description,
                "amount": str(item.amount),
                "amount_formatted": amt_str(item.amount),
                "category": item.category.name if item.category else None,
                "day": item.day_of_month,
                "frequency": item.frequency.value if item.frequency else "monthly",
            }
            for item in items
        ]


@mcp.tool()
def generate_recurring(month: Optional[str] = None) -> dict:
    """Generate transactions from recurring items for a given month. Month format: YYYY-MM (default: next)"""
    init_db()
    if month:
        target_month = date.fromisoformat(month + "-01")
    else:
        target_month = date.today().replace(day=1)
        if target_month.month < 12:
            target_month = date(target_month.year, target_month.month + 1, 1)
        else:
            target_month = date(target_month.year + 1, 1, 1)

    with get_session() as session:
        items = session.query(RecurringItem).filter(RecurringItem.is_active).all()
        count = 0
        for item in items:
            try:
                tx_date = target_month.replace(day=min(item.day_of_month, 28))
            except ValueError:
                tx_date = target_month.replace(day=28)

            existing = session.query(Transaction).filter(
                Transaction.description == item.description,
                Transaction.date == tx_date,
                Transaction.account_id == item.account_id,
            ).first()
            if existing:
                continue

            tx = Transaction(
                account_id=item.account_id,
                date=tx_date,
                description=item.description,
                amount=item.amount,
                category_id=item.category_id,
                type=TransactionType.EXPENSE,
                is_recurring=True,
            )
            session.add(tx)
            count += 1
        session.commit()
        return {"month": target_month.strftime("%Y-%m"), "generated": count}


@mcp.tool()
def add_loan(
    name: str,
    principal: str,
    rate: str,
    tenure: int,
    emi: str,
    day: int,
    loan_type: str = "personal",
    account: Optional[str] = None,
    lender: Optional[str] = None,
    disbursement: Optional[str] = None,
    first_emi: Optional[str] = None,
) -> dict:
    """Add a loan with full amortization schedule. Types: personal, home, car, education, credit_card"""
    init_db()
    p = parse_amount(principal)
    r_val = Decimal(rate)
    e = parse_amount(emi)

    try:
        lt = LoanType(loan_type.lower())
    except ValueError:
        return {"error": f"Invalid loan type: {loan_type}"}

    with get_session() as session:
        acct = None
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                return {"error": f"Account '{account}' not found"}
        else:
            acct = get_or_create_cash_account(session)

        emi_cat = get_emi_category(session)
        disb_date = date.fromisoformat(disbursement) if disbursement else None
        first_emi_date = date.fromisoformat(first_emi) if first_emi else date.today().replace(day=min(day, 28))

        loan = Loan(
            name=name,
            type=lt,
            lender=lender,
            account_id=acct.id,
            category_id=emi_cat.id,
            total_principal=p,
            interest_rate=r_val,
            tenure_months=tenure,
            emi_amount=e,
            emi_day=day,
            remaining_principal=p,
            remaining_tenure=tenure,
            disbursement_date=disb_date,
            first_emi_date=first_emi_date,
        )
        session.add(loan)
        session.flush()

        schedule = generate_schedule(p, r_val, e, tenure, first_emi_date, day)
        for entry in schedule:
            payment = LoanPayment(
                loan_id=loan.id,
                sequence=entry["sequence"],
                due_date=entry["due_date"],
                emi_amount=entry["emi_amount"],
                principal_paid=entry["principal_paid"],
                interest_paid=entry["interest_paid"],
                remaining_after=entry["remaining_after"],
            )
            session.add(payment)

        session.commit()
        total_interest = sum(entry["interest_paid"] for entry in schedule)
        return {
            "id": loan.id,
            "name": name,
            "principal": str(p),
            "principal_formatted": amt_str(p),
            "rate": rate,
            "emi": str(e),
            "emi_formatted": amt_str(e),
            "tenure_months": tenure,
            "total_interest": str(total_interest),
            "total_interest_formatted": amt_str(total_interest),
        }


@mcp.tool()
def list_loans() -> list[dict]:
    """List all active loans."""
    init_db()
    with get_session() as session:
        loans = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()
        results = []
        for loan in loans:
            paid_count = session.query(LoanPayment).filter(
                LoanPayment.loan_id == loan.id, LoanPayment.status == PaymentStatus.PAID
            ).count()
            results.append({
                "id": loan.id,
                "name": loan.name,
                "type": loan.type.value,
                "lender": loan.lender,
                "emi": str(loan.emi_amount),
                "emi_formatted": amt_str(loan.emi_amount),
                "emi_day": loan.emi_day,
                "remaining_principal": str(loan.remaining_principal),
                "remaining_principal_formatted": amt_str(loan.remaining_principal),
                "total_principal": str(loan.total_principal),
                "rate": str(loan.interest_rate),
                "tenure_months": loan.tenure_months,
                "remaining_tenure": loan.remaining_tenure,
                "progress": f"{paid_count}/{loan.tenure_months}",
            })
        return results


@mcp.tool()
def pay_loan(
    loan_id: int,
    month: Optional[str] = None,
) -> dict:
    """Pay the next EMI for a loan. Month format: YYYY-MM"""
    init_db()

    with get_session() as session:
        loan = session.query(Loan).filter(Loan.id == loan_id).first()
        if not loan:
            return {"error": f"Loan #{loan_id} not found"}

        payment = session.query(LoanPayment).filter(
            LoanPayment.loan_id == loan.id,
            LoanPayment.status == PaymentStatus.UPCOMING,
        ).order_by(LoanPayment.sequence).first()

        if not payment:
            return {"message": "All payments are already paid!"}

        emi_cat = get_emi_category(session)
        tx = Transaction(
            account_id=loan.account_id,
            date=payment.due_date,
            description=f"{loan.name} EMI #{payment.sequence}",
            amount=-payment.emi_amount,
            category_id=emi_cat.id,
            type=TransactionType.EXPENSE,
            loan_id=loan.id,
        )
        session.add(tx)
        session.flush()

        payment.status = PaymentStatus.PAID
        payment.paid_date = payment.due_date
        payment.transaction_id = tx.id

        loan.remaining_principal = payment.remaining_after
        loan.remaining_tenure -= 1
        session.commit()

        return {
            "loan": loan.name,
            "emi_sequence": payment.sequence,
            "amount": str(payment.emi_amount),
            "amount_formatted": amt_str(payment.emi_amount),
            "principal": str(payment.principal_paid),
            "interest": str(payment.interest_paid),
            "remaining_principal": str(loan.remaining_principal),
            "remaining_tenure": loan.remaining_tenure,
        }


@mcp.tool()
def loan_forecast(loan_id: int) -> dict:
    """Get the full amortization schedule for a loan."""
    init_db()
    with get_session() as session:
        loan = session.query(Loan).filter(Loan.id == loan_id).first()
        if not loan:
            return {"error": f"Loan #{loan_id} not found"}

        payments = session.query(LoanPayment).filter(
            LoanPayment.loan_id == loan.id
        ).order_by(LoanPayment.sequence).all()

        return {
            "loan_name": loan.name,
            "total_principal": str(loan.total_principal),
            "remaining_principal": str(loan.remaining_principal),
            "interest_rate": str(loan.interest_rate),
            "emi": str(loan.emi_amount),
            "schedule": [
                {
                    "sequence": p.sequence,
                    "due_date": p.due_date.isoformat(),
                    "emi": str(p.emi_amount),
                    "principal": str(p.principal_paid),
                    "interest": str(p.interest_paid),
                    "remaining_after": str(p.remaining_after),
                    "status": p.status.value,
                }
                for p in payments
            ],
        }


@mcp.tool()
def loan_whatif(
    loan_id: int,
    prepay: Optional[str] = None,
    close_by: Optional[str] = None,
) -> dict:
    """What-if analysis for a loan. Simulate prepayment or target close date."""
    init_db()
    if not prepay and not close_by:
        return {"error": "Specify 'prepay' or 'close_by'"}

    with get_session() as session:
        loan = session.query(Loan).filter(Loan.id == loan_id).first()
        if not loan:
            return {"error": f"Loan #{loan_id} not found"}

        paid_count = session.query(LoanPayment).filter(
            LoanPayment.loan_id == loan.id, LoanPayment.status == PaymentStatus.PAID
        ).count()

        if prepay:
            amt = parse_amount(prepay)
            result = whatif_prepay(
                loan.remaining_principal,
                loan.interest_rate,
                loan.emi_amount,
                loan.remaining_tenure,
                date.today(),
                loan.emi_day,
                amt,
                paid_count,
            )
            if "error" in result:
                return result

            return {
                "scenario": "prepay",
                "prepayment": str(amt),
                "prepayment_formatted": amt_str(amt),
                "current_emi": str(loan.emi_amount),
                "new_principal": str(result.get("new_principal", 0)),
                "months_saved": result.get("months_saved", 0),
                "interest_saved": str(result.get("interest_saved", 0)),
                "interest_saved_formatted": amt_str(result.get("interest_saved", 0)),
                "loan_cleared": result.get("new_tenure", -1) == 0,
            }

        elif close_by:
            target = date.fromisoformat(close_by + "-01")
            result = whatif_close_by(
                loan.remaining_principal,
                loan.interest_rate,
                loan.emi_amount,
                loan.remaining_tenure,
                date.today(),
                loan.emi_day,
                target,
                paid_count,
            )
            if "error" in result:
                return result

            return {
                "scenario": "close_by",
                "target_date": close_by,
                "current_emi": str(result["current_emi"]),
                "required_emi": str(result["required_emi"]),
                "required_emi_formatted": amt_str(result["required_emi"]),
                "extra_per_month": str(result["extra_per_month"]),
                "months_to_go": result["months_to_go"],
                "interest_saved": str(result["interest_saved"]),
                "interest_saved_formatted": amt_str(result["interest_saved"]),
            }


@mcp.tool()
def monthly_report(year: Optional[int] = None, month: Optional[int] = None) -> dict:
    """Get a monthly income/expense summary."""
    init_db()
    today = date.today()
    y = year or today.year
    m = month or today.month
    start = date(y, m, 1)
    end = date(y + m // 12, m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)

    with get_session() as session:
        income_rows = session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.INCOME,
        ).all()
        expense_rows = session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        total_income = sum(t.amount for t in income_rows)
        total_expense = abs(sum(t.amount for t in expense_rows))
        net = total_income - total_expense

        top_expenses = sorted(
            [
                {
                    "date": t.date.isoformat(),
                    "description": t.description,
                    "category": t.category.name if t.category else "Uncategorized",
                    "amount": str(abs(t.amount)),
                    "amount_formatted": amt_str(abs(t.amount)),
                }
                for t in expense_rows
            ],
            key=lambda x: abs(Decimal(x["amount"])),
            reverse=True,
        )[:10]

        return {
            "month": f"{y}-{m:02d}",
            "total_income": str(total_income),
            "total_income_formatted": amt_str(total_income),
            "total_expenses": str(total_expense),
            "total_expenses_formatted": amt_str(total_expense),
            "net": str(net),
            "net_formatted": amt_str(net),
            "top_expenses": top_expenses,
        }


@mcp.tool()
def category_breakdown(year: Optional[int] = None, month: Optional[int] = None) -> dict:
    """Get expense breakdown by category."""
    init_db()
    today = date.today()
    y = year or today.year
    m = month or today.month
    start = date(y, m, 1)
    end = date(y + m // 12, m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)

    with get_session() as session:
        rows = session.query(
            Category.name,
            Transaction.amount,
        ).join(Category, Transaction.category_id == Category.id).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        cat_totals: dict[str, Decimal] = {}
        for cat_name, amt in rows:
            cat_totals[cat_name] = cat_totals.get(cat_name, Decimal("0.0")) + abs(amt)

        total = sum(cat_totals.values())
        categories = sorted(
            [
                {
                    "category": name,
                    "amount": str(amt),
                    "amount_formatted": amt_str(amt),
                    "percentage": float(amt / total * 100) if total > 0 else 0,
                }
                for name, amt in cat_totals.items()
            ],
            key=lambda x: x["percentage"],
            reverse=True,
        )

        return {
            "month": f"{y}-{m:02d}",
            "total": str(total),
            "total_formatted": amt_str(total),
            "categories": categories,
        }


@mcp.tool()
def networth() -> dict:
    """Calculate net worth (total assets - total liabilities)."""
    init_db()
    with get_session() as session:
        asset_accounts = session.query(Account).filter(
            Account.is_active,
            Account.type.in_([AccountType.SAVINGS, AccountType.CASH, AccountType.INVESTMENT, AccountType.WALLET]),
        ).all()
        loan_liabilities = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()

        assets = [
            {
                "name": a.name,
                "type": a.type.value,
                "balance": str(a.balance) if a.balance else "0.00",
                "balance_formatted": amt_str(a.balance) if a.balance else "₹0.00",
            }
            for a in asset_accounts
            if a.balance and a.balance > 0
        ]
        total_assets = sum(Decimal(a["balance"]) for a in assets)

        liability_list = [
            {
                "name": li.name,
                "remaining": str(li.remaining_principal),
                "remaining_formatted": amt_str(li.remaining_principal),
            }
            for li in loan_liabilities
        ]
        total_liabilities = sum(li.remaining_principal for li in loan_liabilities)

        net = total_assets - total_liabilities

        return {
            "assets": assets,
            "total_assets": str(total_assets),
            "total_assets_formatted": amt_str(total_assets),
            "liabilities": liability_list,
            "total_liabilities": str(total_liabilities),
            "total_liabilities_formatted": amt_str(total_liabilities),
            "net_worth": str(net),
            "net_worth_formatted": amt_str(net),
        }


@mcp.tool()
def cashflow(year: Optional[int] = None, month: Optional[int] = None) -> dict:
    """Analyze monthly cashflow with projections."""
    init_db()
    today = date.today()
    y = year or today.year
    m = month or today.month
    start = date(y, m, 1)
    end = date(y + m // 12, m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)

    with get_session() as session:
        expense_rows = session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        total_spent = abs(sum(t.amount for t in expense_rows))
        days_in_month = (end - start).days
        day_of_month = min((today - start).days + 1, days_in_month)
        daily_rate = total_spent / day_of_month if day_of_month > 0 else Decimal("0.0")
        projected = daily_rate * days_in_month
        remaining_days = days_in_month - day_of_month

        income_rows = session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.INCOME,
        ).all()
        total_income = sum(t.amount for t in income_rows)
        remaining_budget = total_income - total_spent
        daily_remaining = remaining_budget / remaining_days if remaining_days > 0 else Decimal("0.0")

        return {
            "month": f"{y}-{m:02d}",
            "day_of_month": day_of_month,
            "days_in_month": days_in_month,
            "spent_so_far": str(total_spent),
            "spent_so_far_formatted": amt_str(total_spent),
            "daily_average": str(daily_rate),
            "daily_average_formatted": amt_str(daily_rate),
            "projected_total": str(projected),
            "projected_total_formatted": amt_str(projected),
            "days_remaining": remaining_days,
            "total_income": str(total_income),
            "total_income_formatted": amt_str(total_income),
            "remaining_budget": str(remaining_budget),
            "remaining_budget_formatted": amt_str(remaining_budget),
            "daily_remaining_budget": str(daily_remaining),
            "daily_remaining_budget_formatted": amt_str(daily_remaining),
        }


@mcp.tool()
def committed_report(year: Optional[int] = None, month: Optional[int] = None) -> dict:
    """Analyze committed vs discretionary spending."""
    init_db()
    today = date.today()
    y = year or today.year
    m = month or today.month
    start = date(y, m, 1)
    end = date(y + m // 12, m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)

    committed_cats = {"EMI", "Housing", "Insurance", "Education"}

    with get_session() as session:
        income_sum = sum(
            t.amount for t in session.query(Transaction).filter(
                Transaction.date >= start, Transaction.date < end,
                Transaction.type == TransactionType.INCOME,
            ).all()
        )

        all_expenses = session.query(Category.name, Transaction.amount).join(
            Category, Transaction.category_id == Category.id
        ).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        committed = Decimal("0.0")
        discretionary = Decimal("0.0")
        for cat_name, amt in all_expenses:
            if cat_name in committed_cats:
                committed += abs(amt)
            else:
                discretionary += abs(amt)

        income = income_sum if income_sum > 0 else Decimal("1.0")
        loans = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()

        return {
            "month": f"{y}-{m:02d}",
            "income": str(income_sum),
            "income_formatted": amt_str(income_sum),
            "committed": str(committed),
            "committed_formatted": amt_str(committed),
            "committed_pct": float(committed / income * 100),
            "discretionary": str(discretionary),
            "discretionary_formatted": amt_str(discretionary),
            "discretionary_pct": float(discretionary / income * 100),
            "total_expenses": str(committed + discretionary),
            "total_expenses_formatted": amt_str(committed + discretionary),
            "remaining": str(income_sum - committed - discretionary),
            "remaining_formatted": amt_str(income_sum - committed - discretionary),
            "active_loans": [
                {"name": loan.name, "emi": str(loan.emi_amount), "remaining": str(loan.remaining_principal)}
                for loan in loans
            ],
        }


@mcp.tool()
def allocate_salary(
    salary: str,
    salary_date: Optional[str] = None,
    use_rules: bool = False,
) -> dict:
    """Allocate salary against budgets and loans for a month. salary_date format: YYYY-MM-DD. Set use_rules=True to apply saved allocation rules."""
    init_db()
    amt = parse_amount(salary)
    tx_date = date.fromisoformat(salary_date) if salary_date else date.today()

    with get_session() as session:
        budget_month = tx_date.replace(day=1)

        existing_salary = session.query(Transaction).filter(
            Transaction.date >= budget_month,
            Transaction.type == TransactionType.INCOME,
            Transaction.description.like("Salary%"),
        ).first()

        if not existing_salary:
            salary_cat = find_category(session, "Salary")
            if not salary_cat:
                return {"error": "Salary category not found"}
            acct = get_or_create_cash_account(session)
            tx = Transaction(
                account_id=acct.id,
                date=tx_date,
                description=f"Salary - {tx_date.strftime('%B %Y')}",
                amount=amt,
                category_id=salary_cat.id,
                type=TransactionType.INCOME,
            )
            session.add(tx)
            session.commit()
        else:
            amt = existing_salary.amount

        budgets = session.query(Budget).filter(Budget.month == budget_month).all()
        loans = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()

        actions = {"payments_made": [], "recurring_generated": 0}

        if use_rules:
            allocation = session.query(SalaryAllocation).filter(
                SalaryAllocation.is_active,
            ).first()
            if allocation:
                rules = session.query(AllocationRule).filter(
                    AllocationRule.allocation_id == allocation.id,
                ).order_by(AllocationRule.order).all()
                for rule in rules:
                    if rule.allocation_type == "remaining":
                        continue
                recurring_items = session.query(RecurringItem).filter(
                    RecurringItem.is_active,
                ).all()
                for item in recurring_items:
                    try:
                        gen_date = budget_month.replace(day=min(item.day_of_month, 28))
                    except ValueError:
                        gen_date = budget_month.replace(day=28)
                    existing = session.query(Transaction).filter(
                        Transaction.description == item.description,
                        Transaction.date == gen_date,
                        Transaction.account_id == item.account_id,
                    ).first()
                    if not existing:
                        tx_type = TransactionType.INCOME if item.amount > 0 else TransactionType.EXPENSE
                        tx = Transaction(
                            account_id=item.account_id,
                            date=gen_date,
                            description=item.description,
                            amount=item.amount,
                            category_id=item.category_id,
                            type=tx_type,
                            is_recurring=True,
                        )
                        session.add(tx)
                        actions["recurring_generated"] += 1
                for loan in loans:
                    payment = session.query(LoanPayment).filter(
                        LoanPayment.loan_id == loan.id,
                        LoanPayment.status == PaymentStatus.UPCOMING,
                    ).order_by(LoanPayment.sequence).first()
                    if payment:
                        emi_cat = get_emi_category(session)
                        tx = Transaction(
                            account_id=loan.account_id,
                            date=payment.due_date,
                            description=f"{loan.name} EMI #{payment.sequence}",
                            amount=-payment.emi_amount,
                            category_id=emi_cat.id,
                            type=TransactionType.EXPENSE,
                            loan_id=loan.id,
                        )
                        session.add(tx)
                        session.flush()
                        payment.status = PaymentStatus.PAID
                        payment.paid_date = payment.due_date
                        payment.transaction_id = tx.id
                        loan.remaining_principal = payment.remaining_after
                        loan.remaining_tenure -= 1
                        actions["payments_made"].append({
                            "loan": loan.name,
                            "emi_sequence": payment.sequence,
                            "amount": str(payment.emi_amount),
                        })
                session.commit()

        budget_total = Decimal("0.0")
        loan_total = Decimal("0.0")
        allocation_summary = {"loans": [], "budgets": []}

        for loan in loans:
            loan_total += loan.emi_amount
            allocation_summary["loans"].append({
                "name": loan.name,
                "amount": str(loan.emi_amount),
                "amount_formatted": amt_str(loan.emi_amount),
                "remaining_principal": str(loan.remaining_principal),
            })

        for bg in budgets:
            budget_total += bg.limit_amount
            cat_name = bg.category.name if bg.category else "Unknown"
            allocation_summary["budgets"].append({
                "category": cat_name,
                "limit": str(bg.limit_amount),
                "limit_formatted": amt_str(bg.limit_amount),
            })

        total_allocated = loan_total + budget_total
        remaining = amt - total_allocated

        result = {
            "salary": str(amt),
            "salary_formatted": amt_str(amt),
            "month": budget_month.strftime("%Y-%m"),
            "allocation": allocation_summary,
            "loan_total": str(loan_total),
            "loan_total_formatted": amt_str(loan_total),
            "budget_total": str(budget_total),
            "budget_total_formatted": amt_str(budget_total),
            "total_allocated": str(total_allocated),
            "total_allocated_formatted": amt_str(total_allocated),
            "remaining": str(remaining),
            "remaining_formatted": amt_str(remaining),
        }
        if use_rules:
            result["actions"] = actions
        return result


@mcp.tool()
def reconcile(account: Optional[str] = None) -> dict:
    """Mark all pending transactions as cleared."""
    init_db()
    with get_session() as session:
        query = session.query(Transaction).filter(Transaction.status == TransactionStatus.PENDING)
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                return {"error": f"Account '{account}' not found"}
            query = query.filter(Transaction.account_id == acct.id)

        pending = query.all()
        for tx in pending:
            tx.status = TransactionStatus.CLEARED
        session.commit()
        return {"cleared": len(pending), "account": account or "all"}


@mcp.tool()
def query(sql: str) -> dict:
    """Execute a read-only SQL SELECT query against the database."""
    init_db()
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed."}

    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        rows = result.fetchall()
        columns = list(result.keys())
        return {
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in rows],
            "count": len(rows),
        }


@mcp.tool()
def categories() -> list[dict]:
    """List all expense/income categories."""
    init_db()
    with get_session() as session:
        cats = session.query(Category).all()
        return [
            {"id": c.id, "name": c.name, "type": c.type.value}
            for c in cats
        ]


@mcp.tool()
def list_upcoming_emis(limit: int = 20) -> list[dict]:
    """List upcoming unpaid EMI payments across all active loans."""
    init_db()
    with get_session() as session:
        payments = session.query(LoanPayment).join(Loan).filter(
            LoanPayment.status == PaymentStatus.UPCOMING,
            Loan.status == LoanStatus.ACTIVE,
        ).order_by(LoanPayment.due_date).limit(limit).all()

        return [
            {
                "loan_name": p.loan.name,
                "sequence": p.sequence,
                "due_date": p.due_date.isoformat(),
                "emi": str(p.emi_amount),
                "emi_formatted": amt_str(p.emi_amount),
                "principal": str(p.principal_paid),
                "interest": str(p.interest_paid),
                "remaining_after": str(p.remaining_after),
            }
            for p in payments
        ]


@mcp.tool()
def run_onboarding(
    step: Optional[str] = None,
    data: Optional[dict] = None,
) -> dict:
    """Run or query the onboarding flow. Omit step+data to get current status. Steps: accounts, income, recurring, loans, budgets, allocation, catchup"""
    init_db()
    with get_session() as session:
        if step is None:
            return onboarding_status(session)

        step = step.lower()
        if step not in STEP_HANDLERS:
            return {"error": f"Invalid step '{step}'. Choose from: {', '.join(STEP_KEYS)}"}

        handler = STEP_HANDLERS[step]
        result = handler(session, data or {})

        if "error" in result:
            return result

        status = onboarding_status(session)
        result["progress"] = status["overall"]
        return result


# ─── Resources ────────────────────────────────────────────────────────────────


@mcp.resource("fin://accounts")
def accounts_resource() -> str:
    """List of all accounts with balances."""
    return json.dumps(list_accounts(), indent=2)


@mcp.resource("fin://categories")
def categories_resource() -> str:
    """List of all categories."""
    return json.dumps(categories(), indent=2)


@mcp.resource("fin://transactions/{year}/{month}")
def transactions_resource(year: str, month: str) -> str:
    """Transactions for a specific month (YYYY/MM)."""
    return json.dumps(list_transactions(year=int(year), month=int(month), limit=100), indent=2)


@mcp.resource("fin://budgets/{year}/{month}")
def budgets_resource(year: str, month: str) -> str:
    """Budgets for a specific month (YYYY/MM)."""
    return json.dumps(show_budgets(month=f"{year}-{month}"), indent=2)


@mcp.resource("fin://loans")
def loans_resource() -> str:
    """All active loans."""
    return json.dumps(list_loans(), indent=2)


@mcp.resource("fin://reports/monthly/{year}/{month}")
def monthly_report_resource(year: str, month: str) -> str:
    """Monthly income/expense report for a given month (YYYY/MM)."""
    return json.dumps(monthly_report(year=int(year), month=int(month)), indent=2)


@mcp.resource("fin://reports/networth")
def networth_resource() -> str:
    """Current net worth summary."""
    return json.dumps(networth(), indent=2)


@mcp.resource("fin://reports/cashflow/{year}/{month}")
def cashflow_resource(year: str, month: str) -> str:
    """Cashflow analysis for a given month (YYYY/MM)."""
    return json.dumps(cashflow(year=int(year), month=int(month)), indent=2)


@mcp.resource("fin://reports/categories/{year}/{month}")
def categories_report_resource(year: str, month: str) -> str:
    """Category breakdown for a given month (YYYY/MM)."""
    return json.dumps(category_breakdown(year=int(year), month=int(month)), indent=2)


@mcp.resource("fin://onboarding")
def onboarding_resource() -> str:
    """Current onboarding progress (what's set up and what's missing)."""
    init_db()
    with get_session() as session:
        return json.dumps(onboarding_status(session), indent=2, default=str)


# ─── Entry Point ──────────────────────────────────────────────────────────────


def main():
    init_db()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
