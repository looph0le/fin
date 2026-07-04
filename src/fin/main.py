import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from sqlalchemy import text
from sqlalchemy.orm import Session

from fin.db import engine, get_session
from fin.models import (
    Base,
    Account,
    AccountType,
    Budget,
    Category,
    CategoryType,
    Frequency,
    Loan,
    LoanPayment,
    LoanStatus,
    LoanType,
    PaymentStatus,
    RecurringItem,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from fin.seed import seed_categories
from fin.services.amortization import generate_schedule, whatif_prepay, whatif_close_by

app = typer.Typer()
console = Console()


def init_db():
    Base.metadata.create_all(engine)
    with get_session() as session:
        seed_categories(session)


def parse_amount(value: str) -> Decimal:
    return Decimal(value.replace("₹", "").replace(",", "").replace(" ", "").strip())


def get_or_create_cash_account(session: Session) -> Account:
    acct = session.query(Account).filter(Account.name == "Cash").first()
    if not acct:
        acct = Account(name="Cash", type=AccountType.CASH)
        session.add(acct)
        session.commit()
    return acct


def find_category(session: Session, name: str) -> Optional[Category]:
    return session.query(Category).filter(Category.name.ilike(name)).first()


def auto_categorize(session: Session, description: str) -> Category:
    desc_lower = description.lower()
    keywords = {
        "Food": ["swiggy", "zomato", "chai", "tea", "coffee", "lunch", "dinner", "breakfast", "momos", "food", "restaurant", "pizza", "burger", "grocery", "milk", "bread", "eat", "snack"],
        "Transport": ["uber", "ola", "cab", "auto", "rickshaw", "bus", "metro", "train", "petrol", "fuel", "diesel", "parking", "toll"],
        "Entertainment": ["netflix", "prime", "hotstar", "spotify", "movie", "cinema", "theatre", "game", "pubg", "youtube"],
        "Shopping": ["amazon", "flipkart", "myntra", "meesho", "earphone", "clothes", "shoe", "gadget"],
        "Utilities": ["electricity", "water", "bill", "recharge", "phone", "mobile", "internet", "broadband", "wifi"],
        "EMI": ["emi", "loan", "credit card"],
        "Salary": ["salary", "sal"],
    }
    for cat_name, kw_list in keywords.items():
        if any(kw in desc_lower for kw in kw_list):
            cat = find_category(session, cat_name)
            if cat:
                return cat
    misc = find_category(session, "Miscellaneous")
    if misc:
        return misc
    cat = Category(name="Miscellaneous", type=CategoryType.EXPENSE)
    session.add(cat)
    session.commit()
    return cat


def format_currency(amount: Decimal) -> str:
    sign = ""
    if amount < 0:
        sign = "-"
        amount = -amount
    return f"{sign}₹{amount:,.2f}"


# ─── Accounts ────────────────────────────────────────────────────────────────

accounts_app = typer.Typer()
app.add_typer(accounts_app, name="accounts", help="Manage accounts")


@accounts_app.command("add")
def accounts_add(
    name: str = typer.Argument(..., help="Account name"),
    account_type: str = typer.Option("savings", "-t", "--type", help="Account type: savings, credit_card, loan, investment, cash, wallet"),
    institution: str = typer.Option(None, "-i", "--institution", help="Bank/institution name"),
):
    init_db()
    with get_session() as session:
        existing = session.query(Account).filter(Account.name == name).first()
        if existing:
            rprint(f"[red]Account '{name}' already exists.[/red]")
            raise typer.Exit(1)
        try:
            atype = AccountType(account_type.lower())
        except ValueError:
            rprint(f"[red]Invalid type: {account_type}. Choose from: savings, credit_card, loan, investment, cash, wallet[/red]")
            raise typer.Exit(1)
        acct = Account(name=name, type=atype, institution=institution)
        session.add(acct)
        session.commit()
        rprint(f"[green]✓[/green] Added account: {name} ({atype.value})")


@accounts_app.command("list")
def accounts_list():
    init_db()
    with get_session() as session:
        accounts = session.query(Account).all()
        if not accounts:
            rprint("[yellow]No accounts yet. Use 'fin accounts add' to create one.[/yellow]")
            return
        table = Table(title="Accounts")
        table.add_column("ID", style="dim")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Institution")
        table.add_column("Balance")
        table.add_column("Active")
        for a in accounts:
            bal = format_currency(a.balance) if a.balance else "₹0.00"
            table.add_row(str(a.id), a.name, a.type.value, a.institution or "", bal, "✓" if a.is_active else "✗")
        console.print(table)


@accounts_app.command("balance")
def accounts_balance(
    name: str = typer.Argument(..., help="Account name"),
    amount: str = typer.Argument(None, help="New balance (omit to just view)"),
):
    init_db()
    with get_session() as session:
        acct = session.query(Account).filter(Account.name == name).first()
        if not acct:
            rprint(f"[red]Account '{name}' not found.[/red]")
            raise typer.Exit(1)
        if amount:
            amt = parse_amount(amount)
            acct.balance = amt
            session.commit()
            rprint(f"[green]✓[/green] {name} balance set to {format_currency(amt)}")
        else:
            rprint(f"{name}: {format_currency(acct.balance) if acct.balance else '₹0.00'}")


# ─── Add Transaction ─────────────────────────────────────────────────────────

@app.command()
def add(
    amount: str = typer.Option(..., "-a", "--amount", help="Amount (-450 for expense, 85000 for income)"),
    description: str = typer.Option(..., "-d", "--desc", help="Transaction description"),
    category: str = typer.Option(None, "-c", "--category", help="Category name"),
    account: str = typer.Option(None, "--account", help="Account name (default: Cash)"),
    tx_date: str = typer.Option(None, "--date", metavar="YYYY-MM-DD", help="Date (default: today)"),
    income_flag: bool = typer.Option(False, "--income", help="Force mark as income"),
    tx_notes: str = typer.Option(None, "-n", "--notes", help="Optional notes"),
):
    init_db()
    amt = parse_amount(amount)
    if income_flag or amt > 0:
        tx_type = TransactionType.INCOME
    else:
        tx_type = TransactionType.EXPENSE
    tx_date_parsed = date.fromisoformat(tx_date) if tx_date else date.today()

    with get_session() as session:
        acct = None
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                rprint(f"[red]Account '{account}' not found.[/red]")
                raise typer.Exit(1)
        else:
            acct = get_or_create_cash_account(session)

        cat = None
        if category:
            cat = find_category(session, category)
            if not cat:
                rprint(f"[red]Category '{category}' not found.[/red]")
                raise typer.Exit(1)
        else:
            cat = auto_categorize(session, description)

        tx = Transaction(
            account_id=acct.id,
            date=tx_date_parsed,
            description=description,
            amount=amt,
            category_id=cat.id if cat else None,
            type=tx_type,
            notes=tx_notes,
        )
        session.add(tx)
        session.commit()

        cat_name = cat.name if cat else "Uncategorized"
        icon = "📈" if tx_type == TransactionType.INCOME else "📉"
        rprint(f"{icon} [green]Added:[/green] {description} [yellow]{format_currency(amt)}[/yellow] ({cat_name})")


# ─── Bulk Log ────────────────────────────────────────────────────────────────

@app.command()
def log(
    transactions_json: str = typer.Argument(None, help="JSON array of transactions, or omit to read from stdin"),
    account: str = typer.Option(None, "-a", "--account", help="Default account for all transactions"),
):
    init_db()
    if transactions_json:
        data = json.loads(transactions_json)
    else:
        data = json.loads(sys.stdin.read())

    with get_session() as session:
        acct = None
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                rprint(f"[red]Account '{account}' not found.[/red]")
                raise typer.Exit(1)
        else:
            acct = get_or_create_cash_account(session)

        count = 0
        for item in data:
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

        session.commit()
        rprint(f"[green]✓[/green] Logged {count} transactions")


# ─── Budget ──────────────────────────────────────────────────────────────────

budget_app = typer.Typer()
app.add_typer(budget_app, name="budget", help="Manage budgets")


@budget_app.command("set")
def budget_set(
    category: str = typer.Argument(..., help="Category name"),
    limit: str = typer.Argument(..., help="Monthly budget limit"),
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Month (default: current)"),
    rollover: bool = typer.Option(False, "--rollover", help="Allow unspent to roll over to next month"),
):
    init_db()
    limit_amt = parse_amount(limit)
    budget_month = date.today().replace(day=1)
    if month:
        budget_month = date.fromisoformat(month + "-01")

    with get_session() as session:
        cat = find_category(session, category)
        if not cat:
            rprint(f"[red]Category '{category}' not found.[/red]")
            raise typer.Exit(1)
        existing = session.query(Budget).filter(
            Budget.category_id == cat.id, Budget.month == budget_month
        ).first()
        if existing:
            existing.limit_amount = limit_amt
            existing.rollover = rollover
            rprint(f"[green]✓[/green] Updated budget for {cat.name}: {format_currency(limit_amt)}")
        else:
            bg = Budget(category_id=cat.id, month=budget_month, limit_amount=limit_amt, rollover=rollover)
            session.add(bg)
            rprint(f"[green]✓[/green] Set budget for {cat.name}: {format_currency(limit_amt)}")
        session.commit()


@budget_app.command("show")
def budget_show(
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Month (default: current)"),
):
    init_db()
    budget_month = date.today().replace(day=1)
    if month:
        budget_month = date.fromisoformat(month + "-01")

    with get_session() as session:
        budgets = session.query(Budget).filter(Budget.month == budget_month).all()
        if not budgets:
            rprint("[yellow]No budgets set for this month. Use 'fin budget set'.[/yellow]")
            return

        next_month = date(budget_month.year + budget_month.month // 12, budget_month.month % 12 + 1, 1) if budget_month.month < 12 else date(budget_month.year + 1, 1, 1)
        table = Table(title=f"Budgets - {budget_month.strftime('%B %Y')}")
        table.add_column("Category")
        table.add_column("Budget")
        table.add_column("Spent")
        table.add_column("Remaining")
        table.add_column("Rollover")

        for bg in budgets:
            spent = session.query(Transaction).filter(
                Transaction.category_id == bg.category_id,
                Transaction.date >= budget_month,
                Transaction.date < next_month,
                Transaction.type == TransactionType.EXPENSE,
            ).with_entities(Transaction.amount).all()
            total_spent = sum(t.amount for t in spent if t.amount) * -1

            remaining = bg.limit_amount - total_spent
            status = "[green]" if remaining >= 0 else "[red]"
            table.add_row(
                bg.category.name,
                format_currency(bg.limit_amount),
                format_currency(total_spent),
                f"{status}{format_currency(remaining)}[/]",
                "✓" if bg.rollover else "✗",
            )
        console.print(table)


@budget_app.command("suggest")
def budget_suggest():
    init_db()
    with get_session() as session:
        rprint("[yellow]Analyzing last 3 months...[/yellow]")
        today = date.today()
        three_months_ago = today - timedelta(days=90)

        results = session.query(
            Category.name,
            Transaction.category_id,
        ).join(Category, Transaction.category_id == Category.id).filter(
            Transaction.date >= three_months_ago,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        cat_spending = {}
        for row in results:
            if row.category_id not in cat_spending:
                cat_spending[row.category_id] = {"name": row.name, "total": Decimal("0.0"), "count": 0}
            cat_spending[row.category_id]["count"] += 1

        spending = session.query(
            Transaction.category_id,
            Transaction.amount,
        ).filter(
            Transaction.date >= three_months_ago,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        cat_totals = {}
        for row in spending:
            if row.category_id not in cat_totals:
                cat_totals[row.category_id] = {"total": Decimal("0.0"), "count": 0}
            cat_totals[row.category_id]["total"] += abs(row.amount)
            cat_totals[row.category_id]["count"] += 1

        table = Table(title="Suggested Monthly Budgets (3mo avg)")
        table.add_column("Category")
        table.add_column("Monthly Avg")
        table.add_column("Suggested Budget")

        for cat_id, data in cat_totals.items():
            cat = session.query(Category).filter(Category.id == cat_id).first()
            monthly_avg = data["total"] / 3
            suggested = monthly_avg * Decimal("1.1")  # 10% buffer
            table.add_row(
                cat.name if cat else "Unknown",
                format_currency(monthly_avg),
                format_currency(suggested),
            )
        console.print(table)


# ─── Recurring ───────────────────────────────────────────────────────────────

recurring_app = typer.Typer()
app.add_typer(recurring_app, name="recurring", help="Manage recurring items (EMIs, rent, subs)")


@recurring_app.command("add")
def recurring_add(
    amount: str = typer.Option(..., "-a", "--amount", help="Amount (-649 for expense)"),
    description: str = typer.Option(..., "-d", "--desc", help="Description"),
    category: str = typer.Option(..., "-c", "--category", help="Category name"),
    day: int = typer.Option(..., "-D", "--day", help="Day of month (1-31)"),
    account: str = typer.Option(None, "--account", help="Account name (default: Cash)"),
    frequency: str = typer.Option("monthly", "-f", "--frequency", help="monthly, quarterly, yearly"),
):
    init_db()
    amt = parse_amount(amount)
    try:
        freq = Frequency(frequency.lower())
    except ValueError:
        rprint(f"[red]Invalid frequency: {frequency}[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        cat = find_category(session, category)
        if not cat:
            rprint(f"[red]Category '{category}' not found.[/red]")
            raise typer.Exit(1)
        acct = None
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                rprint(f"[red]Account '{account}' not found.[/red]")
                raise typer.Exit(1)
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
        rprint(f"[green]✓[/green] Added recurring: {description} {format_currency(amt)} on day {day}")


@recurring_app.command("list")
def recurring_list():
    init_db()
    with get_session() as session:
        items = session.query(RecurringItem).filter(RecurringItem.is_active == True).all()
        if not items:
            rprint("[yellow]No recurring items. Use 'fin recurring add'.[/yellow]")
            return
        table = Table(title="Recurring Items")
        table.add_column("ID")
        table.add_column("Description")
        table.add_column("Amount")
        table.add_column("Category")
        table.add_column("Day")
        table.add_column("Frequency")
        for item in items:
            cat_name = item.category.name if item.category else ""
            table.add_row(str(item.id), item.description, format_currency(item.amount), cat_name, str(item.day_of_month), item.frequency.value)
        console.print(table)


@recurring_app.command("generate")
def recurring_generate(
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Month (default: next)"),
):
    init_db()
    target_month = date.today().replace(day=1)
    if month:
        target_month = date.fromisoformat(month + "-01")
    else:
        target_month = date(target_month.year + target_month.month // 12, target_month.month % 12 + 1, 1) if target_month.month < 12 else date(target_month.year + 1, 1, 1)

    with get_session() as session:
        items = session.query(RecurringItem).filter(RecurringItem.is_active == True).all()
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
        rprint(f"[green]✓[/green] Generated {count} recurring transactions for {target_month.strftime('%B %Y')}")


# ─── Loans ───────────────────────────────────────────────────────────────────

loan_app = typer.Typer()
app.add_typer(loan_app, name="loan", help="Manage loans and EMIs")


def get_emi_category(session: Session) -> Category:
    cat = find_category(session, "EMI")
    if not cat:
        cat = Category(name="EMI", type=CategoryType.EXPENSE)
        session.add(cat)
        session.commit()
    return cat


@loan_app.command("add")
def loan_add(
    name: str = typer.Option(..., "-n", "--name", help="Loan name"),
    principal: str = typer.Option(..., "-p", "--principal", help="Total outstanding principal"),
    rate: str = typer.Option(..., "-r", "--rate", help="Annual interest rate (e.g. 16.34)"),
    tenure: int = typer.Option(..., "-t", "--tenure", help="Remaining tenure in months"),
    emi: str = typer.Option(..., "-e", "--emi", help="Monthly EMI amount"),
    day: int = typer.Option(..., "-D", "--day", help="EMI day of month (1-31)"),
    loan_type: str = typer.Option("personal", "-T", "--type", help="personal, home, car, education, credit_card"),
    account: str = typer.Option(None, "--account", help="Account name (default: Cash)"),
    lender: str = typer.Option(None, "-l", "--lender", help="Lender name"),
    disbursement: str = typer.Option(None, "--disbursed", metavar="YYYY-MM-DD", help="Disbursement date"),
    first_emi: str = typer.Option(None, "--first-emi", metavar="YYYY-MM-DD", help="First EMI date"),
):
    init_db()
    p = parse_amount(principal)
    r_val = Decimal(rate)
    e = parse_amount(emi)

    try:
        lt = LoanType(loan_type.lower())
    except ValueError:
        rprint(f"[red]Invalid loan type: {loan_type}[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        acct = None
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                rprint(f"[red]Account '{account}' not found.[/red]")
                raise typer.Exit(1)
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
        rprint(f"[green]✓[/green] Added loan: {name}")
        rprint(f"  Principal: {format_currency(p)} @ {rate}%")
        rprint(f"  EMI: {format_currency(e)} x {tenure} months")
        rprint(f"  Total interest payable: {format_currency(total_interest)}")


@loan_app.command("list")
def loan_list():
    init_db()
    with get_session() as session:
        loans = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()
        if not loans:
            rprint("[yellow]No active loans.[/yellow]")
            return

        table = Table(title="Active Loans")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("EMI")
        table.add_column("Day")
        table.add_column("Remaining")
        table.add_column("Progress")

        for loan in loans:
            paid_count = session.query(LoanPayment).filter(
                LoanPayment.loan_id == loan.id, LoanPayment.status == PaymentStatus.PAID
            ).count()
            pct = paid_count / loan.tenure_months * 100 if loan.tenure_months > 0 else 0
            table.add_row(
                str(loan.id),
                loan.name,
                loan.type.value,
                format_currency(loan.emi_amount),
                str(loan.emi_day),
                format_currency(loan.remaining_principal),
                f"{paid_count}/{loan.tenure_months} ({pct:.0f}%)",
            )
        console.print(table)


@loan_app.command("show")
def loan_show(
    loan_id: int = typer.Argument(..., help="Loan ID"),
):
    init_db()
    with get_session() as session:
        loan = session.query(Loan).filter(Loan.id == loan_id).first()
        if not loan:
            rprint("[red]Loan not found.[/red]")
            raise typer.Exit(1)

        paid_payments = session.query(LoanPayment).filter(
            LoanPayment.loan_id == loan.id, LoanPayment.status == PaymentStatus.PAID
        ).all()
        upcoming = session.query(LoanPayment).filter(
            LoanPayment.loan_id == loan.id, LoanPayment.status == PaymentStatus.UPCOMING
        ).order_by(LoanPayment.sequence).all()

        total_interest_paid = sum(p.interest_paid for p in paid_payments)
        total_principal_paid = sum(p.principal_paid for p in paid_payments)

        table = Table(title=f"Loan: {loan.name}")
        table.add_column("Detail")
        table.add_column("Value")

        table.add_row("Type", loan.type.value)
        table.add_row("Lender", loan.lender or "-")
        table.add_row("Principal", format_currency(loan.total_principal))
        table.add_row("Rate", f"{loan.interest_rate}%")
        table.add_row("EMI", format_currency(loan.emi_amount))
        table.add_row("Tenure", f"{loan.tenure_months} months")
        table.add_row("Paid", f"{len(paid_payments)}/{loan.tenure_months}")
        table.add_row("Principal repaid", format_currency(total_principal_paid))
        table.add_row("Interest paid", format_currency(total_interest_paid))
        table.add_row("Remaining principal", format_currency(loan.remaining_principal))
        console.print(table)

        if upcoming:
            ptable = Table(title=f"Next 6 Payments")
            ptable.add_column("#")
            ptable.add_column("Due")
            ptable.add_column("EMI")
            ptable.add_column("Principal")
            ptable.add_column("Interest")
            ptable.add_column("Remaining")
            ptable.add_column("Status")
            for p in upcoming[:6]:
                ptable.add_row(
                    str(p.sequence),
                    p.due_date.isoformat(),
                    format_currency(p.emi_amount),
                    format_currency(p.principal_paid),
                    format_currency(p.interest_paid),
                    format_currency(p.remaining_after),
                    "[green]✓ Paid[/green]" if p.status == PaymentStatus.PAID else "[yellow]Upcoming[/yellow]",
                )
            console.print(ptable)


@loan_app.command("pay")
def loan_pay(
    loan_id: int = typer.Argument(..., help="Loan ID"),
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Payment month (default: current)"),
):
    init_db()
    target_month = date.today().replace(day=1)
    if month:
        target_month = date.fromisoformat(month + "-01")

    with get_session() as session:
        loan = session.query(Loan).filter(Loan.id == loan_id).first()
        if not loan:
            rprint("[red]Loan not found.[/red]")
            raise typer.Exit(1)

        payment = session.query(LoanPayment).filter(
            LoanPayment.loan_id == loan.id,
            LoanPayment.status == PaymentStatus.UPCOMING,
        ).order_by(LoanPayment.sequence).first()

        if not payment:
            rprint("[green]All payments are already paid![/green]")
            return

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
        rprint(f"[green]✓[/green] Paid {loan.name} EMI #{payment.sequence}: {format_currency(payment.emi_amount)}")
        rprint(f"  Principal: {format_currency(payment.principal_paid)}  |  Interest: {format_currency(payment.interest_paid)}")
        rprint(f"  Remaining: {format_currency(loan.remaining_principal)} ({loan.remaining_tenure} months)")


@loan_app.command("forecast")
def loan_forecast(
    loan_id: int = typer.Argument(..., help="Loan ID"),
):
    init_db()
    with get_session() as session:
        loan = session.query(Loan).filter(Loan.id == loan_id).first()
        if not loan:
            rprint("[red]Loan not found.[/red]")
            raise typer.Exit(1)

        payments = session.query(LoanPayment).filter(
            LoanPayment.loan_id == loan.id
        ).order_by(LoanPayment.sequence).all()

        table = Table(title=f"Amortization Schedule — {loan.name}")
        table.add_column("#")
        table.add_column("Due")
        table.add_column("EMI")
        table.add_column("Principal")
        table.add_column("Interest")
        table.add_column("Balance")
        table.add_column("Status")

        for p in payments:
            status_str = "[green]✓[/green]" if p.status == PaymentStatus.PAID else "[yellow]◷[/yellow]"
            table.add_row(
                str(p.sequence),
                p.due_date.isoformat(),
                format_currency(p.emi_amount),
                format_currency(p.principal_paid),
                format_currency(p.interest_paid),
                format_currency(p.remaining_after),
                status_str,
            )
        console.print(table)

        total_interest = sum(p.interest_paid for p in payments)
        rprint(f"\nTotal interest over remaining tenure: [yellow]{format_currency(total_interest)}[/yellow]")


@loan_app.command("whatif")
def loan_whatif(
    loan_id: int = typer.Argument(..., help="Loan ID"),
    prepay: str = typer.Option(None, "--prepay", help="Prepayment amount to simulate"),
    close_by: str = typer.Option(None, "--close-by", metavar="YYYY-MM", help="Target close date to simulate"),
):
    init_db()
    if not prepay and not close_by:
        rprint("[red]Specify --prepay <amount> or --close-by YYYY-MM[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        loan = session.query(Loan).filter(Loan.id == loan_id).first()
        if not loan:
            rprint("[red]Loan not found.[/red]")
            raise typer.Exit(1)

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
                rprint(f"[red]{result['error']}[/red]")
                return

            table = Table(title=f"What-If: Prepay {format_currency(amt)}")
            table.add_column("Metric")
            table.add_column("Value")
            table.add_row("Current EMI", format_currency(loan.emi_amount))
            table.add_row("Remaining principal", format_currency(loan.remaining_principal))
            table.add_row("Prepayment", format_currency(amt))
            if "new_tenure" in result and result["new_tenure"] == 0:
                table.add_row("[green]Result[/green]", "[bold]Loan cleared![/bold]")
            else:
                table.add_row("New remaining", format_currency(result.get("new_principal", 0)))
                table.add_row("Months saved", f"[green]{result['months_saved']}[/green]")
                table.add_row("Interest saved", f"[green]{format_currency(result['interest_saved'])}[/green]")
            console.print(table)

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
                rprint(f"[red]{result['error']}[/red]")
                return

            table = Table(title=f"What-If: Close by {close_by}")
            table.add_column("Metric")
            table.add_column("Value")
            table.add_row("Current EMI", format_currency(result["current_emi"]))
            table.add_row("Required EMI", f"[yellow]{format_currency(result['required_emi'])}[/yellow]")
            table.add_row("Extra per month", f"[green]{format_currency(result['extra_per_month'])}[/green]")
            table.add_row("Months to go", str(result["months_to_go"]))
            table.add_row("Interest saved", f"[green]{format_currency(result['interest_saved'])}[/green]")
            console.print(table)


# ─── Allocate ────────────────────────────────────────────────────────────────

@app.command()
def allocate(
    salary: str = typer.Argument(..., help="Salary amount"),
    date_str: str = typer.Option(None, "-d", "--date", metavar="YYYY-MM-DD", help="Salary date (default: today)"),
):
    init_db()
    amt = parse_amount(salary)
    tx_date = date.fromisoformat(date_str) if date_str else date.today()

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
                rprint("[red]Salary category not found.[/red]")
                raise typer.Exit(1)
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
            tx_date = existing_salary.date

        rprint(f"\n[bold]📊 Salary Allocation — {tx_date.strftime('%B %Y')}[/bold]")
        rprint(f"Salary: [green]{format_currency(amt)}[/green]\n")

        budgets = session.query(Budget).filter(Budget.month == budget_month).all()
        loans = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()
        committed_total = Decimal("0.0")
        budget_total = Decimal("0.0")

        for loan in loans:
            committed_total += loan.emi_amount
            rprint(f"  [cyan]Loan EMI:[/cyan] {loan.name} [yellow]{format_currency(loan.emi_amount)}[/yellow] (₹{loan.remaining_principal:,.0f} remaining)")

        if budgets:
            for bg in budgets:
                budget_total += bg.limit_amount
                cat_name = bg.category.name if bg.category else "Unknown"
                if bg.category and bg.category.name in ("EMI", "Housing", "Insurance", "Education"):
                    committed_total += bg.limit_amount
                    rprint(f"  [cyan]Committed:[/cyan] {cat_name} [yellow]{format_currency(bg.limit_amount)}[/yellow]")
                else:
                    rprint(f"  [cyan]Budget:[/cyan] {cat_name} [yellow]{format_currency(bg.limit_amount)}[/yellow]")

        total_allocated = committed_total + budget_total
        remaining = amt - total_allocated
        rprint(f"\n  [cyan]Committed (incl. loans):[/cyan] {format_currency(committed_total)}")
        rprint(f"  [cyan]Budget total:[/cyan] {format_currency(budget_total)}")
        if remaining >= 0:
            rprint(f"  [green]Remaining after allocation: {format_currency(remaining)}[/green]")
        else:
            rprint(f"  [red]Over-allocated by: {format_currency(abs(remaining))}[/red]")
        rprint("")


# ─── Reports ─────────────────────────────────────────────────────────────────

report_app = typer.Typer()
app.add_typer(report_app, name="report", help="Generate reports")


@report_app.command("monthly")
def report_monthly(
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Month (default: current)"),
):
    init_db()
    start = date.today().replace(day=1)
    if month:
        start = date.fromisoformat(month + "-01")
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1) if start.month < 12 else date(start.year + 1, 1, 1)

    with get_session() as session:
        income = session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.INCOME,
        ).all()
        expenses = session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        total_income = sum(t.amount for t in income)
        total_expense = abs(sum(t.amount for t in expenses))
        net = total_income - total_expense

        table = Table(title=f"Monthly Report — {start.strftime('%B %Y')}")
        table.add_column("Metric", style="bold")
        table.add_column("Amount")

        table.add_row("Total Income", format_currency(total_income))
        table.add_row("Total Expenses", format_currency(total_expense))
        table.add_row("Net", format_currency(net))

        console.print(table)

        if expenses:
            cat_table = Table(title="Top Expenses")
            cat_table.add_column("Date")
            cat_table.add_column("Description")
            cat_table.add_column("Category")
            cat_table.add_column("Amount")
            for tx in sorted(expenses, key=lambda x: abs(x.amount), reverse=True)[:10]:
                cat_name = tx.category.name if tx.category else "Uncategorized"
                cat_table.add_row(
                    tx.date.isoformat(),
                    tx.description[:40],
                    cat_name,
                    format_currency(abs(tx.amount)),
                )
            console.print(cat_table)


@report_app.command("categories")
def report_categories(
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Month (default: current)"),
):
    init_db()
    start = date.today().replace(day=1)
    if month:
        start = date.fromisoformat(month + "-01")
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1) if start.month < 12 else date(start.year + 1, 1, 1)

    with get_session() as session:
        rows = session.query(
            Category.name,
            Transaction.amount,
        ).join(Category, Transaction.category_id == Category.id).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.EXPENSE,
        ).all()

        cat_totals = {}
        for cat_name, amt in rows:
            if cat_name not in cat_totals:
                cat_totals[cat_name] = Decimal("0.0")
            cat_totals[cat_name] += abs(amt)

        total = sum(cat_totals.values())
        table = Table(title=f"Category Breakdown — {start.strftime('%B %Y')}")
        table.add_column("Category")
        table.add_column("Amount")
        table.add_column("%")

        for cat_name, amt in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
            pct = f"{amt / total * 100:.1f}%" if total > 0 else "0%"
            table.add_row(cat_name, format_currency(amt), pct)
        table.add_row("[bold]Total[/bold]", format_currency(total), "100%")
        console.print(table)


@report_app.command("committed")
def report_committed(
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Month (default: current)"),
):
    init_db()
    start = date.today().replace(day=1)
    if month:
        start = date.fromisoformat(month + "-01")
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1) if start.month < 12 else date(start.year + 1, 1, 1)

    committed_cats = {"EMI", "Housing", "Insurance", "Education"}

    with get_session() as session:
        income = sum(t.amount for t in session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.INCOME,
        ).all())

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

        table = Table(title=f"Committed vs Discretionary — {start.strftime('%B %Y')}")
        table.add_column("Category")
        table.add_column("Amount")
        table.add_column("% of Income")

        table.add_row("[cyan]Committed (EMI, Rent, Insurance)[/cyan]", format_currency(committed), f"{committed / income * 100:.1f}%" if income > 0 else "0%")
        table.add_row("[yellow]Discretionary[/yellow]", format_currency(discretionary), f"{discretionary / income * 100:.1f}%" if income > 0 else "0%")
        table.add_row("[bold]Total Expenses[/bold]", format_currency(committed + discretionary), f"{(committed + discretionary) / income * 100:.1f}%" if income > 0 else "0%")
        table.add_row("[green]Remaining[/green]", format_currency(income - committed - discretionary), f"{(income - committed - discretionary) / income * 100:.1f}%" if income > 0 else "0%")
        console.print(table)

        loans = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()
        if loans:
            ltable = Table(title="Active Loans")
            ltable.add_column("Loan")
            ltable.add_column("EMI")
            ltable.add_column("Remaining")
            ltable.add_column("Tenure Left")
            for loan in loans:
                ltable.add_row(loan.name, format_currency(loan.emi_amount), format_currency(loan.remaining_principal), f"{loan.remaining_tenure} mo")
            console.print(ltable)


@report_app.command("networth")
def report_networth():
    init_db()
    with get_session() as session:
        asset_accounts = session.query(Account).filter(
            Account.is_active == True, Account.type.in_([AccountType.SAVINGS, AccountType.CASH, AccountType.INVESTMENT, AccountType.WALLET])
        ).all()
        liabilities = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).all()

        total_assets = Decimal("0.00")
        asset_table = Table(title="Assets")
        asset_table.add_column("Account")
        asset_table.add_column("Type")
        asset_table.add_column("Balance")
        for acct in asset_accounts:
            bal = acct.balance if acct.balance else Decimal("0.00")
            if bal > 0:
                total_assets += bal
                asset_table.add_row(acct.name, acct.type.value, format_currency(bal))
        console.print(asset_table)

        total_liabilities = Decimal("0.00")
        liability_table = Table(title="Liabilities")
        liability_table.add_column("Loan")
        liability_table.add_column("Remaining")
        for loan in liabilities:
            total_liabilities += loan.remaining_principal
            liability_table.add_row(loan.name, format_currency(loan.remaining_principal))
        console.print(liability_table)

        net = total_assets - total_liabilities
        summary = Table(title="Net Worth")
        summary.add_column("Metric")
        summary.add_column("Amount")
        summary.add_row("Total Assets", format_currency(total_assets))
        summary.add_row("Total Liabilities", format_currency(total_liabilities))
        if net >= 0:
            summary.add_row("[bold]Net Worth[/bold]", f"[green]{format_currency(net)}[/green]")
        else:
            summary.add_row("[bold]Net Worth[/bold]", f"[red]{format_currency(net)}[/red]")
        console.print(summary)


@report_app.command("cashflow")
def report_cashflow(
    month: str = typer.Option(None, "-m", "--month", metavar="YYYY-MM", help="Month (default: current)"),
):
    init_db()
    start = date.today().replace(day=1)
    if month:
        start = date.fromisoformat(month + "-01")
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1) if start.month < 12 else date(start.year + 1, 1, 1)

    with get_session() as session:
        rows = session.query(Transaction).filter(
            Transaction.date >= start, Transaction.date < end,
            Transaction.type == TransactionType.EXPENSE,
        ).order_by(Transaction.date).all()

        total_spent = abs(sum(t.amount for t in rows))
        today = date.today()
        days_in_month = (end - start).days
        day_of_month = (today - start).days + 1
        daily_rate = total_spent / day_of_month if day_of_month > 0 else Decimal("0.0")
        projected = daily_rate * days_in_month
        remaining_days = days_in_month - day_of_month

        table = Table(title=f"Cashflow — {start.strftime('%B %Y')}")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Day of month", f"{day_of_month}/{days_in_month}")
        table.add_row("Spent so far", format_currency(total_spent))
        table.add_row("Daily avg", format_currency(daily_rate))
        table.add_row("Projected total", format_currency(projected))
        table.add_row("Days remaining", str(remaining_days))
        console.print(table)

        if remaining_days > 0 and daily_rate > 0:
            income_rows = session.query(Transaction).filter(
                Transaction.date >= start, Transaction.date < end,
                Transaction.type == TransactionType.INCOME,
            ).all()
            total_income = sum(t.amount for t in income_rows)
            remaining_budget = total_income - total_spent
            daily_remaining = remaining_budget / remaining_days if remaining_days > 0 else Decimal("0.0")
            rprint(f"\nRemaining budget: [green]{format_currency(remaining_budget)}[/green]  |  ₹{daily_remaining:.0f}/day")


