import csv
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_FIELDS = [
    "order_id",
    "customer_id",
    "sku",
    "price",
    "quantity",
    "stock",
]

LOGISTICS_FIELDS = [
    "address",
    "city",
    "postal_code",
    "warehouse",
    "shipping_provider",
    "service_level",
    "delivery_window",
    "lead_time_days",
    "shipped_at",
    "delivered_at",
    "status",
    "weight_kg",
]

ECOMMERCE_FIELDS = [
    "address",
    "city",
    "postal_code",
    "channel",
    "payment_method",
    "discount_pct",
]

OPTIONAL_FIELDS = [
    "warehouse",
    "delivery_window",
    "lead_time_days",
    "address_valid",
    "service_level",
    "channel",
    "payment_method",
    "discount_pct",
]

DELIVERY_WINDOWS = {"09-13", "13-17", "17-21"}
CHANNELS = {"web", "app", "marketplace", "b2b"}
PAYMENT_METHODS = {"card", "transfer", "cash", "wallet"}
SERVICE_LEVELS = {"standard", "express", "same_day"}
STATUSES = {"delivered", "in_transit", "canceled", "delayed", "returned"}

# Expected type of every known column, declared once.
#
# Until now this knowledge was implicit in the rule bodies: `price` was numeric
# because `_to_float` happened to be called on it. Stating it here lets the
# schema check reuse exactly the same expectations the rules enforce, instead
# of maintaining a second, drifting definition.
#
#   number      -> must parse as a float
#   integer     -> must parse as a whole number
#   date        -> must parse as an ISO timestamp
#   category    -> must belong to the declared set
#   boolean     -> true/false/1/0
#   text        -> anything (not type checked)
CATEGORY_VALUES: dict[str, set[str]] = {
    "delivery_window": DELIVERY_WINDOWS,
    "channel": CHANNELS,
    "payment_method": PAYMENT_METHODS,
    "service_level": SERVICE_LEVELS,
    "status": STATUSES,
}

FIELD_TYPES: dict[str, str] = {
    "order_id": "text",
    "customer_id": "text",
    "sku": "text",
    "price": "number",
    "quantity": "integer",
    "stock": "integer",
    "weight_kg": "number",
    "lead_time_days": "integer",
    "discount_pct": "number",
    "shipped_at": "date",
    "delivered_at": "date",
    "address": "text",
    "city": "text",
    "postal_code": "text",
    "warehouse": "text",
    "shipping_provider": "text",
    "address_valid": "boolean",
    "delivery_window": "category",
    "channel": "category",
    "payment_method": "category",
    "service_level": "category",
    "status": "category",
}

# The row identity. Without it there is no way to tell rows apart, deduplicate
# them, or tie a finding back to a record, so a CSV lacking it is not a dataset
# of this domain regardless of what else it carries.
IDENTITY_FIELD = "order_id"

RULES_CATALOG = {
    "missing_value": "Campos requeridos faltantes",
    "missing_optional": "Campos operativos opcionales faltantes",
    "duplicate_order_id": "IDs de orden duplicados",
    "invalid_price": "Precio inválido",
    "invalid_quantity": "Cantidad inválida",
    "invalid_stock": "Stock negativo",
    "invalid_address": "Dirección sin calle o sin numeración",
    "invalid_postal_code": "Código postal inválido",
    "invalid_delivery_time": "Delivery time inconsistente",
    "invalid_weight": "Peso inválido",
    "invalid_lead_time": "Lead time fuera de rango",
    "invalid_delivery_window": "Ventana de entrega inválida",
    "invalid_address_flag": "Flag de dirección inválido",
    "address_flag_mismatch": "Flag de dirección inconsistente",
    "invalid_channel": "Canal inválido",
    "invalid_payment_method": "Medio de pago inválido",
    "invalid_service_level": "Service level inválido",
    "invalid_discount": "Descuento fuera de rango",
    "invalid_status": "Estado de envío inválido",
    "anomaly_price": "Anomalía de precio",
    "anomaly_weight_kg": "Anomalía de peso",
    "anomaly_lead_time_days": "Anomalía de lead time",
    "anomaly_quantity": "Anomalía de cantidad",
    "anomaly_stock": "Anomalía de stock",
    "anomaly_discount_pct": "Anomalía de descuento",
}

