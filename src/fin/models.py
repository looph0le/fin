import datetime
import enum
from decimal import Decimal

from sqlalchemy import Boolean, Column, Date, Enum, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship

today = datetime.date.today


class Base(DeclarativeBase):
    pass


class AccountType(str, enum.Enum):
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    LOAN = "loan"
    INVESTMENT = "investment"
    CASH = "cash"
    WALLET = "wallet"


class TransactionType(str, enum.Enum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    CLEARED = "cleared"
    RECONCILED = "reconciled"


class CategoryType(str, enum.Enum):
    EXPENSE = "expense"
    INCOME = "income"


class Frequency(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class LoanType(str, enum.Enum):
    PERSONAL = "personal"
    HOME = "home"
    CAR = "car"
    EDUCATION = "education"
    CREDIT_CARD = "credit_card"


class LoanStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class PaymentStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    PAID = "paid"
    LATE = "late"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    type = Column(Enum(AccountType), nullable=False)
    institution = Column(String(255))
    balance = Column(Numeric(12, 2), default=Decimal("0.00"))
    is_active = Column(Boolean, default=True)
    created_at = Column(Date, default=today)
    updated_at = Column(Date, default=today, onupdate=today)

    transactions = relationship("Transaction", back_populates="account")
    recurring_items = relationship("RecurringItem", back_populates="account")

    def __repr__(self):
        return f"<Account {self.name} ({self.type.value})>"


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    type = Column(Enum(CategoryType), nullable=False)

    transactions = relationship("Transaction", back_populates="category")
    budgets = relationship("Budget", back_populates="category")
    recurring_items = relationship("RecurringItem", back_populates="category")

    def __repr__(self):
        return f"<Category {self.name}>"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    date = Column(Date, nullable=False, default=today)
    description = Column(String(500), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"))
    type = Column(Enum(TransactionType), nullable=False)
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING)
    is_recurring = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(Date, default=today)

    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=True)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction {self.description}: ₹{self.amount}>"


class RecurringItem(Base):
    __tablename__ = "recurring_items"

    id = Column(Integer, primary_key=True)
    description = Column(String(500), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"))
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    frequency = Column(Enum(Frequency), default=Frequency.MONTHLY)
    day_of_month = Column(Integer)
    next_date = Column(Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(Date, default=today)

    category = relationship("Category", back_populates="recurring_items")
    account = relationship("Account", back_populates="recurring_items")

    def __repr__(self):
        return f"<RecurringItem {self.description}: ₹{self.amount}>"


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    month = Column(Date, nullable=False)
    limit_amount = Column(Numeric(12, 2), nullable=False)
    rollover = Column(Boolean, default=False)
    created_at = Column(Date, default=today)

    category = relationship("Category", back_populates="budgets")

    def __repr__(self):
        return f"<Budget {self.category.name} {self.month}: ₹{self.limit_amount}>"


class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    type = Column(Enum(LoanType), nullable=False)
    lender = Column(String(255))
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"))
    total_principal = Column(Numeric(12, 2), nullable=False)
    interest_rate = Column(Numeric(5, 2), nullable=False)
    tenure_months = Column(Integer, nullable=False)
    emi_amount = Column(Numeric(12, 2), nullable=False)
    emi_day = Column(Integer, nullable=False)
    remaining_principal = Column(Numeric(12, 2), nullable=False)
    remaining_tenure = Column(Integer, nullable=False)
    disbursement_date = Column(Date)
    first_emi_date = Column(Date)
    status = Column(Enum(LoanStatus), default=LoanStatus.ACTIVE)
    created_at = Column(Date, default=today)

    account = relationship("Account")
    category = relationship("Category")
    payments = relationship("LoanPayment", back_populates="loan", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Loan {self.name}: ₹{self.remaining_principal} remaining>"


class LoanPayment(Base):
    __tablename__ = "loan_payments"

    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    due_date = Column(Date, nullable=False)
    emi_amount = Column(Numeric(12, 2), nullable=False)
    principal_paid = Column(Numeric(12, 2), nullable=False)
    interest_paid = Column(Numeric(12, 2), nullable=False)
    remaining_after = Column(Numeric(12, 2), nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.UPCOMING)
    paid_date = Column(Date)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    loan = relationship("Loan", back_populates="payments")
    transaction = relationship("Transaction", foreign_keys=[transaction_id])

    def __repr__(self):
        return f"<LoanPayment #{self.sequence}: ₹{self.emi_amount}>"


class NetWorthSnapshot(Base):
    __tablename__ = "networth_snapshots"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, default=today)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    loan_id = Column(Integer, ForeignKey("loans.id"))
    amount = Column(Numeric(12, 2), nullable=False)
    type = Column(String(10), nullable=False)  # asset or liability
    notes = Column(Text)
    created_at = Column(Date, default=today)

    account = relationship("Account")
    loan = relationship("Loan")

    def __repr__(self):
        return f"<NetWorthSnapshot {self.date}: {self.type} ₹{self.amount}>"
