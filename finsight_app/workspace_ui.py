"""Authenticated business workspace UI built on FinSight backend services."""

from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
from services.rag.dashboard_context import remember

from services import (
    account_service,
    analytics_service,
    business_health_service,
    business_service,
    decision_support_service,
)

ALL_START = "2000-01-01"
ALL_END = "2099-12-31"
_EXPECTED_ANOMALY_ENGINE_VERSION = "finsight_tukey_outer_v1"


def _money(minor: Any, currency: str = "INR") -> str:
    if minor is None:
        return "N/A"
    try:
        value = Decimal(str(minor)) / Decimal(100)
    except Exception:
        return "N/A"
    prefix = "₹" if currency == "INR" else f"{currency} "
    return f"{prefix}{value:,.2f}"


def _value(value: Any, *, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value}{suffix}"


def _business_account(st: Any, token: str, business_id: str):
    ready = business_service.ensure_business_ready(token, business_id)
    if not isinstance(ready, dict) or ready.get("success") is not True:
        st.error(
            ready.get("message", "The selected business could not be prepared.")
            if isinstance(ready, dict)
            else "The selected business could not be prepared."
        )
        return None
    result = account_service.list_business_accounts(token, business_id)
    accounts = result.get("accounts", []) if isinstance(result, dict) and result.get("success") else []
    account = next(
        (item for item in accounts if item.get("account_id") == ready.get("account_id")),
        None,
    )
    if account is None:
        st.error("The internal business account is unavailable.")
        return None
    return account


def load_business_analytics(st: Any, token: str, business_id: str):
    account = _business_account(st, token, business_id)
    if account is None:
        return None, None
    try:
        result = analytics_service.get_financial_analytics(
            session_token=token,
            business_id=business_id,
            account_id=account["account_id"],
            start_date=ALL_START,
            end_date=ALL_END,
            currency=account["currency"],
        )
    except analytics_service.AnalyticsError:
        st.error("Financial analytics could not be loaded for this business.")
        return account, None
    except Exception:
        st.error("Financial analytics could not be loaded for this business.")
        return account, None
    remember(st, business_id, analysis=result, currency=account["currency"])
    return account, result


def render_overview(st: Any, token: str, business: dict[str, Any]) -> bool:
    account, analysis = load_business_analytics(st, token, business["business_id"])
    if account is None or analysis is None:
        return False
    kpis = analysis.get("kpis", {})
    currency = account["currency"]
    count = int(kpis.get("transaction_count", 0) or 0)

    st.subheader("Overview")
    st.caption(f"Financial overview for {business['business_name']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Income", _money(kpis.get("total_income_minor", 0), currency))
    c2.metric("Total Expenses", _money(kpis.get("total_expense_minor", 0), currency))
    c3.metric("Net Cash Flow", _money(kpis.get("net_cash_flow_minor", 0), currency))
    c4.metric("Transactions", count)

    if count == 0:
        st.info(
            "No transaction data available. Upload transactions to begin financial analysis."
        )
        if st.button("Upload Transactions", type="primary"):
            st.session_state["pending_page"] = "Upload Transactions"
            st.rerun()
        return True

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Average Transaction", _money(kpis.get("average_transaction_minor"), currency))
    c6.metric("Largest Income", _money(kpis.get("largest_income_minor"), currency))
    c7.metric("Largest Expense", _money(kpis.get("largest_expense_minor"), currency))
    c8.metric("Savings Rate", _value(kpis.get("savings_rate"), suffix="%"))

    ratio = kpis.get("income_expense_ratio")
    if ratio is not None:
        try:
            formatted_ratio = f"{float(Decimal(str(ratio))):.2f}"
        except Exception:
            formatted_ratio = str(ratio)
        st.caption(f"Income / Expense Ratio: {formatted_ratio}")

    trends = analysis.get("trends", {})
    monthly = trends.get("monthly", []) if isinstance(trends, dict) else []
    if monthly:
        chart = pd.DataFrame([
            {
                "Month": row["period"],
                "Income": float(Decimal(row.get("income_minor", 0)) / 100),
                "Expenses": float(Decimal(row.get("expense_minor", 0)) / 100),
                "Net Cash Flow": float(Decimal(row.get("net_cash_flow_minor", 0)) / 100),
            }
            for row in monthly
        ]).set_index("Month")
        st.subheader("Income, Expenses & Cash Flow")
        st.line_chart(chart, width="stretch")

    categories = analysis.get("categories", [])
    if categories:
        expense = pd.DataFrame([
            {
                "Category": row.get("category") or "Uncategorized",
                "Expenses": float(Decimal(row.get("expense_minor", 0)) / 100),
            }
            for row in categories
            if row.get("expense_minor", 0)
        ])
        if not expense.empty:
            st.subheader("Expenses by Category")
            st.bar_chart(expense.set_index("Category"), width="stretch")

    payment_modes = analysis.get("payment_modes", [])
    if payment_modes:
        modes = pd.DataFrame([
            {
                "Payment Mode": row.get("payment_mode") or "Other",
                "Income": float(Decimal(row.get("income_minor", 0)) / 100),
                "Expenses": float(Decimal(row.get("expense_minor", 0)) / 100),
            }
            for row in payment_modes
        ])
        if not modes.empty:
            st.subheader("Payment Mode Distribution")
            st.bar_chart(modes.set_index("Payment Mode"), width="stretch")
    return True


