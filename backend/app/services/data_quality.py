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

RULES_CATALOG = {
    "missing_value": "Campos requeridos faltantes",
    "missing_optional": "Campos operativos opcionales faltantes",
    "duplicate_order_id": "IDs de orden duplicados",
    "invalid_price": "Precio inválido",
    "invalid_quantity": "Cantidad inválida",
    "invalid_stock": "Stock negativo",
    "invalid_address": "Dirección inválida",
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


def _profile(domain: str | None) -> Dict[str, Any]:
    if not domain:
        return DOMAIN_PROFILES["ecommerce-logistica"]
    return DOMAIN_PROFILES.get(domain, DOMAIN_PROFILES["ecommerce-logistica"])


def _active_rules(domain: str | None, disabled: set[str]) -> list[str]:
    rules = DOMAIN_RULES.get(domain or "ecommerce-logistica", [])
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

    for row in records:
        order_id = (row.get("order_id") or "").strip()
        if "missing_value" in active_rules:
            if not order_id:
                invalid_values.append({"code": "missing_order_id", "row": row})
        if "duplicate_order_id" in active_rules:
            if order_id:
                if order_id in seen_orders:
                    duplicate_order_ids += 1
                else:
                    seen_orders.add(order_id)

        status = (row.get("status") or "").strip()

        for field in required_fields:
            if field == "delivered_at" and status != "delivered":
                continue
            value = (row.get(field) or "").strip()
            if not value and "missing_value" in active_rules:
                missing_by_field[field] += 1

        for field in optional_fields:
            if field in row:
                value = (row.get(field) or "").strip()
                if not value and "missing_optional" in active_rules:
                    optional_missing[field] += 1

        price = _to_float(row.get("price", ""))
        if (price is None or price <= 0) and "invalid_price" in active_rules:
            invalid_values.append({"code": "invalid_price", "row": row})

        quantity = _to_int(row.get("quantity", ""))
        if (quantity is None or quantity <= 0) and "invalid_quantity" in active_rules:
            invalid_values.append({"code": "invalid_quantity", "row": row})

        stock = _to_int(row.get("stock", ""))
        if (stock is None or stock < 0) and "invalid_stock" in active_rules:
            invalid_values.append({"code": "invalid_stock", "row": row})

        address = (row.get("address") or "").strip()
        if len(address) < 6 and "invalid_address" in active_rules:
            invalid_values.append({"code": "invalid_address", "row": row})

        postal_code = (row.get("postal_code") or "").strip()
        if (
            postal_code
            and not postal_code.replace("-", "").isdigit()
            and "invalid_postal_code" in active_rules
        ):
            invalid_values.append({"code": "invalid_postal_code", "row": row})

        shipped_at = _parse_date(row.get("shipped_at", ""))
        delivered_at = _parse_date(row.get("delivered_at", ""))
        if status and status not in STATUSES:
            if "invalid_status" in active_rules:
                invalid_values.append({"code": "invalid_status", "row": row})
        if status == "delivered" and delivered_at is None and "invalid_delivery_time" in active_rules:
            invalid_values.append({"code": "missing_delivered_at", "row": row})
        if (
            shipped_at
            and delivered_at
            and delivered_at < shipped_at
            and "invalid_delivery_time" in active_rules
        ):
            invalid_values.append({"code": "invalid_delivery_time", "row": row})

        weight = _to_float(row.get("weight_kg", ""))
        if (weight is None or weight <= 0) and "invalid_weight" in active_rules:
            invalid_values.append({"code": "invalid_weight", "row": row})

        lead_time = _to_int(row.get("lead_time_days", ""))
        if (
            lead_time is not None
            and (lead_time < 0 or lead_time > 21)
            and "invalid_lead_time" in active_rules
        ):
            invalid_values.append({"code": "invalid_lead_time", "row": row})

        delivery_window = (row.get("delivery_window") or "").strip()
        if (
            delivery_window
            and delivery_window not in DELIVERY_WINDOWS
            and "invalid_delivery_window" in active_rules
        ):
            invalid_values.append({"code": "invalid_delivery_window", "row": row})

        address_valid = (row.get("address_valid") or "").strip().lower()
        if (
            address_valid
            and address_valid not in {"true", "false", "1", "0"}
            and "invalid_address_flag" in active_rules
        ):
            invalid_values.append({"code": "invalid_address_flag", "row": row})
        if (
            address_valid in {"false", "0"}
            and len(address) >= 6
            and "address_flag_mismatch" in active_rules
        ):
            invalid_values.append({"code": "address_flag_mismatch", "row": row})

        channel = (row.get("channel") or "").strip()
        if channel and channel not in CHANNELS and "invalid_channel" in active_rules:
            invalid_values.append({"code": "invalid_channel", "row": row})

        payment_method = (row.get("payment_method") or "").strip()
        if (
            payment_method
            and payment_method not in PAYMENT_METHODS
            and "invalid_payment_method" in active_rules
        ):
            invalid_values.append({"code": "invalid_payment_method", "row": row})

        service_level = (row.get("service_level") or "").strip()
        if (
            service_level
            and service_level not in SERVICE_LEVELS
            and "invalid_service_level" in active_rules
        ):
            invalid_values.append({"code": "invalid_service_level", "row": row})

        discount = _to_float(row.get("discount_pct", ""))
        if (
            discount is not None
            and (discount < 0 or discount > 60)
            and "invalid_discount" in active_rules
        ):
            invalid_values.append({"code": "invalid_discount", "row": row})

    issues: List[Dict[str, Any]] = []
    for field, count in missing_by_field.items():
        if count:
            issues.append({
                "code": "missing_value",
                "field": field,
                "count": count,
                "severity": "high" if field in {"address", "postal_code", "order_id"} else "medium",
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
            "severity": "high"
            if code in {"invalid_address", "invalid_price", "invalid_delivery_time"}
            else "medium",
        })

    summary = {
        "total_rows": total,
        "missing_by_field": missing_by_field,
        "issue_count": len(issues),
        "domain_profile": domain or "ecommerce-logistica",
        "active_rule_ids": active_rules,
        "active_rules": [RULES_CATALOG.get(rule, rule) for rule in active_rules],
    }
    return summary, issues


def run_anomaly_detection(
    records: List[Dict[str, Any]],
    domain: str | None = None,
    disabled_rules: List[str] | None = None,
) -> Dict[str, Any]:
    def values_for(field: str) -> List[float]:
        values = []
        for row in records:
            value = _to_float(row.get(field, ""))
            if value is not None:
                values.append(value)
        return values

    def zscore(value: float, mean: float, stdev: float) -> float:
        if stdev == 0:
            return 0.0
        return (value - mean) / stdev

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
    for field in fields:
        values = values_for(field)
        if len(values) < 5:
            continue
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        for row in records:
            raw_value = _to_float(row.get(field, ""))
            if raw_value is None:
                continue
            score = zscore(raw_value, mean, stdev)
            if abs(score) >= 3:
                anomalies.append({
                    "field": field,
                    "value": raw_value,
                    "score": round(score, 2),
                    "order_id": row.get("order_id"),
                })

    return {
        "anomaly_count": len(anomalies),
        "anomalies": anomalies[:50],
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
