from sqlalchemy.orm import Session

from fin.models import Category, CategoryType


DEFAULT_CATEGORIES = [
    ("Food", CategoryType.EXPENSE),
    ("Transport", CategoryType.EXPENSE),
    ("Housing", CategoryType.EXPENSE),
    ("Utilities", CategoryType.EXPENSE),
    ("Entertainment", CategoryType.EXPENSE),
    ("Shopping", CategoryType.EXPENSE),
    ("Healthcare", CategoryType.EXPENSE),
    ("Insurance", CategoryType.EXPENSE),
    ("EMI", CategoryType.EXPENSE),
    ("Education", CategoryType.EXPENSE),
    ("Personal Care", CategoryType.EXPENSE),
    ("Gifts", CategoryType.EXPENSE),
    ("Travel", CategoryType.EXPENSE),
    ("Miscellaneous", CategoryType.EXPENSE),
    ("Salary", CategoryType.INCOME),
    ("Bonus", CategoryType.INCOME),
    ("Interest", CategoryType.INCOME),
    ("Refund", CategoryType.INCOME),
]


def seed_categories(session: Session):
    existing = {c.name for c in session.query(Category).all()}
    for name, cat_type in DEFAULT_CATEGORIES:
        if name not in existing:
            session.add(Category(name=name, type=cat_type))
    session.commit()
