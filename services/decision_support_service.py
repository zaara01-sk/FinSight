"""Deterministic, read-only recommendations based on Modules 5–7 outputs."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from services import (
    analytics_service,
    business_health_service,
    business_service,
    report_service,
)


class DecisionSupportError(ValueError):
    """Safe error raised when decision support cannot be produced."""


_PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_ANOMALY_RULES = {
    "negative_cash_flow": (
        "Cash Flow",
        "Address negative cash flow",
        "HIGH",
        "HIGH",
        "Review spending and restore positive cash flow.",
    ),
    "negative_cash_flow_period": (
        "Cash Flow",
        "Address negative cash flow",
        "HIGH",
        "HIGH",
        "Review spending and restore positive cash flow.",
    ),
    "high_expense_ratio": (
        "Expense",
        "Reduce the expense burden",
        "HIGH",
        "HIGH",
        "Reduce discretionary spending and review major costs.",
    ),
    "income_drop": (
        "Income",
        "Investigate income decline",
        "HIGH",
        "HIGH",
        "Increase sales activity and review the causes of the decline.",
    ),
    "sudden_income_drop": (
        "Income",
        "Investigate income decline",
        "HIGH",
        "HIGH",
        "Increase sales activity and review the causes of the decline.",
    ),
    "income_interruption": (
        "Income",
        "Restore income continuity",
        "CRITICAL",
        "CRITICAL",
        "Investigate the interruption and restore reliable income activity.",
    ),
    "expense_explosion": (
        "Expense",
        "Investigate expense explosion",
        "CRITICAL",
        "CRITICAL",
        "Investigate the expense increase and pause avoidable spending.",
    ),
    "sudden_expense_spike": (
        "Expense",
        "Investigate expense spike",
        "HIGH",
        "HIGH",
        "Review the affected period and reduce discretionary spending.",
    ),
    "large_transaction": (
        "Risk",
        "Review the large transaction",
        "HIGH",
        "HIGH",
        "Investigate the large payment before approving similar activity.",
    ),
    "unusually_large_income": (
        "Risk",
        "Review the large transaction",
        "MEDIUM",
        "MEDIUM",
        "Verify the unusual income and retain supporting records.",
    ),
    "unusually_large_expense": (
        "Risk",
        "Review the large transaction",
        "HIGH",
        "HIGH",
        "Investigate the large payment before approving similar activity.",
    ),
    "category_spike": (
        "Category Spending",
        "Monitor category spending",
        "HIGH",
        "HIGH",
        "Monitor the affected category and reduce avoidable costs.",
    ),
    "recurring_expense_growth": (
        "Expense",
        "Review recurring expenses",
        "HIGH",
        "HIGH",
        "Review recurring subscriptions and renegotiate fixed costs.",
    ),
    "very_high_recurring_expenses": (
        "Expense",
        "Review recurring expenses",
        "HIGH",
        "HIGH",
        "Review recurring subscriptions and renegotiate fixed costs.",
    ),
    "payment_mode_change": (
        "Payment Behaviour",
        "Verify payment behaviour",
        "MEDIUM",
        "MEDIUM",
        "Verify the unusual payment pattern and monitor future activity.",
    ),
    "unexpected_payment_mode": (
        "Payment Behaviour",
        "Verify payment behaviour",
        "MEDIUM",
        "MEDIUM",
        "Verify the unusual payment pattern and monitor future activity.",
    ),
    "duplicate_pattern": (
        "Risk",
        "Verify repeated transactions",
        "MEDIUM",
        "MEDIUM",
        "Verify repeated entries and investigate suspicious behaviour.",
    ),
    "repeated_identical_transactions": (
        "Risk",
        "Verify repeated transactions",
        "MEDIUM",
        "MEDIUM",
        "Verify repeated entries and investigate suspicious behaviour.",
    ),
    "inactive_period": (
        "Operational",
        "Review inactive activity",
        "LOW",
        "LOW",
        "Review the inactive period and confirm that operations are continuing.",
    ),
    "inactive_business": (
        "Operational",
        "Review inactive activity",
        "LOW",
        "LOW",
        "Review the inactive period and confirm that operations are continuing.",
    ),
    "cash_flow_instability": (
        "Business Health",
        "Stabilize cash flow",
        "HIGH",
        "HIGH",
        "Reduce volatility by monitoring inflows and planned outflows.",
    ),
}


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return default


def _validate_date_range(start_date: Any, end_date: Any) -> tuple[str, str]:
    if type(start_date) is not str or type(end_date) is not str:
        raise DecisionSupportError("The decision-support date range is invalid.")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as error:
        raise DecisionSupportError(
            "The decision-support date range is invalid."
        ) from error
    if start > end:
        raise DecisionSupportError("The decision-support date range is invalid.")
    return start.isoformat(), end.isoformat()


def _timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if type(value) is str and value:
        return value
    raise DecisionSupportError("The decision-support timestamp is invalid.")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _safe_access(session_token: Any, business_id: Any) -> str:
    try:
        access = business_service.require_business_access(
            session_token,
            business_id,
            {"owner", "manager"},
        )
    except Exception as error:
        raise DecisionSupportError("The selected business is unavailable.") from error
    if not isinstance(access, dict) or access.get("success") is not True:
        raise DecisionSupportError(
            "You do not have permission to view recommendations."
        )
    business = access.get("business")
    membership = access.get("membership")
    if (
        not isinstance(business, dict)
        or business.get("business_status") != "active"
        or not isinstance(membership, dict)
        or membership.get("membership_status") != "active"
        or membership.get("membership_role") not in {"owner", "manager"}
        or type(business.get("business_name")) is not str
        or not business["business_name"].strip()
    ):
        raise DecisionSupportError(
            "You do not have permission to view recommendations."
        )
    return business["business_name"]


def _metrics(health: dict[str, Any]) -> dict[str, Any]:
    value = health.get("metrics")
    return value if isinstance(value, dict) else {}


def _kpis(analytics: dict[str, Any]) -> dict[str, Any]:
    value = analytics.get("kpis")
    return value if isinstance(value, dict) else {}


def _recommendation(
    *,
    category: str,
    title: str,
    priority: str,
    severity: str,
    confidence: int,
    reason: str,
    explanation: str,
    supporting_metrics: dict[str, Any],
    recommended_action: str,
    business_id: str,
    account_id: Any,
    date_generated: str,
) -> dict[str, Any]:
    recommendation = {
        "title": title,
        "category": category,
        "priority": priority,
        "severity": severity,
        "confidence": confidence,
        "reason": reason,
        "explanation": explanation,
        "supporting_metrics": supporting_metrics,
        "recommended_action": recommended_action,
        "business_id": business_id,
        "date_generated": date_generated,
    }
    if account_id is not None:
        recommendation["account_id"] = account_id
    return recommendation


def _add(
    recommendations: list[dict[str, Any]],
    recommendation: dict[str, Any],
) -> None:
    key = (recommendation["category"], recommendation["title"])
    if any((item["category"], item["title"]) == key for item in recommendations):
        return
    recommendations.append(recommendation)


def _rule_recommendations(
    *,
    analytics: dict[str, Any],
    health: dict[str, Any],
    business_id: str,
    account_id: Any,
    date_generated: str,
) -> list[dict[str, Any]]:
    kpis = _kpis(analytics)
    metrics = _metrics(health)
    recommendations: list[dict[str, Any]] = []
    income = _decimal(kpis.get("total_income_minor"))
    expense = _decimal(kpis.get("total_expense_minor"))
    net = _decimal(kpis.get("net_cash_flow_minor"), income - expense)
    count = int(_decimal(kpis.get("transaction_count")))
    ratio_value = metrics.get("expense_to_income_ratio")
    ratio = _decimal(ratio_value) if ratio_value is not None else None
    savings_value = metrics.get("savings_rate", kpis.get("savings_rate"))
    savings = _decimal(savings_value) if savings_value is not None else None
    concentration = _decimal(metrics.get("category_concentration"))
    recurring = _decimal(metrics.get("recurring_expense_burden"))
    stability = _decimal(metrics.get("cash_flow_stability"))
    monthly_growth = _decimal(
        metrics.get("monthly_growth", metrics.get("income_trend"))
    )
    monthly_decline = _decimal(
        metrics.get("monthly_decline"),
    )
    if monthly_decline == 0 and _decimal(metrics.get("income_trend")) < 0:
        monthly_decline = abs(_decimal(metrics.get("income_trend")))
    reserve = metrics.get("cash_reserve_estimate_minor")
    if reserve is None:
        reserve = kpis.get("closing_balance_minor")

    if net < 0:
        priority = (
            "CRITICAL"
            if (income == 0 and expense > 0)
            or (ratio is not None and ratio > 1)
            else "HIGH"
        )
        _add(
            recommendations,
            _recommendation(
                category="Cash Flow",
                title="Address negative cash flow",
                priority=priority,
                severity=priority,
                confidence=95,
                reason="Net cash flow is below zero in the selected period.",
                explanation=(
                    f"Net cash flow of {net} minor units is negative; "
                    "cash outflows exceed inflows. Review spending and restore "
                    "positive cash flow."
                ),
                supporting_metrics={"net_cash_flow_minor": net, "threshold": 0},
                recommended_action="Review spending and restore positive cash flow.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if ratio is not None and ratio > Decimal("1.00"):
        priority = "CRITICAL"
    elif ratio is not None and ratio > Decimal("0.75"):
        priority = "HIGH"
    else:
        priority = ""
    if priority:
        _add(
            recommendations,
            _recommendation(
                category="Expense",
                title="Reduce the expense burden",
                priority=priority,
                severity=priority,
                confidence=93,
                reason="The expense-to-income ratio exceeds the safe threshold.",
                explanation=(
                    f"Expenses consume {ratio} times recorded income; the "
                    "expense-to-income ratio triggered the 0.75 threshold. "
                    "Reduce discretionary spending and review major costs."
                ),
                supporting_metrics={
                    "expense_to_income_ratio": ratio,
                    "threshold": Decimal("0.75"),
                },
                recommended_action=(
                    "Reduce discretionary spending and review major costs."
                ),
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if savings is not None and savings < Decimal("20.00") and count:
        _add(
            recommendations,
            _recommendation(
                category="Savings",
                title="Create a savings buffer",
                priority="HIGH" if savings < 0 else "MEDIUM",
                severity="HIGH" if savings < 0 else "MEDIUM",
                confidence=90,
                reason="The savings rate is below the 20 percent target.",
                explanation=(
                    f"The savings rate is {savings} percent, below the 20 percent "
                    "threshold. Allocate more inflows to a cash buffer."
                ),
                supporting_metrics={
                    "savings_rate": savings,
                    "threshold": Decimal("20.00"),
                },
                recommended_action="Increase the cash reserve from future inflows.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if monthly_decline > Decimal("20.00"):
        _add(
            recommendations,
            _recommendation(
                category="Income",
                title="Investigate income decline",
                priority="HIGH",
                severity="HIGH",
                confidence=90,
                reason="Income declined by more than 20 percent between periods.",
                explanation=(
                    f"Income decline of {monthly_decline} percent exceeded the "
                    "20 percent threshold. Increase sales activity and review "
                    "the causes of the decline."
                ),
                supporting_metrics={
                    "monthly_decline": monthly_decline,
                    "threshold": Decimal("20.00"),
                },
                recommended_action="Increase sales activity and review the decline.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if monthly_growth > Decimal("10.00"):
        _add(
            recommendations,
            _recommendation(
                category="Growth",
                title="Maintain positive income growth",
                priority="LOW",
                severity="LOW",
                confidence=88,
                reason=(
                    "Income growth exceeded the 10 percent positive-trend threshold."
                ),
                explanation=(
                    f"Income grew by {monthly_growth} percent, above the 10 percent "
                    "threshold. Maintain the current sales trend."
                ),
                supporting_metrics={
                    "monthly_growth": monthly_growth,
                    "threshold": Decimal("10.00"),
                },
                recommended_action="Maintain the current sales trend.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if concentration > Decimal("60.00"):
        _add(
            recommendations,
            _recommendation(
                category="Category Spending",
                title="Monitor category concentration",
                priority="HIGH",
                severity="HIGH",
                confidence=89,
                reason="One category accounts for more than 60 percent of activity.",
                explanation=(
                    f"Category concentration is {concentration} percent, above the "
                    "60 percent threshold. Monitor the category and reduce "
                    "avoidable costs."
                ),
                supporting_metrics={
                    "category_concentration": concentration,
                    "threshold": Decimal("60.00"),
                },
                recommended_action="Monitor category spending and diversify exposure.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if recurring > Decimal("50.00"):
        _add(
            recommendations,
            _recommendation(
                category="Expense",
                title="Review recurring expenses",
                priority="HIGH",
                severity="HIGH",
                confidence=92,
                reason="Recurring expenses consume more than half of total expenses.",
                explanation=(
                    f"Recurring expenses represent {recurring} percent of expenses, "
                    "above the 50 percent threshold. Review recurring subscriptions "
                    "and fixed costs."
                ),
                supporting_metrics={
                    "recurring_expense_burden": recurring,
                    "threshold": Decimal("50.00"),
                },
                recommended_action="Review recurring subscriptions and fixed costs.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if reserve is not None and expense > 0 and _decimal(reserve) < expense:
        _add(
            recommendations,
            _recommendation(
                category="Risk",
                title="Increase the cash reserve",
                priority="HIGH",
                severity="HIGH",
                confidence=91,
                reason="The estimated cash reserve is below one period of expenses.",
                explanation=(
                    f"The reserve is {_decimal(reserve)} minor units against "
                    f"{expense} minor units of expenses, below the one-period "
                    "reserve threshold. Increase the cash reserve."
                ),
                supporting_metrics={
                    "cash_reserve_estimate_minor": _decimal(reserve),
                    "expense_threshold_minor": expense,
                },
                recommended_action="Increase the cash reserve from future inflows.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if stability < Decimal("50.00") and count:
        _add(
            recommendations,
            _recommendation(
                category="Business Health",
                title="Stabilize cash flow",
                priority="HIGH",
                severity="HIGH",
                confidence=87,
                reason="Cash-flow stability is below 50 percent.",
                explanation=(
                    f"Only {stability} percent of observed periods had stable cash "
                    "flow, below the 50 percent threshold. Reduce volatility."
                ),
                supporting_metrics={
                    "cash_flow_stability": stability,
                    "threshold": Decimal("50.00"),
                },
                recommended_action="Monitor inflows and plan outflows more closely.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if (
        monthly_growth > Decimal("10.00")
        and stability >= Decimal("75.00")
        and str(metrics.get("health_level")) in {"Excellent", "Good"}
    ):
        _add(
            recommendations,
            _recommendation(
                category="Business Health",
                title="Maintain the positive trend",
                priority="LOW",
                severity="LOW",
                confidence=86,
                reason="Growth and cash-flow stability are both positive.",
                explanation=(
                    f"Income growth is {monthly_growth} percent and cash-flow "
                    f"stability "
                    f"is {stability} percent. Maintain the current trend."
                ),
                supporting_metrics={
                    "monthly_growth": monthly_growth,
                    "cash_flow_stability": stability,
                },
                recommended_action=(
                    "Maintain the current trend and continue monitoring."
                ),
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    if (
        str(metrics.get("health_level")) == "Stable"
        and net >= 0
        and ratio <= Decimal("0.75")
        and savings >= Decimal("20.00")
        and stability >= Decimal("75.00")
    ):
        _add(
            recommendations,
            _recommendation(
                category="Business Health",
                title="Maintain stable operations",
                priority="LOW",
                severity="LOW",
                confidence=85,
                reason="The business has stable cash flow and controlled expenses.",
                explanation=(
                    f"Cash-flow stability is {stability} percent, the expense-to-income "
                    f"ratio is {ratio}, and the savings rate is {savings} percent. "
                    "Maintain the current operating discipline."
                ),
                supporting_metrics={
                    "cash_flow_stability": stability,
                    "expense_to_income_ratio": ratio,
                    "savings_rate": savings,
                },
                recommended_action="Maintain current controls and continue monitoring.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )

    payment_modes = analytics.get("payment_modes")
    if isinstance(payment_modes, list):
        for mode in payment_modes:
            if not isinstance(mode, dict):
                continue
            percentage = _decimal(mode.get("percentage"))
            if percentage > Decimal("80.00"):
                name = str(mode.get("payment_mode") or "one payment mode")
                _add(
                    recommendations,
                    _recommendation(
                        category="Payment Behaviour",
                        title="Monitor payment-mode concentration",
                        priority="MEDIUM",
                        severity="MEDIUM",
                        confidence=84,
                        reason="A single payment mode exceeds 80 percent of activity.",
                        explanation=(
                            f"{name} represents {percentage} percent of activity, "
                            "above the 80 percent concentration threshold."
                        ),
                        supporting_metrics={
                            "payment_mode": name,
                            "percentage": percentage,
                            "threshold": Decimal("80.00"),
                        },
                        recommended_action=(
                            "Monitor payment behaviour and maintain alternatives."
                        ),
                        business_id=business_id,
                        account_id=account_id,
                        date_generated=date_generated,
                    ),
                )
                break

    return recommendations


def _anomaly_recommendations(
    *,
    health: dict[str, Any],
    business_id: str,
    account_id: Any,
    date_generated: str,
) -> list[dict[str, Any]]:
    anomalies = health.get("anomalies")
    if not isinstance(anomalies, list):
        return []
    recommendations: list[dict[str, Any]] = []
    for anomaly in anomalies:
        if not isinstance(anomaly, dict):
            continue
        anomaly_type = str(anomaly.get("type") or "").lower()
        rule = _ANOMALY_RULES.get(anomaly_type)
        if rule is None:
            continue
        category, title, default_priority, default_severity, action = rule
        severity = str(anomaly.get("severity") or default_severity).upper()
        if severity not in _SEVERITY_ORDER:
            severity = default_severity
        priority = min(
            (severity, default_priority),
            key=lambda value: _PRIORITY_ORDER[value],
        )
        metric_value = anomaly.get("metric_value")
        threshold = anomaly.get("threshold")
        date_detected = anomaly.get("date_detected") or anomaly.get("date")
        _add(
            recommendations,
            _recommendation(
                category=category,
                title=title,
                priority=priority,
                severity=severity,
                confidence=95 if severity == "CRITICAL" else 88,
                reason=(
                    f"The {anomaly_type.replace('_', ' ')} anomaly was detected "
                    "by the health service."
                ),
                explanation=(
                    f"The health service detected {anomaly_type.replace('_', ' ')} "
                    f"with metric value {metric_value} against threshold {threshold}. "
                    f"{action}"
                ),
                supporting_metrics={
                    "anomaly_type": anomaly_type,
                    "metric_value": metric_value,
                    "threshold": threshold,
                    "affected_period": date_detected,
                },
                recommended_action=action,
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )
    if len(anomalies) >= 2:
        _add(
            recommendations,
            _recommendation(
                category="Risk",
                title="Review multiple anomalies",
                priority="HIGH",
                severity="HIGH",
                confidence=90,
                reason="Multiple deterministic anomalies were reported in the period.",
                explanation=(
                    f"The health service reported {len(anomalies)} anomalies. "
                    "Review the affected metrics together and verify "
                    "suspicious behaviour."
                ),
                supporting_metrics={
                    "anomaly_count": len(anomalies),
                    "threshold": 2,
                },
                recommended_action="Review the affected metrics together.",
                business_id=business_id,
                account_id=account_id,
                date_generated=date_generated,
            ),
        )
    return recommendations


def _finalize(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Deduplicate across combined recommendations by category and normalized title
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rec in recommendations:
        key = (str(rec.get("category", "")).lower().strip(), str(rec.get("title", "")).lower().strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rec)

    ordered = sorted(
        deduped,
        key=lambda item: (
            _PRIORITY_ORDER.get(item.get("priority", "MEDIUM"), 2),
            _SEVERITY_ORDER.get(item.get("severity", "MEDIUM"), 2),
            item.get("category", ""),
            item.get("title", ""),
        ),
    )
    for index, recommendation in enumerate(ordered, start=1):
        recommendation["id"] = f"recommendation-{index:03d}"
        ordered[index - 1] = {
            "id": recommendation["id"],
            **{
                key: recommendation[key]
                for key in (
                    "title",
                    "category",
                    "priority",
                    "severity",
                    "confidence",
                    "reason",
                    "explanation",
                    "supporting_metrics",
                    "recommended_action",
                    "business_id",
                    "account_id",
                    "date_generated",
                )
                if key in recommendation
            },
        }
    return ordered


def get_decision_support(
    *,
    session_token: str,
    business_id: str,
    account_id: str | None,
    start_date: str,
    end_date: str,
    currency: str,
    generated_at: Any = None,
) -> dict[str, Any]:
    """Return deterministic recommendations for an authorized business scope."""
    start_date, end_date = _validate_date_range(start_date, end_date)
    if type(currency) is not str or len(currency) != 3 or currency != currency.upper():
        raise DecisionSupportError("The decision-support currency is invalid.")
    business_name = _safe_access(session_token, business_id)
    timestamp = _timestamp(generated_at)
    service_args = {
        "session_token": session_token,
        "business_id": business_id,
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "currency": currency,
    }
    try:
        analytics = analytics_service.get_financial_analytics(**service_args)
    except Exception as error:
        raise DecisionSupportError(
            "Decision support data could not be loaded."
        ) from error
    try:
        health = business_health_service.get_business_health(**service_args)
    except Exception as error:
        raise DecisionSupportError(
            "Business health data could not be loaded."
        ) from error
    try:
        report = report_service.build_report(
            **service_args,
            generated_at=timestamp,
        )
    except Exception as error:
        raise DecisionSupportError(
            "The executive report could not be loaded."
        ) from error
    if not (
        isinstance(analytics, dict)
        and isinstance(health, dict)
        and isinstance(report, dict)
    ):
        raise DecisionSupportError("Decision support data could not be loaded.")

    kpis = _kpis(analytics)
    total_count = int(_decimal(kpis.get("transaction_count")))
    anomalies = health.get("anomalies")
    has_anomalies = isinstance(anomalies, list) and bool(anomalies)
    recommendations: list[dict[str, Any]] = []
    if total_count or has_anomalies:
        recommendations.extend(
            _rule_recommendations(
                analytics=analytics,
                health=health,
                business_id=business_id,
                account_id=account_id,
                date_generated=timestamp,
            )
        )
        recommendations.extend(
            _anomaly_recommendations(
                health=health,
                business_id=business_id,
                account_id=account_id,
                date_generated=timestamp,
            )
        )
    recommendations = _finalize(recommendations)
    result = {
        "business": {"name": business_name},
        "date_range": {"start_date": start_date, "end_date": end_date},
        "currency": currency,
        "generated_at": timestamp,
        "recommendations": recommendations,
        "summary": {
            "recommendation_count": len(recommendations),
            "highest_priority": (
                recommendations[0]["priority"] if recommendations else None
            ),
        },
    }
    return _json_ready(result)


generate_recommendations = get_decision_support
build_decision_support = get_decision_support
get_recommendations = get_decision_support


__all__ = [
    "DecisionSupportError",
    "build_decision_support",
    "generate_recommendations",
    "get_decision_support",
    "get_recommendations",
]