# ─── Import ──────────────────────────────────────────────────────────────────

@app.command()
def import_csv(
    file: str = typer.Option(..., "-f", "--file", help="Path to CSV file"),
    account: str = typer.Option(None, "-a", "--account", help="Account name (default: Cash)"),
):
    init_db()
    rprint("[yellow]CSV import coming soon![/yellow]")


# ─── Reconcile ───────────────────────────────────────────────────────────────

@app.command()
def reconcile(
    account: str = typer.Option(None, "-a", "--account", help="Account name (default: all)"),
):
    init_db()
    with get_session() as session:
        query = session.query(Transaction).filter(Transaction.status == TransactionStatus.PENDING)
        if account:
            acct = session.query(Account).filter(Account.name == account).first()
            if not acct:
                rprint(f"[red]Account '{account}' not found.[/red]")
                raise typer.Exit(1)
            query = query.filter(Transaction.account_id == acct.id)

        pending = query.all()
        if not pending:
            rprint("[green]All transactions are cleared![/green]")
            return

        for tx in pending:
            tx.status = TransactionStatus.CLEARED
        session.commit()
        rprint(f"[green]✓[/green] Marked {len(pending)} transactions as cleared")


# ─── Query ───────────────────────────────────────────────────────────────────

@app.command()
def query(
    sql: str = typer.Argument(..., help="Read-only SQL SELECT query"),
):
    init_db()
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        rprint("[red]Only SELECT queries are allowed.[/red]")
        raise typer.Exit(1)

    with engine.connect() as conn:
        result = conn.execute(text(sql))
        rows = result.fetchall()
        if not rows:
            rprint("[yellow]No results.[/yellow]")
            return
        columns = result.keys()
        table = Table(title="Query Result")
        for col in columns:
            table.add_column(str(col))
        for row in rows:
            table.add_row(*[str(c) if c is not None else "" for c in row])
        console.print(table)


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    init_db()
    app()


if __name__ == "__main__":
    main()