DOMAIN_PROFILES = {
    "ecommerce": {
        "required": BASE_FIELDS + ECOMMERCE_FIELDS,
        "optional": [
            "warehouse",
            "delivery_window",
            "lead_time_days",
            "service_level",
            "shipping_provider",
            "weight_kg",
            "address_valid",
            "status",
            "shipped_at",
            "delivered_at",
        ],
        "anomaly_fields": ["price", "quantity", "discount_pct", "stock"],
        "rules": [
            "missing_value",
            "missing_optional",
            "duplicate_order_id",
            "invalid_price",
            "invalid_quantity",
            "invalid_stock",
            "invalid_address",
            "invalid_postal_code",
            "invalid_channel",
            "invalid_payment_method",
            "invalid_discount",
            "anomaly_price",
            "anomaly_quantity",
            "anomaly_discount_pct",
            "anomaly_stock",
        ],
    },
    "logistica": {
        "required": BASE_FIELDS + LOGISTICS_FIELDS,
        "optional": ["channel", "payment_method", "discount_pct", "address_valid"],
        "anomaly_fields": ["weight_kg", "lead_time_days", "stock", "quantity"],
        "rules": [
            "missing_value",
            "missing_optional",
            "duplicate_order_id",
            "invalid_stock",
            "invalid_address",
            "invalid_postal_code",
            "invalid_delivery_time",
            "invalid_weight",
            "invalid_lead_time",
            "invalid_delivery_window",
            "invalid_service_level",
            "invalid_status",
            "anomaly_weight_kg",
            "anomaly_lead_time_days",
            "anomaly_stock",
            "anomaly_quantity",
        ],
    },
    "ecommerce-logistica": {
        "required": BASE_FIELDS
        + [
            "address",
            "city",
            "postal_code",
            "warehouse",
            "shipping_provider",
            "service_level",
            "delivery_window",
            "lead_time_days",
            "status",
            "shipped_at",
            "channel",
            "payment_method",
            "weight_kg",
        ],
        "optional": ["discount_pct", "address_valid", "delivered_at"],
        "anomaly_fields": [
            "price",
            "weight_kg",
            "lead_time_days",
            "quantity",
            "stock",
            "discount_pct",
        ],
        "rules": [
            "missing_value",
            "missing_optional",
            "duplicate_order_id",
            "invalid_price",
            "invalid_quantity",
            "invalid_stock",
            "invalid_address",
            "invalid_postal_code",
            "invalid_delivery_time",
            "invalid_weight",
            "invalid_lead_time",
            "invalid_delivery_window",
            "invalid_channel",
            "invalid_payment_method",
            "invalid_discount",
            "invalid_status",
            "anomaly_price",
            "anomaly_weight_kg",
            "anomaly_lead_time_days",
            "anomaly_quantity",
            "anomaly_stock",
            "anomaly_discount_pct",
        ],
    },
}

DOMAIN_RULES = {key: value["rules"] for key, value in DOMAIN_PROFILES.items()}

# Used when a caller does not specify a domain at all.
DEFAULT_DOMAIN = "ecommerce-logistica"


# Severity is a declared business policy, not a derived number: these findings
# block fulfilment, so they are the ones worth fixing first. Kept in one place
# because both the per-row scan and the issue list need the same answer.
HIGH_SEVERITY_CODES = {
    "invalid_address",
    "invalid_price",
    "invalid_delivery_time",
    "missing_delivered_at",
    "duplicate_order_id",
}
HIGH_SEVERITY_MISSING_FIELDS = {"order_id", "address", "postal_code"}
LOW_SEVERITY_CODES = {"missing_optional"}


