from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from fin.helpers import (
    amt_str,
    auto_categorize,
    find_category,
    get_emi_category,
    get_or_create_cash_account,
    parse_amount,
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
    RecurringItem,
    SalaryAllocation,
    Transaction,
    TransactionType,
)
from fin.services.amortization import generate_schedule


STEP_KEYS = ["accounts", "income", "recurring", "loans", "budgets", "allocation", "catchup"]


def onboarding_status(session: Session) -> dict:
    accounts = session.query(Account).all()
    has_salary = session.query(RecurringItem).filter(
        RecurringItem.description.ilike("%salary%"),
        RecurringItem.is_active,
    ).first() is not None
    recurring_count = session.query(RecurringItem).filter(RecurringItem.is_active).count()
    loan_count = session.query(Loan).filter(Loan.status == LoanStatus.ACTIVE).count()
    budget_count = session.query(Budget).filter(Budget.month == date.today().replace(day=1)).count()
    has_allocation = session.query(SalaryAllocation).filter(SalaryAllocation.is_active).first() is not None
    today = date.today()
    start = today.replace(day=1)
    if today.month < 12:
        end = date(today.year, today.month + 1, 1)
    else:
        end = date(today.year + 1, 1, 1)
    tx_count = session.query(Transaction).filter(
        Transaction.date >= start, Transaction.date < end,
    ).count()

    steps = {
        "accounts": {
            "done": len(accounts) > 0,
            "summary": f"{len(accounts)} account(s): {', '.join(f'{a.name} ({amt_str(a.balance or 0)})' for a in accounts)}" if accounts else "No accounts set up",
        },
        "income": {
            "done": has_salary,
            "summary": "Salary recurring item configured" if has_salary else "No salary/income set up",
        },
        "recurring": {
            "done": recurring_count > 0,
            "summary": f"{recurring_count} recurring item(s)" if recurring_count > 0 else "No recurring expenses",
        },
        "loans": {
            "done": loan_count > 0,
            "summary": f"{loan_count} active loan(s)" if loan_count > 0 else "No active loans",
        },
        "budgets": {
            "done": budget_count > 0,
            "summary": f"{budget_count} budget(s) set for this month" if budget_count > 0 else "No budgets set",
        },
        "allocation": {
            "done": has_allocation,
            "summary": "Salary allocation rules configured" if has_allocation else "No salary allocation defined",
        },
        "catchup": {
            "done": tx_count > 0,
            "summary": f"{tx_count} transaction(s) this month" if tx_count > 0 else "No transactions this month",
        },
    }

    done_count = sum(1 for s in steps.values() if s["done"])
    next_step = None
    for key in STEP_KEYS:
        if not steps[key]["done"]:
            next_step = key
            break

    return {
        "status": "complete" if done_count == len(STEP_KEYS) else "in_progress",
        "overall": f"{done_count} of {len(STEP_KEYS)} steps complete",
        "steps": steps,
        "next_step": next_step,
    }


PROMPTS = {
    "accounts": (
        "Let's set up your accounts. You can add savings accounts, credit cards, cash, wallet, and investment accounts. "
        "For each account, I need: name, type (savings/credit_card/cash/wallet/investment), institution (optional), and current balance."
    ),
    "income": (
        "Let's set up your income. What's your monthly salary amount and which day of the month do you receive it? "
        "Any other recurring income (freelance, rental, interest)?"
    ),
    "recurring": (
        "Let's add your recurring expenses. These are monthly/quarterly/yearly charges like rent, subscriptions, insurance premiums, etc. "
        "For each: description, amount, category, day of month, and frequency (monthly/quarterly/yearly)."
    ),
    "loans": (
        "Let's add any active loans. For each: name, principal, interest rate (%), tenure in months, EMI amount, EMI day, "
        "loan type (personal/home/car/education/credit_card), and lender (optional)."
    ),
    "budgets": (
        "Let's set monthly budgets. For each category, tell me the monthly spending limit. "
        "I can also suggest budgets based on common guidelines if you prefer."
    ),
    "allocation": (
        "Let's configure salary allocation. Tell me which account receives your salary and how you want it distributed: "
        "e.g., fixed amounts to specific budgets, percentage to savings, etc."
    ),
    "catchup": (
        "Let's backfill recent transactions so this month isn't empty. "
        "Provide any recent transactions you remember: amount, description, date (YYYY-MM-DD), category, and whether it's income."
    ),
}


