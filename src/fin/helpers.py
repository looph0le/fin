from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from fin.db import engine, get_session
from fin.models import Account, AccountType, Base, Category, CategoryType, Transaction
from fin.seed import seed_categories


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


def amt_str(amount: Decimal) -> str:
    sign = ""
    val = amount
    if val < 0:
        sign = "-"
        val = -val
    return f"{sign}₹{val:,.2f}"


def get_emi_category(session: Session) -> Category:
    cat = find_category(session, "EMI")
    if not cat:
        cat = Category(name="EMI", type=CategoryType.EXPENSE)
        session.add(cat)
        session.commit()
    return cat


def _tx_dict(tx: Transaction) -> dict:
    return {
        "id": tx.id,
        "account": tx.account.name if tx.account else None,
        "date": tx.date.isoformat(),
        "description": tx.description,
        "amount": str(tx.amount),
        "amount_formatted": amt_str(tx.amount),
        "category": tx.category.name if tx.category else None,
        "type": tx.type.value,
        "status": tx.status.value if tx.status else None,
        "is_recurring": tx.is_recurring,
        "notes": tx.notes,
    }
