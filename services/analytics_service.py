"""Read-only financial analytics for accepted Module 4 transactions."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from database import queries
from services import auth_service


class AnalyticsError(ValueError):
    """Safe error raised for invalid analytics requests."""


def _percentage(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _validate_date_range(start_date: Any, end_date: Any) -> tuple[str, str]:
    if type(start_date) is not str or type(end_date) is not str:
        raise AnalyticsError("The analytics date range is invalid.")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as error:
        raise AnalyticsError("The analytics date range is invalid.") from error
    if start > end:
        raise AnalyticsError("The analytics date range is invalid.")
    return start.isoformat(), end.isoformat()


def _require_authorized_session(session_token: Any, business_id: Any) -> None:
    if type(session_token) is not str or not session_token:
        raise AnalyticsError("Authentication is required for analytics.")
    try:
        session = auth_service.validate_session(session_token)
    except Exception as error:
        raise AnalyticsError("Authentication is required for analytics.") from error
    if not isinstance(session, dict) or session.get("success") is not True:
        raise AnalyticsError("Authentication is required for analytics.")
    user = session.get("user")
    if (
        not isinstance(user, dict)
        or type(user.get("user_id")) is not str
        or not user["user_id"]
    ):
        raise AnalyticsError("Authentication is required for analytics.")
    if type(business_id) is not str or not business_id:
        raise AnalyticsError("The selected business is unavailable.")
    try:
        membership = queries.get_business_membership(business_id, user["user_id"])
    except Exception as error:
        raise AnalyticsError("The selected business is unavailable.") from error
    if membership is None:
        raise AnalyticsError("The selected business is unavailable.")
    try:
        business_status = membership["business_status"]
        membership_status = membership["membership_status"]
        membership_role = membership["membership_role"]
    except (KeyError, TypeError, IndexError) as error:
        raise AnalyticsError("The selected business is unavailable.") from error
    if (
        business_status != "active"
        or membership_status != "active"
        or membership_role not in {"owner", "manager"}
    ):
        raise AnalyticsError("The selected business is unavailable.")


def _load_account(account_id: Any, business_id: str, currency: Any):
    if type(account_id) is not str or not account_id:
        raise AnalyticsError("The selected financial account is unavailable.")
    if type(currency) is not str or not currency:
        raise AnalyticsError("The selected analytics currency is invalid.")
    with queries.get_connection() as connection:
        account = connection.execute(
            """SELECT opening_balance_minor, currency
               FROM financial_accounts
               WHERE account_id=? AND business_id=? AND account_status='active'""",
            (account_id, business_id),
        ).fetchone()
    if account is None:
        raise AnalyticsError("The selected financial account is unavailable.")
    if account["currency"] != currency:
        raise AnalyticsError("The selected analytics currency is invalid.")
    return account


def _load_accepted_rows(
    *,
    business_id: str,
    account_id: str,
    start_date: str,
    end_date: str,
) -> list[Any]:
    with queries.get_connection() as connection:
        return connection.execute(
            """SELECT i.transaction_date, i.amount_minor, i.direction, i.currency,
                      i.identity_id, t.category, t.payment_mode, t.description
               FROM ingested_transaction_identities i
               JOIN transaction_general_ledger t
                 ON t.transaction_id=i.transaction_id
               WHERE i.business_id=? AND i.account_id=?
                 AND i.transaction_date BETWEEN ? AND ?
               ORDER BY i.transaction_date, i.identity_id""",
            (business_id, account_id, start_date, end_date),
        ).fetchall()


def _empty_trends() -> dict[str, list[dict[str, Any]]]:
    return {"daily": [], "weekly": [], "monthly": []}


def _trend_row(period: str, rows: list[Any]) -> dict[str, Any]:
    income = sum(row["amount_minor"] for row in rows if row["direction"] == "income")
    expense = sum(row["amount_minor"] for row in rows if row["direction"] == "expense")
    return {
        "period": period,
        "income_minor": income,
        "expense_minor": expense,
        "net_cash_flow_minor": income - expense,
        "transaction_count": len(rows),
    }


def _build_trends(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    if not rows:
        return _empty_trends()

    daily_groups: dict[str, list[Any]] = defaultdict(list)
    weekly_groups: dict[str, list[Any]] = defaultdict(list)
    monthly_groups: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        transaction_date = date.fromisoformat(row["transaction_date"])
        day = transaction_date.isoformat()
        week = f"{transaction_date:%G}-W{transaction_date:%V}"
        month = transaction_date.strftime("%Y-%m")
        daily_groups[day].append(row)
        weekly_groups[week].append(row)
        monthly_groups[month].append(row)

    return {
        "daily": [_trend_row(period, daily_groups[period]) for period in sorted(daily_groups)],
        "weekly": [_trend_row(period, weekly_groups[period]) for period in sorted(weekly_groups)],
        "monthly": [
            _trend_row(period, monthly_groups[period])
            for period in sorted(monthly_groups)
        ],
    }


def _build_category_summary(rows: list[Any]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = row["category"] or "Uncategorized"
        group = groups.setdefault(
            category,
            {
                "income_minor": 0,
                "expense_minor": 0,
                "income_count": 0,
                "expense_count": 0,
                "count": 0,
            },
        )
        direction = row["direction"]
        group["count"] += 1
        group[f"{direction}_count"] += 1
        group[f"{direction}_minor"] += row["amount_minor"]

    total_income = sum(
        row["amount_minor"] for row in rows if row["direction"] == "income"
    )
    total_expense = sum(
        row["amount_minor"] for row in rows if row["direction"] == "expense"
    )
    total_amount = total_income + total_expense
    result = []
    for category, group in groups.items():
        amount = group["income_minor"] + group["expense_minor"]
        result.append(
            {
                "category": category,
                "income_minor": group["income_minor"],
                "expense_minor": group["expense_minor"],
                "amount_minor": amount,
                "income_count": group["income_count"],
                "expense_count": group["expense_count"],
                "count": group["count"],
                "income_percentage": _percentage(
                    group["income_minor"], total_income
                ),
                "expense_percentage": _percentage(
                    group["expense_minor"], total_expense
                ),
                "percentage": _percentage(amount, total_amount),
            }
        )
    return sorted(result, key=lambda item: (-item["amount_minor"], item["category"]))


_PAYMENT_MODE_ORDER = {
    mode: index
    for index, mode in enumerate(("Cash", "UPI", "Card", "Bank", "Other"))
}


def _build_payment_mode_summary(rows: list[Any]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        payment_mode = row["payment_mode"]
        if payment_mode not in _PAYMENT_MODE_ORDER:
            payment_mode = "Other"
        group = groups.setdefault(
            payment_mode,
            {
                "income_minor": 0,
                "expense_minor": 0,
                "income_count": 0,
                "expense_count": 0,
                "count": 0,
            },
        )
        direction = row["direction"]
        group["count"] += 1
        group[f"{direction}_count"] += 1
        group[f"{direction}_minor"] += row["amount_minor"]

    total_income = sum(
        row["amount_minor"] for row in rows if row["direction"] == "income"
    )
    total_expense = sum(
        row["amount_minor"] for row in rows if row["direction"] == "expense"
    )
    total_amount = total_income + total_expense
    result = []
    for payment_mode, group in groups.items():
        amount = group["income_minor"] + group["expense_minor"]
        result.append(
            {
                "payment_mode": payment_mode,
                "income_minor": group["income_minor"],
                "expense_minor": group["expense_minor"],
                "amount_minor": amount,
                "income_count": group["income_count"],
                "expense_count": group["expense_count"],
                "count": group["count"],
                "income_percentage": _percentage(
                    group["income_minor"], total_income
                ),
                "expense_percentage": _percentage(
                    group["expense_minor"], total_expense
                ),
                "percentage": _percentage(amount, total_amount),
            }
        )
    return sorted(result, key=lambda item: _PAYMENT_MODE_ORDER[item["payment_mode"]])


def _build_account_summary(
    account_id: str, account: Any, rows: list[Any]
) -> list[dict[str, Any]]:
    if not rows:
        return []
    income = sum(row["amount_minor"] for row in rows if row["direction"] == "income")
    expense = sum(row["amount_minor"] for row in rows if row["direction"] == "expense")
    net = income - expense
    opening = account["opening_balance_minor"]
    return [
        {
            "account_id": account_id,
            "opening_balance_minor": opening,
            "closing_balance_minor": opening + net if opening is not None else None,
            "total_income_minor": income,
            "total_expense_minor": expense,
            "net_cash_flow_minor": net,
            "transaction_count": len(rows),
        }
    ]


def _build_transaction_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Expose only non-sensitive accepted fields for downstream read-only analysis."""
    result = []
    for row in rows:
        item = {
            "transaction_date": row["transaction_date"],
            "amount_minor": row["amount_minor"],
            "direction": row["direction"],
            "category": row["category"],
            "payment_mode": row["payment_mode"],
        }
        # Description was added for the final-submission UI, but older callers/tests
        # may provide rows that predate that optional field. Preserve the legacy
        # response shape unless the source row actually exposes description.
        if "description" in row.keys():
            item["description"] = row["description"]
        result.append(item)
    return result