def step_accounts(session: Session, data: dict) -> dict:
    results = []
    errors = []
    accounts_list = data.get("accounts", [])
    if not accounts_list:
        return {"error": "No accounts provided", "next_prompt": "Provide at least one account with name, type, and balance."}

    for acct_data in accounts_list:
        name = acct_data.get("name", "").strip()
        if not name:
            errors.append({"account": acct_data, "error": "Account name is required"})
            continue
        existing = session.query(Account).filter(Account.name == name).first()
        if existing:
            results.append({"name": name, "status": "skipped", "reason": "already exists"})
            continue
        try:
            atype = AccountType(acct_data.get("type", "savings").lower())
        except ValueError:
            errors.append({"account": acct_data, "error": f"Invalid type: {acct_data.get('type')}"})
            continue
        acct = Account(
            name=name,
            type=atype,
            institution=acct_data.get("institution"),
        )
        session.add(acct)
        session.flush()
        balance = parse_amount(str(acct_data.get("balance", "0")))
        if balance != 0:
            acct.balance = balance
        results.append({"name": name, "type": atype.value, "balance": str(acct.balance), "status": "created"})

    session.commit()
    return {
        "step": "accounts",
        "results": results,
        "errors": errors,
        "next_step": "income",
        "next_prompt": PROMPTS["income"],
    }


def step_income(session: Session, data: dict) -> dict:
    results = []
    errors = []

    salary_amount = data.get("salary_amount")
    salary_day = data.get("salary_day")
    if salary_amount and salary_day:
        amt = parse_amount(str(salary_amount))
        existing = session.query(RecurringItem).filter(
            RecurringItem.description.ilike("%salary%"),
            RecurringItem.is_active,
        ).first()
        if existing:
            results.append({"description": "Salary", "status": "skipped", "reason": "already exists"})
        else:
            cat = find_category(session, "Salary")
            if not cat:
                return {"error": "Salary category not found"}
            acct_name = data.get("salary_account")
            acct = None
            if acct_name:
                acct = session.query(Account).filter(Account.name == acct_name).first()
            if not acct:
                acct = get_or_create_cash_account(session)
            item = RecurringItem(
                description="Salary - Monthly",
                amount=amt,
                category_id=cat.id,
                account_id=acct.id,
                frequency=Frequency.MONTHLY,
                day_of_month=int(salary_day),
                is_active=True,
            )
            session.add(item)
            results.append({"description": "Salary", "amount": str(amt), "day": int(salary_day), "status": "created"})

    other_income = data.get("other_income", [])
    for inc in other_income:
        desc = inc.get("description", "").strip()
        if not desc:
            continue
        amt = parse_amount(str(inc.get("amount", "0")))
        cat_name = inc.get("category", "Interest")
        cat = find_category(session, cat_name)
        if not cat:
            cat = find_category(session, "Interest")
        acct_name = inc.get("account")
        acct = None
        if acct_name:
            acct = session.query(Account).filter(Account.name == acct_name).first()
        if not acct:
            acct = get_or_create_cash_account(session)
        item = RecurringItem(
            description=desc,
            amount=amt,
            category_id=cat.id,
            account_id=acct.id,
            frequency=Frequency(inc.get("frequency", "monthly").lower()),
            day_of_month=int(inc.get("day", 1)),
            is_active=True,
        )
        session.add(item)
        results.append({"description": desc, "amount": str(amt), "status": "created"})

    session.commit()
    return {
        "step": "income",
        "results": results,
        "errors": errors,
        "next_step": "recurring",
        "next_prompt": PROMPTS["recurring"],
    }


def step_recurring(session: Session, data: dict) -> dict:
    results = []
    errors = []
    items = data.get("items", [])
    if not items:
        return {"error": "No recurring items provided"}

    for item_data in items:
        desc = item_data.get("description", "").strip()
        if not desc:
            errors.append({"item": item_data, "error": "Description is required"})
            continue
        amt = parse_amount(str(item_data.get("amount", "0")))
        if amt == 0:
            errors.append({"item": item_data, "error": "Amount must be non-zero"})
            continue
        cat_name = item_data.get("category", "Miscellaneous")
        cat = find_category(session, cat_name)
        if not cat:
            cat = auto_categorize(session, desc)
        acct_name = item_data.get("account")
        acct = None
        if acct_name:
            acct = session.query(Account).filter(Account.name == acct_name).first()
        if not acct:
            acct = get_or_create_cash_account(session)
        try:
            freq = Frequency(item_data.get("frequency", "monthly").lower())
        except ValueError:
            errors.append({"item": item_data, "error": f"Invalid frequency: {item_data.get('frequency')}"})
            continue
        day = int(item_data.get("day", 1))
        item = RecurringItem(
            description=desc,
            amount=amt,
            category_id=cat.id,
            account_id=acct.id,
            frequency=freq,
            day_of_month=day,
            is_active=True,
        )
        session.add(item)
        results.append({"description": desc, "amount": str(amt), "category": cat.name, "day": day, "frequency": freq.value, "status": "created"})

    session.commit()
    return {
        "step": "recurring",
        "results": results,
        "errors": errors,
        "next_step": "loans",
        "next_prompt": PROMPTS["loans"],
    }