def severity_for(code: str, field: str | None = None) -> str:
    """Severity of a single finding."""
    if code in LOW_SEVERITY_CODES:
        return "low"
    if code == "missing_value":
        return "high" if field in HIGH_SEVERITY_MISSING_FIELDS else "medium"
    return "high" if code in HIGH_SEVERITY_CODES else "medium"


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _to_int(value: str) -> int | None:
    try:
        return int(float(value))
    except Exception:
        return None


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def load_records(file_path: str) -> List[Dict[str, Any]]:
    with Path(file_path).open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


class UnknownDomainError(ValueError):
    """A domain was requested that has no rule profile."""


def _profile(domain: str | None) -> Dict[str, Any]:
    """Resolve a domain to its profile.

    ``None`` means "not specified" and resolves to the default profile, which
    is the documented behaviour of the callers' optional argument. An unknown
    *name*, however, is a bug or a stale value: silently analysing it against
    the wrong column set produced results that looked valid and were not, so
    it raises instead.
    """
    if domain is None:
        return DOMAIN_PROFILES[DEFAULT_DOMAIN]
    profile = DOMAIN_PROFILES.get(domain)
    if profile is None:
        known = ", ".join(sorted(DOMAIN_PROFILES))
        raise UnknownDomainError(f"Dominio desconocido: {domain!r}. Conocidos: {known}")
    return profile


def _active_rules(domain: str | None, disabled: set[str]) -> list[str]:
    # Goes through _profile so an unknown domain raises here too, instead of
    # quietly producing an empty rule list and an all-clear result.
    rules = _profile(domain)["rules"]
    return [rule for rule in rules if rule not in disabled]


