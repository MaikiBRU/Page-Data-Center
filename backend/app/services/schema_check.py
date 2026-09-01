"""Does this CSV actually belong to the selected domain?

The quality rules assume the columns of a domain profile exist. Handed a CSV
from somewhere else they still run, report every required field as missing on
every row, and produce a quality score of 0 — which reads as "your data is
terrible" when the truth is "this file was never this kind of data".

This module answers that question first, deterministically, from the profile
definitions that already exist in :mod:`app.services.data_quality`. No
inference, no learning: it compares column names against the profile and
samples values against the declared types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List

from app.services.data_quality import (
    CATEGORY_VALUES,
    DOMAIN_PROFILES,
    FIELD_TYPES,
    IDENTITY_FIELD,
    _profile,
)

# --- thresholds -------------------------------------------------------------
# All three are policy choices, kept here so they can be pointed at and
# argued about rather than buried in a condition.

# Share of the profile's required columns that must be present for the file to
# be treated as this kind of data at all. Below it, the rules would be
# measuring the absence of a schema rather than the quality of data.
MIN_REQUIRED_COVERAGE = 0.6

# Share of non-empty values in a typed column that may fail to parse before
# the column is reported as the wrong type. Above half means the column is not
# holding what its name claims.
MAX_INVALID_TYPE_RATIO = 0.5

# Rows sampled for type checking. Matches the preview sample so the two views
# agree, and keeps the check O(1) with respect to file size.
TYPE_SAMPLE_ROWS = 200

# A typed column needs at least this many non-empty values before a ratio is
# meaningful.
MIN_TYPED_VALUES = 5

STATUS_COMPATIBLE = "compatible"
STATUS_WARNING = "warning"
STATUS_INCOMPATIBLE = "incompatible"


@dataclass
class TypeMismatch:
    column: str
    expected: str
    checked: int
    invalid: int
    invalid_ratio: float
    samples: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "column": self.column,
            "expected": self.expected,
            "checked": self.checked,
            "invalid": self.invalid,
            "invalid_ratio": round(self.invalid_ratio, 3),
            "samples": self.samples,
        }


@dataclass
class SchemaReport:
    status: str
    domain: str
    columns_present: List[str]
    required_expected: List[str]
    missing_required: List[str]
    missing_optional: List[str]
    unexpected_columns: List[str]
    type_mismatches: List[TypeMismatch]
    required_coverage: float
    reasons: List[str]

    @property
    def is_incompatible(self) -> bool:
        return self.status == STATUS_INCOMPATIBLE

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "domain": self.domain,
            "columns_present": self.columns_present,
            "required_expected": self.required_expected,
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
            "unexpected_columns": self.unexpected_columns,
            "type_mismatches": [item.as_dict() for item in self.type_mismatches],
            "required_coverage": round(self.required_coverage, 3),
            "reasons": self.reasons,
        }


# --- value parsing ----------------------------------------------------------
# Deliberately the same notion of "parses" the rules use, so a value the rules
# would accept is never reported here as the wrong type.


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _is_integer(value: str) -> bool:
    try:
        number = float(value)
    except ValueError:
        return False
    return number == int(number)


def _is_date(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_boolean(value: str) -> bool:
    return value.strip().lower() in {"true", "false", "1", "0"}


def _value_matches(column: str, expected: str, value: str) -> bool:
    if expected == "number":
        return _is_number(value)
    if expected == "integer":
        return _is_integer(value)
    if expected == "date":
        return _is_date(value)
    if expected == "boolean":
        return _is_boolean(value)
    if expected == "category":
        allowed = CATEGORY_VALUES.get(column, set())
        return not allowed or value in allowed
    return True  # text


def _check_types(
    records: Iterable[Dict[str, Any]], columns: List[str], limit: int
) -> List[TypeMismatch]:
    """Sample values and report columns that do not hold what they claim."""
    typed = [col for col in columns if FIELD_TYPES.get(col, "text") != "text"]
    if not typed:
        return []

    checked: Dict[str, int] = {col: 0 for col in typed}
    invalid: Dict[str, int] = {col: 0 for col in typed}
    samples: Dict[str, List[str]] = {col: [] for col in typed}

    for index, row in enumerate(records):
        if index >= limit:
            break
        for col in typed:
            raw = row.get(col)
            value = "" if raw is None else str(raw).strip()
            if not value:
                # Emptiness is a quality problem, not a type problem. The
                # missing_value rules already own it.
                continue
            checked[col] += 1
            if not _value_matches(col, FIELD_TYPES[col], value):
                invalid[col] += 1
                if len(samples[col]) < 3 and value not in samples[col]:
                    samples[col].append(value[:40])

    mismatches: List[TypeMismatch] = []
    for col in typed:
        seen = checked[col]
        if seen < MIN_TYPED_VALUES:
            continue
        ratio = invalid[col] / seen
        if ratio > MAX_INVALID_TYPE_RATIO:
            mismatches.append(
                TypeMismatch(
                    column=col,
                    expected=FIELD_TYPES[col],
                    checked=seen,
                    invalid=invalid[col],
                    invalid_ratio=ratio,
                    samples=samples[col],
                )
            )
    return mismatches


# --- the check --------------------------------------------------------------


def check_schema(
    columns: Iterable[str] | None,
    records: Iterable[Dict[str, Any]] | None = None,
    domain: str | None = None,
    sample_rows: int = TYPE_SAMPLE_ROWS,
) -> SchemaReport:
    """Compare a CSV header (and a sample of its rows) against a domain profile.

    Verdict, in order:

    1. **incompatible** when the identity column is absent, or when fewer than
       ``MIN_REQUIRED_COVERAGE`` of the profile's required columns are present.
       Either way the file is not this kind of data and running the rules over
       it would only measure the mismatch.
    2. **warning** when it is recognisably the right kind of data but something
       is off: required columns missing, columns the profile does not know
       about, or a typed column holding values it cannot parse.
    3. **compatible** otherwise.
    """
    profile = _profile(domain)
    resolved_domain = domain if domain in DOMAIN_PROFILES else "ecommerce-logistica"

    present = [str(col).strip() for col in (columns or []) if str(col).strip()]
    present_set = set(present)

    required = list(profile["required"])
    optional = list(profile["optional"])
    known = set(required) | set(optional)

    missing_required = [col for col in required if col not in present_set]
    missing_optional = [col for col in optional if col not in present_set]
    unexpected = sorted(present_set - known)

    coverage = 1.0 if not required else (len(required) - len(missing_required)) / len(required)

    mismatches = _check_types(records or [], present, sample_rows) if records else []

    reasons: List[str] = []
    status = STATUS_COMPATIBLE

    if IDENTITY_FIELD not in present_set:
        status = STATUS_INCOMPATIBLE
        reasons.append(
            f"Falta la columna identificadora '{IDENTITY_FIELD}', "
            "necesaria para identificar y deduplicar registros."
        )
    if coverage < MIN_REQUIRED_COVERAGE:
        status = STATUS_INCOMPATIBLE
        reasons.append(
            f"Solo {len(required) - len(missing_required)} de {len(required)} columnas "
            f"requeridas estan presentes ({coverage:.0%}); el minimo es "
            f"{MIN_REQUIRED_COVERAGE:.0%}."
        )

    if status != STATUS_INCOMPATIBLE:
        if missing_required:
            status = STATUS_WARNING
            reasons.append(
                f"Faltan {len(missing_required)} columnas requeridas: "
                f"{', '.join(missing_required)}."
            )
        if unexpected:
            status = STATUS_WARNING
            reasons.append(
                f"Hay {len(unexpected)} columnas que el dominio no reconoce: "
                f"{', '.join(unexpected)}."
            )
        if mismatches:
            status = STATUS_WARNING
            for mismatch in mismatches:
                reasons.append(
                    f"La columna '{mismatch.column}' deberia ser de tipo "
                    f"{mismatch.expected} pero {mismatch.invalid} de {mismatch.checked} "
                    f"valores no lo son."
                )
        if status == STATUS_COMPATIBLE:
            reasons.append("El dataset coincide con el esquema del dominio.")

    return SchemaReport(
        status=status,
        domain=resolved_domain,
        columns_present=present,
        required_expected=required,
        missing_required=missing_required,
        missing_optional=missing_optional,
        unexpected_columns=unexpected,
        type_mismatches=mismatches,
        required_coverage=coverage,
        reasons=reasons,
    )