def step_loans(session: Session, data: dict) -> dict:
    results = []
    errors = []
    loans_list = data.get("loans", [])
    if not loans_list:
        return {"error": "No loans provided"}

    for loan_data in loans_list:
        name = loan_data.get("name", "").strip()
        if not name:
            errors.append({"loan": loan_data, "error": "Loan name is required"})
            continue
        try:
            p = parse_amount(str(loan_data["principal"]))
            r_val = Decimal(str(loan_data["rate"]))
            e = parse_amount(str(loan_data["emi"]))
            tenure = int(loan_data["tenure"])
            day = int(loan_data["day"])
        except (KeyError, ValueError) as exc:
            errors.append({"loan": loan_data, "error": f"Missing or invalid field: {exc}"})
            continue
        try:
            lt = LoanType(loan_data.get("loan_type", "personal").lower())
        except ValueError:
            errors.append({"loan": loan_data, "error": f"Invalid loan type: {loan_data.get('loan_type')}"})
            continue
        acct_name = loan_data.get("account")
        acct = None
        if acct_name:
            acct = session.query(Account).filter(Account.name == acct_name).first()
        if not acct:
            acct = get_or_create_cash_account(session)
        emi_cat = get_emi_category(session)
        first_emi_date_str = loan_data.get("first_emi")
        first_emi_date = date.fromisoformat(first_emi_date_str) if first_emi_date_str else date.today().replace(day=min(day, 28))

        loan = Loan(
            name=name,
            type=lt,
            lender=loan_data.get("lender"),
            account_id=acct.id,
            category_id=emi_cat.id,
            total_principal=p,
            interest_rate=r_val,
            tenure_months=tenure,
            emi_amount=e,
            emi_day=day,
            remaining_principal=p,
            remaining_tenure=tenure,
            disbursement_date=date.fromisoformat(loan_data["disbursement"]) if loan_data.get("disbursement") else None,
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

        total_interest = sum(entry["interest_paid"] for entry in schedule)
        results.append({
            "name": name,
            "principal": str(p),
            "emi": str(e),
            "tenure": tenure,
            "total_interest": str(total_interest),
            "status": "created",
        })

    session.commit()
    return {
        "step": "loans",
        "results": results,
        "errors": errors,
        "next_step": "budgets",
        "next_prompt": PROMPTS["budgets"],
    }


def step_budgets(session: Session, data: dict) -> dict:
    results = []
    errors = []
    budget_month = date.today().replace(day=1)

    if data.get("suggest"):
        cats = session.query(Category).filter(Category.type == "expense").all()
        for cat in cats:
            existing = session.query(Budget).filter(
                Budget.category_id == cat.id, Budget.month == budget_month
            ).first()
            if not existing:
                bg = Budget(
                    category_id=cat.id,
                    month=budget_month,
                    limit_amount=Decimal("0.00"),
                    rollover=False,
                )
                session.add(bg)
                results.append({"category": cat.name, "limit": "0.00", "status": "placeholder"})
        session.commit()
        return {
            "step": "budgets",
            "results": results,
            "note": "Placeholder budgets created (₹0). Use set_budget tool to set actual limits.",
            "next_step": "allocation",
            "next_prompt": PROMPTS["allocation"],
        }

    budgets_map = data.get("budgets", {})
    if not budgets_map:
        return {"error": "No budgets provided. Set budgets or use 'suggest': true for auto-suggestions."}

    for cat_name, limit_str in budgets_map.items():
        cat = find_category(session, cat_name)
        if not cat:
            errors.append({"category": cat_name, "error": "Category not found"})
            continue
        limit_amt = parse_amount(str(limit_str))
        existing = session.query(Budget).filter(
            Budget.category_id == cat.id, Budget.month == budget_month
        ).first()
        if existing:
            existing.limit_amount = limit_amt
            results.append({"category": cat_name, "limit": str(limit_amt), "status": "updated"})
        else:
            bg = Budget(
                category_id=cat.id,
                month=budget_month,
                limit_amount=limit_amt,
                rollover=data.get("rollover", False),
            )
            session.add(bg)
            results.append({"category": cat_name, "limit": str(limit_amt), "status": "created"})

    session.commit()
    return {
        "step": "budgets",
        "results": results,
        "errors": errors,
        "next_step": "allocation",
        "next_prompt": PROMPTS["allocation"],
    }


def step_allocation(session: Session, data: dict) -> dict:
    results = []
    errors = []
    salary_amount = data.get("salary_amount")
    salary_day = data.get("salary_day")
    salary_account_name = data.get("salary_account")

    if not salary_amount or not salary_day:
        errors.append("salary_amount and salary_day are required")
        return {"step": "allocation", "results": [], "errors": errors, "error": "Missing required fields"}

    amt = parse_amount(str(salary_amount))
    acct = None
    if salary_account_name:
        acct = session.query(Account).filter(Account.name == salary_account_name).first()
    if not acct:
        acct = get_or_create_cash_account(session)

    existing = session.query(SalaryAllocation).filter(SalaryAllocation.is_active).first()
    if existing:
        existing.is_active = False

    allocation = SalaryAllocation(
        salary_amount=amt,
        salary_day=int(salary_day),
        salary_account_id=acct.id,
        is_active=True,
    )
    session.add(allocation)
    session.flush()
    results.append({
        "salary_amount": str(amt),
        "salary_day": int(salary_day),
        "salary_account": acct.name,
        "status": "created",
    })

    rules_data = data.get("rules", [])
    for i, rule_data in enumerate(rules_data):
        rule = AllocationRule(
            allocation_id=allocation.id,
            target_type=rule_data.get("target_type", "account"),
            target_name=rule_data.get("target_name", ""),
            allocation_type=rule_data.get("allocation_type", "remaining"),
            allocation_value=parse_amount(str(rule_data["allocation_value"])) if rule_data.get("allocation_value") else None,
            order=i,
        )
        session.add(rule)
        results.append({
            "rule": f"{rule.allocation_type} of {rule.target_type}:{rule.target_name}",
            "status": "created",
        })

    session.commit()
    return {
        "step": "allocation",
        "results": results,
        "errors": errors,
        "next_step": "catchup",
        "next_prompt": PROMPTS["catchup"],
    }


def step_catchup(session: Session, data: dict) -> dict:
    results = []
    errors = []
    transactions = data.get("transactions", [])
    if not transactions:
        return {"error": "No transactions provided"}

    default_account_name = data.get("default_account")
    acct = None
    if default_account_name:
        acct = session.query(Account).filter(Account.name == default_account_name).first()
    if not acct:
        acct = get_or_create_cash_account(session)

    count = 0
    for item in transactions:
        try:
            amt = parse_amount(str(item["amount"]))
            tx_type = TransactionType.INCOME if (item.get("income") or amt > 0) else TransactionType.EXPENSE
            tx_date_str = item.get("date")
            if tx_date_str:
                try:
                    tx_date = date.fromisoformat(tx_date_str)
                except ValueError:
                    tx_date = date.today()
            else:
                tx_date = date.today()

            cat = None
            if item.get("category"):
                cat = find_category(session, item["category"])
            if not cat:
                cat = auto_categorize(session, item.get("description", ""))

            tx = Transaction(
                account_id=acct.id,
                date=tx_date,
                description=item.get("description", ""),
                amount=amt,
                category_id=cat.id if cat else None,
                type=tx_type,
                notes=item.get("notes"),
            )
            session.add(tx)
            count += 1
            results.append({
                "description": item.get("description", ""),
                "amount": str(amt),
                "date": tx_date.isoformat(),
                "status": "logged",
            })
        except Exception as e:
            errors.append({"item": item, "error": str(e)})

    session.commit()
    return {
        "step": "catchup",
        "results": results,
        "errors": errors,
        "total_logged": count,
    }


STEP_HANDLERS = {
    "accounts": step_accounts,
    "income": step_income,
    "recurring": step_recurring,
    "loans": step_loans,
    "budgets": step_budgets,
    "allocation": step_allocation,
    "catchup": step_catchup,
}