def render_transactions(st: Any, token: str, business: dict[str, Any]) -> bool:
    account, analysis = load_business_analytics(st, token, business["business_id"])
    if account is None or analysis is None:
        return False
    rows = analysis.get("transactions", [])
    st.subheader("Transactions")
    if not rows:
        st.info("No transaction data available for this business.")
        return True

    frame = pd.DataFrame([
        {
            "Date": row.get("transaction_date"),
            "Description": row.get("description") or "",
            "Direction": str(row.get("direction") or "").title(),
            "Category": row.get("category") or "Uncategorized",
            "Payment Mode": row.get("payment_mode") or "Other",
            "Amount": float(Decimal(row.get("amount_minor", 0)) / 100),
        }
        for row in rows
    ])
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.date
    min_date, max_date = frame["Date"].min(), frame["Date"].max()

    f1, f2, f3 = st.columns(3)
    direction = f1.selectbox("Direction", ["All", "Income", "Expense"])
    categories = ["All"] + sorted(frame["Category"].dropna().unique().tolist())
    category = f2.selectbox("Category", categories)
    modes = ["All"] + sorted(frame["Payment Mode"].dropna().unique().tolist())
    payment_mode = f3.selectbox("Payment Mode", modes)
    start, end = st.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    filtered = frame[(frame["Date"] >= start) & (frame["Date"] <= end)]
    if direction != "All":
        filtered = filtered[filtered["Direction"] == direction]
    if category != "All":
        filtered = filtered[filtered["Category"] == category]
    if payment_mode != "All":
        filtered = filtered[filtered["Payment Mode"] == payment_mode]
    st.dataframe(
        filtered,
        hide_index=True,
        width="stretch",
        column_config={"Amount": st.column_config.NumberColumn("Amount (₹)", format="₹ %.2f")},
    )
    return True


def _health_context(st: Any, token: str, business: dict[str, Any]):
    account = _business_account(st, token, business["business_id"])
    if account is None:
        return None, None
    args = {
        "session_token": token,
        "business_id": business["business_id"],
        "account_id": account["account_id"],
        "start_date": ALL_START,
        "end_date": ALL_END,
        "currency": account["currency"],
    }
    try:
        health = business_health_service.get_business_health(**args)
    except Exception:
        st.error("Business health could not be loaded for this business.")
        return args, None
    if (
        not isinstance(health, dict)
        or health.get("anomaly_engine_version") != _EXPECTED_ANOMALY_ENGINE_VERSION
    ):
        st.error(
            "The anomaly analysis runtime is out of date. Restart FinSight from "
            "the current fix-reports-calculations-anomalies branch."
        )
        return args, None
    remember(st, business["business_id"], health=health, currency=args["currency"])
    return args, health


