import csv
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

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


def generate_dataset(file_path: str, rows: int, anomaly_rate: float) -> None:
    random.seed(42)
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

    base_date = datetime.utcnow() - timedelta(days=30)
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for _ in range(rows):
            order_id = str(uuid.uuid4())[:8]
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

            if _maybe_anomaly(anomaly_rate):
                price = -abs(price)
            if _maybe_anomaly(anomaly_rate):
                stock = -random.randint(1, 10)
            if _maybe_anomaly(anomaly_rate):
                address = ""
                address_valid = "false"
            if _maybe_anomaly(anomaly_rate):
                delivered_at = shipped_at - timedelta(days=2)
            if _maybe_anomaly(anomaly_rate):
                weight = 0
            if _maybe_anomaly(anomaly_rate):
                warehouse = ""
            if _maybe_anomaly(anomaly_rate):
                service_level = ""
            if _maybe_anomaly(anomaly_rate):
                lead_time = random.choice([-3, 30])
            if _maybe_anomaly(anomaly_rate):
                discount = random.choice([-10, 85])
            if _maybe_anomaly(anomaly_rate):
                delivery_window = "25-30"
            if _maybe_anomaly(anomaly_rate):
                channel = "unknown"
            if _maybe_anomaly(anomaly_rate):
                payment = "other"

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
