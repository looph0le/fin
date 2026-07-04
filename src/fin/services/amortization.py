from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List


def calculate_monthly_rate(annual_rate: Decimal) -> Decimal:
    return (annual_rate / Decimal("100")) / Decimal("12")


def generate_schedule(
    remaining_principal: Decimal,
    annual_rate: Decimal,
    emi_amount: Decimal,
    remaining_tenure: int,
    start_date: date,
    emi_day: int,
    already_paid: int = 0,
) -> List[dict]:
    rate = calculate_monthly_rate(annual_rate)
    schedule = []
    balance = remaining_principal

    for i in range(remaining_tenure):
        seq = already_paid + i + 1

        try:
            due = start_date.replace(day=min(emi_day, 28))
        except ValueError:
            due = start_date.replace(day=28)

        interest = (balance * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        principal = emi_amount - interest

        if principal > balance:
            principal = balance
            interest = emi_amount - principal

        if principal < 0:
            principal = Decimal("0.00")
            interest = emi_amount

        next_balance = balance - principal
        if next_balance < 0:
            next_balance = Decimal("0.00")

        schedule.append({
            "sequence": seq,
            "due_date": due,
            "emi_amount": emi_amount,
            "principal_paid": principal,
            "interest_paid": interest,
            "remaining_after": next_balance,
        })

        balance = next_balance
        next_month = due.month + 1
        next_year = due.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        start_date = date(next_year, next_month, 1)

        if balance <= Decimal("0.00"):
            break

    return schedule


def whatif_prepay(
    remaining_principal: Decimal,
    annual_rate: Decimal,
    emi_amount: Decimal,
    remaining_tenure: int,
    current_date: date,
    emi_day: int,
    prepay_amount: Decimal,
    already_paid: int = 0,
) -> dict:
    new_principal = remaining_principal - prepay_amount
    if new_principal <= 0:
        months_saved = remaining_tenure
        interest_saved = Decimal("0.00")
        for p in generate_schedule(remaining_principal, annual_rate, emi_amount, remaining_tenure, current_date, emi_day, already_paid):
            interest_saved += p["interest_paid"]
        return {
            "new_tenure": 0,
            "months_saved": months_saved,
            "interest_saved": interest_saved,
            "final_payment": abs(new_principal) + prepay_amount if new_principal < 0 else prepay_amount,
        }

    original_schedule = generate_schedule(remaining_principal, annual_rate, emi_amount, remaining_tenure, current_date, emi_day, already_paid)
    new_schedule = generate_schedule(new_principal, annual_rate, emi_amount, remaining_tenure, current_date, emi_day, already_paid)

    original_interest = sum(p["interest_paid"] for p in original_schedule)
    new_interest = sum(p["interest_paid"] for p in new_schedule)

    remaining_after_prepay = new_principal
    months_reduced = 0
    for p in original_schedule:
        if p["remaining_after"] <= new_principal:
            months_reduced = remaining_tenure - len(new_schedule)
            break

    return {
        "new_principal": new_principal,
        "new_tenure": len(new_schedule),
        "months_saved": len(original_schedule) - len(new_schedule),
        "interest_saved": original_interest - new_interest,
    }


def whatif_close_by(
    remaining_principal: Decimal,
    annual_rate: Decimal,
    emi_amount: Decimal,
    remaining_tenure: int,
    current_date: date,
    emi_day: int,
    target_date: date,
    already_paid: int = 0,
) -> dict:
    months_available = (target_date.year - current_date.year) * 12 + (target_date.month - current_date.month)
    if months_available <= 0:
        return {"error": "Target date must be in the future"}

    rate = calculate_monthly_rate(annual_rate)
    balance = remaining_principal

    interest_total = Decimal("0.00")
    for _ in range(months_available):
        interest = (balance * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        interest_total += interest
        principal = min(emi_amount - interest, balance)
        balance -= principal
        if balance <= Decimal("0.00"):
            break

    total_to_pay = remaining_principal + interest_total
    new_emi = (total_to_pay / Decimal(months_available)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    original_interest = sum(
        p["interest_paid"]
        for p in generate_schedule(remaining_principal, annual_rate, emi_amount, remaining_tenure, current_date, emi_day, already_paid)
    )

    return {
        "current_emi": emi_amount,
        "required_emi": new_emi,
        "extra_per_month": new_emi - emi_amount,
        "months_to_go": months_available,
        "target_date": target_date.isoformat(),
        "interest_saved": original_interest - interest_total,
    }