def get_transaction_date_bounds(
    *,
    session_token: str,
    business_id: str,
    account_id: str,
    currency: str,
) -> dict[str, str | None]:
    """Return the accepted transaction date bounds for one authorized account."""
    _require_authorized_session(session_token, business_id)
    _load_account(account_id, business_id, currency)
    row = queries.get_ingested_transaction_date_bounds(business_id, account_id)
    return {
        "start_date": None if row is None else row["min_date"],
        "end_date": None if row is None else row["max_date"],
    }

def get_financial_analytics(
    *,
    session_token: str,
    business_id: str,
    account_id: str,
    start_date: str,
    end_date: str,
    currency: str,
) -> dict[str, Any]:
    """Return KPI aggregates without modifying any FinSight data."""
    _require_authorized_session(session_token, business_id)
    start_date, end_date = _validate_date_range(start_date, end_date)
    account = _load_account(account_id, business_id, currency)
    rows = _load_accepted_rows(
        business_id=business_id,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
    )
    if any(row["currency"] != currency for row in rows):
        raise AnalyticsError("The selected analytics currency is inconsistent.")

    incomes = [row["amount_minor"] for row in rows if row["direction"] == "income"]
    expenses = [row["amount_minor"] for row in rows if row["direction"] == "expense"]
    total_income = sum(incomes)
    total_expense = sum(expenses)
    transaction_count = len(rows)
    opening_balance = account["opening_balance_minor"]

    return {
        "kpis": {
            "total_income_minor": total_income,
            "total_expense_minor": total_expense,
            "net_cash_flow_minor": total_income - total_expense,
            "transaction_count": transaction_count,
            "average_transaction_minor": (
                Decimal(total_income + total_expense) / Decimal(transaction_count)
                if transaction_count
                else Decimal("0")
            ),
            "largest_income_minor": max(incomes) if incomes else None,
            "smallest_income_minor": min(incomes) if incomes else None,
            "largest_expense_minor": max(expenses) if expenses else None,
            "smallest_expense_minor": min(expenses) if expenses else None,
            "opening_balance_minor": opening_balance,
            "closing_balance_minor": (
                opening_balance + total_income - total_expense
                if opening_balance is not None
                else None
            ),
            "expense_to_income_ratio": (
                (Decimal(total_expense) / Decimal(total_income)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if total_income
                else None
            ),
            "income_expense_ratio": (
                (Decimal(total_income) / Decimal(total_expense)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if total_expense
                else None
            ),
            "savings_rate": _percentage(total_income - total_expense, total_income),
        },
        "trends": _build_trends(rows),
        "categories": _build_category_summary(rows),
        "payment_modes": _build_payment_mode_summary(rows),
        "accounts": _build_account_summary(account_id, account, rows),
        "transactions": _build_transaction_rows(rows),
    }


__all__ = ["AnalyticsError", "get_financial_analytics", "get_transaction_date_bounds"]
