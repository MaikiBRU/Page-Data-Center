import csv
import io
import random
from datetime import datetime, timedelta
from pathlib import Path

# Anchor for the generated timestamps. It used to be datetime.utcnow(), which
# meant two runs with the same seed produced different shipped_at and
# delivered_at values -- the dataset was only reproducible in its numeric
# columns. Callers that want dates relative to now pass reference_date
# explicitly; everything else gets a fixed anchor and a byte-identical file.
DEFAULT_REFERENCE_DATE = datetime(2026, 1, 1)

CITIES = ["Buenos Aires", "Cordoba", "Rosario", "Mendoza", "La Plata"]
STATUSES = ["delivered", "in_transit", "canceled", "delayed", "returned"]
PROVIDERS = ["Andreani", "Correo Argentino", "OCA", "Mercado Envios"]
WAREHOUSES = ["CABA-01", "BA-02", "ROS-01", "MDZ-01", "CBA-02"]
DELIVERY_WINDOWS = ["09-13", "13-17", "17-21"]
CHANNELS = ["web", "app", "marketplace", "b2b"]
PAYMENT_METHODS = ["card", "transfer", "cash", "wallet"]
SERVICE_LEVELS = ["standard", "express", "same_day"]


def _maybe_anomaly(rate: float) -> bool:
    return random.random() < rate


# Every deliberate perturbation the generator can apply, and which kind of
# defect it represents. "rule" faults are impossible values the domain rules
# already catch; "outlier" faults are values that are legal but statistically
# extreme, which is what the anomaly detector is for. Keeping the distinction
# explicit is what makes an honest evaluation possible.
INJECTION_KINDS: dict[str, str] = {
    "price_negative": "rule",
    "stock_negative": "rule",
    "address_missing": "rule",
    "delivered_before_shipped": "rule",
    "weight_zero": "rule",
    "warehouse_missing": "rule",
    "service_level_missing": "rule",
    "lead_time_out_of_range": "rule",
    "discount_out_of_range": "rule",
    "delivery_window_invalid": "rule",
    "channel_unknown": "rule",
    "payment_unknown": "rule",
}

# Numeric columns the anomaly detector monitors, and the injections that land
# in them. Used by the evaluation harness to build the ground truth.
#
# Note what these are: every one of them is an *impossible* value that the
# domain rules already reject (negative price, negative stock, zero weight,
# lead time outside 0..21, discount outside 0..60). They sit 1.4 to 1.6 robust
# deviations from the median, which is to say they are not statistically
# extreme at all. Measuring an outlier detector against them is measuring the
# wrong thing.
NUMERIC_INJECTIONS: dict[str, str] = {
    "price_negative": "price",
    "stock_negative": "stock",
    "weight_zero": "weight_kg",
    "lead_time_out_of_range": "lead_time_days",
    "discount_out_of_range": "discount_pct",
}

# Genuine statistical outliers: values that pass every domain rule but sit far
# outside the distribution of the column. This is the class of defect an
# outlier detector exists for and the one the dataset previously contained
# none of -- a price of 6.000 on a catalogue that runs 10 to 500 is perfectly
# legal and almost certainly a data entry error, and no rule will ever catch
# it. Ranges are chosen to be one to two orders of magnitude above the base
# distribution, which is what a misplaced decimal point or a unit mix-up looks
# like in practice.
OUTLIER_INJECTIONS: dict[str, str] = {
    "price_extreme": "price",
    "quantity_extreme": "quantity",
    "weight_extreme": "weight_kg",
    "stock_extreme": "stock",
    "discount_high": "discount_pct",
}