def run_quality_checks(
    records: List[Dict[str, Any]],
    domain: str | None = None,
    disabled_rules: List[str] | None = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    total = len(records)
    profile = _profile(domain)
    required_fields = profile["required"]
    optional_fields = profile["optional"]
    disabled = set(disabled_rules or [])
    active_rules = _active_rules(domain, disabled)
    missing_by_field = {field: 0 for field in required_fields}
    invalid_values: List[Dict[str, Any]] = []
    duplicate_order_ids = 0
    seen_orders: set[str] = set()
    optional_missing = {field: 0 for field in optional_fields}

    # Row-level bookkeeping. A row can break several rules, so counting
    # findings tells you nothing about how much of the dataset is actually
    # damaged. These sets answer that: how many distinct rows failed at least
    # one rule, and how many failed a high severity one.
    affected_rows: set[int] = set()
    critical_rows: set[int] = set()

    def flag(index: int, code: str, row_data: Dict[str, Any], field: str | None = None) -> None:
        invalid_values.append({"code": code, "row": row_data})
        affected_rows.add(index)
        if severity_for(code, field) == "high":
            critical_rows.add(index)

    def mark(index: int, code: str, field: str | None = None) -> None:
        """Record a row as affected without adding to the invalid_values list.

        Used by the aggregated counters (missing_by_field, optional_missing,
        duplicates) which build their issue entries separately.
        """
        affected_rows.add(index)
        if severity_for(code, field) == "high":
            critical_rows.add(index)

    for index, row in enumerate(records):
        order_id = (row.get("order_id") or "").strip()
        # An empty order_id is reported once, by the generic missing_value
        # rule below (order_id is a required field of every profile). There
        # used to be a `missing_order_id` finding here as well, which counted
        # the same condition on the same rows a second time.
        if "duplicate_order_id" in active_rules:
            if order_id:
                if order_id in seen_orders:
                    duplicate_order_ids += 1
                    mark(index, "duplicate_order_id")
                else:
                    seen_orders.add(order_id)

        status = (row.get("status") or "").strip()

        for field in required_fields:
            if field == "delivered_at" and status != "delivered":
                continue
            value = (row.get(field) or "").strip()
            if not value and "missing_value" in active_rules:
                missing_by_field[field] += 1
                mark(index, "missing_value", field)

        for field in optional_fields:
            if field in row:
                value = (row.get(field) or "").strip()
                if not value and "missing_optional" in active_rules:
                    optional_missing[field] += 1
                    mark(index, "missing_optional", field)

        price = _to_float(row.get("price", ""))
        if (price is None or price <= 0) and "invalid_price" in active_rules:
            flag(index, "invalid_price", row)

        quantity = _to_int(row.get("quantity", ""))
        if (quantity is None or quantity <= 0) and "invalid_quantity" in active_rules:
            flag(index, "invalid_quantity", row)

        stock = _to_int(row.get("stock", ""))
        if (stock is None or stock < 0) and "invalid_stock" in active_rules:
            flag(index, "invalid_stock", row)

        address = (row.get("address") or "").strip()
        # A street reference needs a street name and a street number, so it
        # must contain at least one letter and at least one digit. The rule
        # used to be `len(address) < 6`, which rejected legitimate short
        # addresses ("Av 9") while accepting incomplete ones ("Sarmiento",
        # nine characters and no number), and which fired on every empty
        # address on top of the missing_value rule that already reported it.
        # Emptiness is completeness, not validity, and is left to that rule.
        if address and "invalid_address" in active_rules:
            if not (any(c.isalpha() for c in address) and any(c.isdigit() for c in address)):
                flag(index, "invalid_address", row)

        postal_code = (row.get("postal_code") or "").strip()
        if (
            postal_code
            and not postal_code.replace("-", "").isdigit()
            and "invalid_postal_code" in active_rules
        ):
            flag(index, "invalid_postal_code", row)

        shipped_at = _parse_date(row.get("shipped_at", ""))
        delivered_at = _parse_date(row.get("delivered_at", ""))
        if status and status not in STATUSES:
            if "invalid_status" in active_rules:
                flag(index, "invalid_status", row)
        if status == "delivered" and delivered_at is None and "invalid_delivery_time" in active_rules:
            flag(index, "missing_delivered_at", row)
        if (
            shipped_at
            and delivered_at
            and delivered_at < shipped_at
            and "invalid_delivery_time" in active_rules
        ):
            flag(index, "invalid_delivery_time", row)

        weight = _to_float(row.get("weight_kg", ""))
        if (weight is None or weight <= 0) and "invalid_weight" in active_rules:
            flag(index, "invalid_weight", row)

        lead_time = _to_int(row.get("lead_time_days", ""))
        if (
            lead_time is not None
            and (lead_time < 0 or lead_time > 21)
            and "invalid_lead_time" in active_rules
        ):
            flag(index, "invalid_lead_time", row)

        delivery_window = (row.get("delivery_window") or "").strip()
        if (
            delivery_window
            and delivery_window not in DELIVERY_WINDOWS
            and "invalid_delivery_window" in active_rules
        ):
            flag(index, "invalid_delivery_window", row)

        address_valid = (row.get("address_valid") or "").strip().lower()
        if (
            address_valid
            and address_valid not in {"true", "false", "1", "0"}
            and "invalid_address_flag" in active_rules
        ):
            flag(index, "invalid_address_flag", row)
        if (
            address_valid in {"false", "0"}
            and len(address) >= 6
            and "address_flag_mismatch" in active_rules
        ):
            flag(index, "address_flag_mismatch", row)

        channel = (row.get("channel") or "").strip()
        if channel and channel not in CHANNELS and "invalid_channel" in active_rules:
            flag(index, "invalid_channel", row)

        payment_method = (row.get("payment_method") or "").strip()
        if (
            payment_method
            and payment_method not in PAYMENT_METHODS
            and "invalid_payment_method" in active_rules
        ):
            flag(index, "invalid_payment_method", row)

        service_level = (row.get("service_level") or "").strip()
        if (
            service_level
            and service_level not in SERVICE_LEVELS
            and "invalid_service_level" in active_rules
        ):
            flag(index, "invalid_service_level", row)

        discount = _to_float(row.get("discount_pct", ""))
        if (
            discount is not None
            and (discount < 0 or discount > 60)
            and "invalid_discount" in active_rules
        ):
            flag(index, "invalid_discount", row)

    issues: List[Dict[str, Any]] = []
    for field, count in missing_by_field.items():
        if count:
            issues.append({
                "code": "missing_value",
                "field": field,
                "count": count,
                "severity": severity_for("missing_value", field),
            })

    for field, count in optional_missing.items():
        if count:
            issues.append({
                "code": "missing_optional",
                "field": field,
                "count": count,
                "severity": "low",
            })

    if duplicate_order_ids:
        issues.append({
            "code": "duplicate_order_id",
            "count": duplicate_order_ids,
            "severity": "high",
        })

    invalid_counts: Dict[str, int] = {}
    for item in invalid_values:
        invalid_counts[item["code"]] = invalid_counts.get(item["code"], 0) + 1

    for code, count in invalid_counts.items():
        issues.append({
            "code": code,
            "count": count,
            "severity": severity_for(code),
        })

    summary = {
        "total_rows": total,
        "missing_by_field": missing_by_field,
        # Number of distinct findings, i.e. (rule, field) pairs that fired at
        # least once. NOT a row count.
        "issue_count": len(issues),
        # Total times any rule fired. A single row breaking three rules
        # contributes three. NOT a row count either.
        "rule_violations": sum(int(issue.get("count", 0) or 0) for issue in issues),
        # Distinct rows failing at least one active rule. Bounded by total_rows.
        "rows_affected": len(affected_rows),
        # Distinct rows failing at least one high severity rule.
        "critical_rows": len(critical_rows),
        "domain_profile": domain or "ecommerce-logistica",
        "active_rule_ids": active_rules,
        "active_rules": [RULES_CATALOG.get(rule, rule) for rule in active_rules],
    }
    return summary, issues


# Modified z-score threshold. 3.5 is the value recommended by Iglewicz and
# Hoaglin (1993), "How to Detect and Handle Outliers"; it is a published
# constant, not a number tuned until this project's demo data looked good.
ANOMALY_THRESHOLD = 3.5

# Consistency constants. 1.4826 makes the MAD an unbiased estimator of sigma
# for normally distributed data; 1.2533 does the same for the mean absolute
# deviation, used only when the MAD collapses to zero.
_MAD_SCALE = 1.4826
_MEANAD_SCALE = 1.2533

# Below this many values a centre and a spread cannot be estimated with any
# confidence, so the column is skipped rather than guessed at.
MIN_VALUES_FOR_ANOMALY = 12


def robust_scale(values: List[float], centre: float) -> float:
    """Spread of a sample, resistant to the outliers being looked for.

    The previous implementation used the standard deviation of the whole
    sample, including the outliers. With 12% contamination that inflated sigma
    enough for the outliers to fall inside their own threshold -- the classic
    masking effect. The MAD has a breakdown point of 50%, so it barely moves
    until half the data is contaminated.

    Falls back to the mean absolute deviation when more than half the values
    are identical (MAD = 0), and returns 0.0 for a constant column, which the
    caller treats as "nothing to measure".
    """
    deviations = [abs(value - centre) for value in values]
    mad = statistics.median(deviations)
    if mad > 0:
        return _MAD_SCALE * mad
    mean_ad = sum(deviations) / len(deviations)
    if mean_ad > 0:
        return _MEANAD_SCALE * mean_ad
    return 0.0


def run_anomaly_detection(
    records: List[Dict[str, Any]],
    domain: str | None = None,
    disabled_rules: List[str] | None = None,
    threshold: float = ANOMALY_THRESHOLD,
) -> Dict[str, Any]:
    """Flag numeric values that are far from the centre of their own column.

    This looks for values that are *legal but implausible*: a price of 6.000
    in a catalogue that runs 10 to 500 breaks no rule, yet is almost certainly
    a misplaced decimal point. Impossible values -- negative prices, negative
    stock -- are not outliers and are not reported here; the domain rules
    already reject them, and reporting them twice under two names would
    overstate how much is wrong.

    Uses the modified z-score: (value - median) / (1.4826 * MAD).
    """
    def values_for(field: str) -> List[float]:
        values = []
        for row in records:
            value = _to_float(row.get(field, ""))
            if value is not None:
                values.append(value)
        return values

    fields = _profile(domain)["anomaly_fields"]
    if disabled_rules:
        field_map = {
            "price": "anomaly_price",
            "weight_kg": "anomaly_weight_kg",
            "lead_time_days": "anomaly_lead_time_days",
            "quantity": "anomaly_quantity",
            "stock": "anomaly_stock",
            "discount_pct": "anomaly_discount_pct",
        }
        disabled_set = set(disabled_rules)
        fields = [
            field
            for field in fields
            if field_map.get(field, "") not in disabled_set
        ]

    anomalies: List[Dict[str, Any]] = []
    field_stats: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        values = values_for(field)
        if len(values) < MIN_VALUES_FOR_ANOMALY:
            continue
        centre = statistics.median(values)
        scale = robust_scale(values, centre)
        if scale <= 0:
            # Constant column: every value is the centre, nothing is far from it.
            continue
        field_stats[field] = {
            "median": round(centre, 4),
            "scale": round(scale, 4),
            "values_checked": len(values),
        }
        for row in records:
            raw_value = _to_float(row.get(field, ""))
            if raw_value is None:
                # Missing values are a completeness problem, owned by the
                # missing_value rules. A gap has no distance to a centre.
                continue
            score = (raw_value - centre) / scale
            if abs(score) >= threshold:
                anomalies.append({
                    "field": field,
                    "value": raw_value,
                    "score": round(score, 2),
                    "order_id": row.get("order_id"),
                })

    return {
        "anomaly_count": len(anomalies),
        "anomalies": anomalies[:50],
        "method": "modified_zscore_mad",
        "threshold": threshold,
        "fields_analyzed": field_stats,
    }


def _priority_for_issue(issue: Dict[str, Any]) -> str:
    severity = issue.get("severity")
    count = int(issue.get("count") or 0)
    if severity == "high" or count >= 120:
        return "alta"
    if severity == "medium" or count >= 50:
        return "media"
    return "baja"


def recommend_actions(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    recommendations = []
    mapping = {
        "missing_value": "Implementar validaciones en origen y bloquear carga cuando falten campos críticos.",
        "missing_optional": "Completar campos operativos para mejorar la trazabilidad logística.",
        "duplicate_order_id": "Revisar el sistema de IDs y activar deduplicación automática.",
        "invalid_price": "Agregar reglas de control de precios y alertas con umbrales.",
        "invalid_stock": "Conciliar stock con el ERP y activar alertas ante negativos.",
        "invalid_address": "Implementar autocompletado y verificación de direcciones.",
        "invalid_delivery_time": "Sincronizar eventos de tracking y validar timestamps.",
        "invalid_status": "Normalizar los estados de envío según el flujo operativo.",
        "invalid_lead_time": "Revisar promesas de entrega y tiempos de preparación en almacén.",
        "invalid_delivery_window": "Normalizar ventanas de entrega según la operación logística.",
        "invalid_channel": "Validar el canal de venta en el checkout o integraciones.",
        "invalid_payment_method": "Normalizar medios de pago aceptados y su codificación.",
        "invalid_discount": "Revisar reglas de promociones y descuentos aplicados.",
        "address_flag_mismatch": "Cruzar validación de direcciones con proveedor externo.",
    }
    for issue in issues:
        code = issue.get("code")
        text = mapping.get(code)
        if text:
            recommendations.append({
                "code": code,
                "label": RULES_CATALOG.get(code, code),
                "action": text,
                "severity": issue.get("severity"),
                "count": issue.get("count", 0),
                "priority": _priority_for_issue(issue),
            })
    return recommendations