def render_business_health(st: Any, token: str, business: dict[str, Any]) -> bool:
    _args, health = _health_context(st, token, business)
    if health is None:
        return False
    metrics = health.get("metrics", {})
    count = int(metrics.get("transaction_count", 0) or 0)
    st.subheader("Business Health")
    if count == 0:
        st.info("Business health will become available after transaction data is uploaded.")
        return True

    c1, c2, c3 = st.columns(3)
    c1.metric("Health Score", metrics.get("health_score", "N/A"))
    c2.metric("Health Level", metrics.get("health_level", "N/A"))
    c3.metric("Savings Rate", _value(metrics.get("savings_rate"), suffix="%"))
    st.markdown("#### What the indicators mean")
    indicators = [
        ("Expense-to-Income Ratio", metrics.get("expense_to_income_ratio"),
         "How much recorded income is consumed by expenses."),
        ("Cash Flow Stability", metrics.get("cash_flow_stability"),
         "How consistently cash flow behaves across the available periods."),
        ("Category Concentration", metrics.get("category_concentration"),
         "How strongly activity is concentrated in the largest category."),
        ("Recurring Expense Burden", metrics.get("recurring_expense_burden"),
         "The share of expenses identified as recurring by FinSight's deterministic rules."),
    ]
    for label, value, explanation in indicators:
        with st.container(border=True):
            st.markdown(f"**{label}:** {_value(value)}")
            st.caption(explanation)
    return True


_ANOMALY_TITLES = {
    "unusually_large_income": "Unusually Large Income",
    "unusually_large_expense": "Unusually Large Expense",
    "negative_cash_flow_period": "Negative Daily Cash Flow",
    "repeated_identical_transactions": "Repeated Transaction Pattern",
    "unexpected_payment_mode": "Unusual Payment Mode",
    "category_spike": "Category Spike",
    "recurring_expense_growth": "Recurring Expense Growth",
    "very_high_recurring_expenses": "High Recurring Expense Burden",
}

_ANOMALY_GROUPS = (
    (
        "Unusually Large Transactions",
        {"unusually_large_income", "unusually_large_expense"},
    ),
    (
        "Cash Flow Warnings",
        {
            "negative_cash_flow_period",
            "sudden_expense_spike",
            "expense_explosion",
            "sudden_income_drop",
            "income_interruption",
            "high_expense_ratio",
            "cash_flow_instability",
            "inactive_period",
        },
    ),
    (
        "Repeated / Payment Patterns",
        {"repeated_identical_transactions", "unexpected_payment_mode"},
    ),
    (
        "Category / Recurring Expense Changes",
        {
            "category_spike",
            "recurring_expense_growth",
            "very_high_recurring_expenses",
        },
    ),
)


def _anomaly_title(item: dict[str, Any]) -> str:
    anomaly_type = str(item.get("type") or "anomaly")
    return _ANOMALY_TITLES.get(
        anomaly_type,
        anomaly_type.replace("_", " ").title(),
    )


def _anomaly_group(item: dict[str, Any]) -> str:
    anomaly_type = str(item.get("type") or "")
    for label, types in _ANOMALY_GROUPS:
        if anomaly_type in types:
            return label
    return "Other Findings"