def generate_dataset(
    file_path: str,
    rows: int,
    anomaly_rate: float,
    seed: int = 42,
    outlier_rate: float | None = None,
    reference_date: datetime | None = None,
) -> None:
    """Write a synthetic dataset to disk (authenticated app path)."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        _write_dataset(
            handle, rows, anomaly_rate, seed, outlier_rate=outlier_rate,
            reference_date=reference_date,
        )


def generate_dataset_csv(
    rows: int,
    anomaly_rate: float,
    seed: int = 42,
    labels: list[dict] | None = None,
    outlier_rate: float | None = None,
    reference_date: datetime | None = None,
) -> str:
    """Build the same dataset in memory (demo sandbox path).

    Passing ``labels`` records, per row, which perturbations were applied. It
    is an instrument for evaluation only: the CSV produced is byte for byte
    the same whether or not it is supplied.
    """
    buffer = io.StringIO()
    _write_dataset(
        buffer, rows, anomaly_rate, seed, labels=labels, outlier_rate=outlier_rate,
        reference_date=reference_date,
    )
    return buffer.getvalue()


# Outliers default to a sixth of the rule fault rate: rare enough that the
# column still has a well defined centre, common enough to be visible in a
# few hundred rows.
OUTLIER_RATE_FRACTION = 1 / 6


def _write_dataset(
    handle,
    rows: int,
    anomaly_rate: float,
    seed: int = 42,
    labels: list[dict] | None = None,
    outlier_rate: float | None = None,
    reference_date: datetime | None = None,
) -> None:
    random.seed(seed)
    if outlier_rate is None:
        outlier_rate = anomaly_rate * OUTLIER_RATE_FRACTION
    headers = [
        "order_id",
        "customer_id",
        "sku",
        "price",
        "quantity",
        "stock",
        "warehouse",
        "address",
        "city",
        "postal_code",
        "address_valid",
        "shipped_at",
        "delivered_at",
        "delivery_window",
        "lead_time_days",
        "status",
        "shipping_provider",
        "service_level",
        "channel",
        "payment_method",
        "discount_pct",
        "weight_kg",
    ]

    base_date = (reference_date or DEFAULT_REFERENCE_DATE) - timedelta(days=30)

    writer = csv.writer(handle)
    writer.writerow(headers)
    for index in range(rows):
        # uuid4() reads os.urandom and ignores random.seed(), so the
        # identifiers changed on every run. Drawn from the seeded generator
        # instead; still unique within a dataset because the counter is
        # appended.
        order_id = f"{random.getrandbits(28):07x}{index:x}"
        customer_id = f"C{random.randint(1000, 9999)}"
        sku = f"SKU-{random.randint(100, 999)}"
        price = round(random.uniform(10, 500), 2)
        quantity = random.randint(1, 5)
        stock = random.randint(0, 200)
        warehouse = random.choice(WAREHOUSES)
        address = f"Calle {random.randint(10, 999)}"
        city = random.choice(CITIES)
        postal_code = str(random.randint(1000, 9999))
        shipped_at = base_date + timedelta(days=random.randint(0, 28))
        lead_time = random.randint(1, 7)
        delivered_at = shipped_at + timedelta(days=lead_time)
        status = random.choices(STATUSES, weights=[0.72, 0.15, 0.05, 0.05, 0.03], k=1)[0]
        provider = random.choice(PROVIDERS)
        service_level = random.choice(SERVICE_LEVELS)
        delivery_window = random.choice(DELIVERY_WINDOWS)
        channel = random.choices(CHANNELS, weights=[0.5, 0.2, 0.2, 0.1], k=1)[0]
        payment = random.choices(PAYMENT_METHODS, weights=[0.6, 0.2, 0.1, 0.1], k=1)[0]
        discount = round(random.uniform(0, 30), 2)
        weight = round(random.uniform(0.2, 15.0), 2)
        address_valid = "true"
        injected: list[str] = []

        if _maybe_anomaly(anomaly_rate):
            price = -abs(price)
            injected.append("price_negative")
        if _maybe_anomaly(anomaly_rate):
            stock = -random.randint(1, 10)
            injected.append("stock_negative")
        if _maybe_anomaly(anomaly_rate):
            address = ""
            address_valid = "false"
            injected.append("address_missing")
        if _maybe_anomaly(anomaly_rate):
            delivered_at = shipped_at - timedelta(days=2)
            injected.append("delivered_before_shipped")
        if _maybe_anomaly(anomaly_rate):
            weight = 0
            injected.append("weight_zero")
        if _maybe_anomaly(anomaly_rate):
            warehouse = ""
            injected.append("warehouse_missing")
        if _maybe_anomaly(anomaly_rate):
            service_level = ""
            injected.append("service_level_missing")
        if _maybe_anomaly(anomaly_rate):
            lead_time = random.choice([-3, 30])
            injected.append("lead_time_out_of_range")
        if _maybe_anomaly(anomaly_rate):
            discount = random.choice([-10, 85])
            injected.append("discount_out_of_range")
        if _maybe_anomaly(anomaly_rate):
            delivery_window = "25-30"
            injected.append("delivery_window_invalid")
        if _maybe_anomaly(anomaly_rate):
            channel = "unknown"
            injected.append("channel_unknown")
        if _maybe_anomaly(anomaly_rate):
            payment = "other"
            injected.append("payment_unknown")

        # Statistical outliers, applied last and only to fields no rule fault
        # already touched, so the two classes never overlap on one value.
        # Deliberately rarer than rule faults: real outliers are rare, and a
        # column where 12% of values are extreme has no "normal" left to
        # measure against.
        if "price_negative" not in injected and _maybe_anomaly(outlier_rate):
            price = round(random.uniform(3000, 9000), 2)
            injected.append("price_extreme")
        if _maybe_anomaly(outlier_rate):
            quantity = random.randint(80, 400)
            injected.append("quantity_extreme")
        if "weight_zero" not in injected and _maybe_anomaly(outlier_rate):
            weight = round(random.uniform(120, 400), 2)
            injected.append("weight_extreme")
        if "stock_negative" not in injected and _maybe_anomaly(outlier_rate):
            stock = random.randint(5000, 20000)
            injected.append("stock_extreme")
        if "discount_out_of_range" not in injected and _maybe_anomaly(outlier_rate):
            # Legal (the rule allows up to 60) but far above the usual 0-30.
            discount = round(random.uniform(48, 59), 2)
            injected.append("discount_high")

        if labels is not None:
            labels.append({"order_id": order_id, "injected": injected})

        writer.writerow(
            [
                order_id,
                customer_id,
                sku,
                price,
                quantity,
                stock,
                warehouse,
                address,
                city,
                postal_code,
                address_valid,
                shipped_at.isoformat(),
                delivered_at.isoformat() if status != "canceled" else "",
                delivery_window,
                lead_time,
                status,
                provider,
                service_level,
                channel,
                payment,
                discount,
                weight,
            ]
        )