def _render_anomaly_card(st: Any, item: dict[str, Any], currency: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{_anomaly_title(item)}**")
        st.caption(f"Severity: {str(item.get('severity', 'N/A')).title()}")
        st.write(
            item.get("explanation")
            or item.get("reason")
            or "This pattern requires review."
        )

        affected = item.get("affected_transaction")
        if isinstance(affected, dict):
            if affected.get("amount_minor") is not None:
                st.write("Amount:", _money(affected["amount_minor"], currency))
            if affected.get("date"):
                st.write("Affected date:", affected["date"])
            if affected.get("description"):
                st.write("Description:", affected["description"])
            if affected.get("category"):
                st.write("Category:", affected["category"])
            if affected.get("payment_mode"):
                st.write("Payment mode:", affected["payment_mode"])

        context = item.get("detection_context")
        context = context if isinstance(context, dict) else {}
        if context.get("category") and (
            not isinstance(affected, dict)
            or context["category"] != affected.get("category")
        ):
            st.write("Category:", context["category"])
        if context.get("payment_mode") and (
            not isinstance(affected, dict)
            or context["payment_mode"] != affected.get("payment_mode")
        ):
            st.write("Payment mode:", context["payment_mode"])
        if context.get("occurrence_count"):
            st.write("Occurrences:", context["occurrence_count"])
            st.write(
                "Observed dates:",
                f"{context.get('first_date', 'N/A')} to {context.get('last_date', 'N/A')}",
            )

        affected_period = item.get("affected_period")
        affected_date = affected.get("date") if isinstance(affected, dict) else None
        if affected_period and affected_period != affected_date:
            period_label = (
                "Affected day"
                if context.get("period_kind") == "daily"
                else "Affected period"
            )
            st.write(f"{period_label}:", affected_period)

        reference = item.get("transaction_reference")
        if reference and not (isinstance(affected, dict) and affected.get("description")):
            st.write("Reference:", reference)

        st.write(
            "Suggested review action: Review the underlying transactions and supporting records."
        )


def render_anomalies(st: Any, token: str, business: dict[str, Any]) -> bool:
    args, health = _health_context(st, token, business)
    if health is None:
        return False
    count = int(health.get("metrics", {}).get("transaction_count", 0) or 0)
    st.subheader("Anomalies")
    if count == 0:
        st.info("Anomaly analysis will become available after transaction data is uploaded.")
        return True

    anomalies = [
        item for item in health.get("anomalies", [])
        if isinstance(item, dict)
    ]
    if not anomalies:
        st.success("No significant anomalies were detected for the selected period.")
        return True

    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for item in anomalies:
        severity = str(item.get("severity") or "").upper()
        if severity in severity_counts:
            severity_counts[severity] += 1

    st.markdown("#### Anomaly Summary")
    summary_columns = st.columns(4)
    summary_columns[0].metric("Total Findings", len(anomalies))
    summary_columns[1].metric(
        "High / Critical",
        severity_counts["HIGH"] + severity_counts["CRITICAL"],
    )
    summary_columns[2].metric("Medium", severity_counts["MEDIUM"])
    summary_columns[3].metric("Low", severity_counts["LOW"])

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in anomalies:
        grouped.setdefault(_anomaly_group(item), []).append(item)

    ordered_labels = [label for label, _types in _ANOMALY_GROUPS]
    ordered_labels.extend(
        label for label in grouped
        if label not in ordered_labels
    )
    currency = str((args or {}).get("currency") or "INR")
    for label in ordered_labels:
        findings = grouped.get(label, [])
        if not findings:
            continue
        with st.expander(f"{label} ({len(findings)})", expanded=False):
            for item in findings:
                _render_anomaly_card(st, item, currency)
    return True

def render_recommendations(st: Any, token: str, business: dict[str, Any]) -> bool:
    args, health = _health_context(st, token, business)
    if health is None or args is None:
        return False
    count = int(health.get("metrics", {}).get("transaction_count", 0) or 0)
    st.subheader("Recommendations")
    if count == 0:
        st.info("Recommendations will appear after sufficient transaction data is available.")
        return True
    try:
        support = decision_support_service.get_decision_support(**args)
    except Exception:
        st.error("Recommendations could not be loaded for this business.")
        return False
    recommendations = support.get("recommendations", [])
    remember(st, business["business_id"], support=support)
    if not recommendations:
        st.info("No specific recommendations were generated for the available data.")
        return True
    for item in recommendations:
        with st.container(border=True):
            st.markdown(f"**{item.get('title', 'Recommendation')}**")
            st.caption(f"Priority: {item.get('priority', 'N/A')}")
            st.write(item.get("explanation") or item.get("reason") or "")
            if item.get("recommended_action"):
                st.write("Suggested action:", item["recommended_action"])
    return True
