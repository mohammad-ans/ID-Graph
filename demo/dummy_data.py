from __future__ import annotations
import hashlib

def sha256_text(value: str):
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()

def row(record_id, source_table, transaction_date, merchant_name, email=None, phone=None, maid=None, screen_width=None, screen_length=None, ip_country=None, city=None, language=None):
    return {
        "record_id": record_id, "source_table": source_table, "transaction_date": transaction_date, "merchant_name": merchant_name, "merchant_url": f"https://{merchant_name.lower().replace(' ', '')}.com",
        "hashed_email": sha256_text(email) if email else None, "hashed_phone": sha256_text(phone) if phone else None, "maid": maid,
        "screen_width": screen_width, "screen_length": screen_length, "ip_country": ip_country, "city": city, "language": language,
    }


def build_batches() -> list[list[dict]]:
    batch1 = [
        row("r-alice-1", "orders", "2023-01-05T10:00:00", "Northwind Foods",
             email="alice@example.com",
             screen_width="1440", screen_length="900", ip_country="us", city="Austin", language="en-US"),
        row("r-alice-2", "orders", "2023-03-10T14:30:00", "Bluebird Books",
             email="alice@example.com",
             screen_width="390", screen_length="844", ip_country="us", city="Austin", language="en-US"),

        row("r-bob-1", "orders", "2023-01-01T09:00:00", "Northwind Foods",
             phone="555-010-0001",
             screen_width="1920", screen_length="1080", ip_country="us", city="Denver", language="en-US"),

        row("r-dave-1", "orders", "2025-06-01T11:00:00", "Northwind Foods",
             phone="555-010-0002",
             screen_width="1280", screen_length="800", ip_country="us", city="Reno", language="en-US"),

        row("r-promo-1", "orders", "2025-01-01T08:00:00", "BulkBuy Outlet",
             email="promo@bulkbuy.example", phone="555-020-0001",
             screen_width="1366", screen_length="768", ip_country="us", city="Miami", language="en-US"),
        row("r-promo-2", "orders", "2025-01-01T08:05:00", "BulkBuy Outlet",
             email="promo@bulkbuy.example", phone="555-020-0002",
             screen_width="360", screen_length="800", ip_country="us", city="Chicago", language="en-US"),
        row("r-promo-3", "orders", "2025-01-01T08:10:00", "BulkBuy Outlet",
             email="promo@bulkbuy.example", phone="555-020-0003",
             screen_width="1536", screen_length="864", ip_country="ca", city="Toronto", language="en-CA"),
        row("r-promo-4", "orders", "2025-01-01T08:15:00", "BulkBuy Outlet",
             email="promo@bulkbuy.example", phone="555-020-0004",
             screen_width="414", screen_length="896", ip_country="us", city="Seattle", language="en-US"),
    ]

    batch2 = [
        row("r-carol-1", "orders", "2026-06-01T09:00:00", "Northwind Foods",
             phone="555-010-0001",
             screen_width="1600", screen_length="900", ip_country="us", city="Tampa", language="en-US"),

        row("r-dave-2", "orders", "2025-07-01T11:00:00", "Bluebird Books",
             phone="555-010-0002",
             screen_width="1280", screen_length="800", ip_country="us", city="Reno", language="en-US"),


        row("r-promo-5", "orders", "2025-01-02T08:20:00", "BulkBuy Outlet",
             email="promo@bulkbuy.example", phone="555-020-0005",
             screen_width="1920", screen_length="1200", ip_country="us", city="Boston", language="en-US"),
        row("r-promo-6", "orders", "2025-01-02T08:25:00", "BulkBuy Outlet",
             email="promo@bulkbuy.example", phone="555-020-0006",
             screen_width="393", screen_length="852", ip_country="mx", city="Monterrey", language="es-MX"),
        row("r-promo-7", "orders", "2025-01-02T08:30:00", "BulkBuy Outlet",
             email="promo@bulkbuy.example", phone="555-020-0007",
             screen_width="1440", screen_length="900", ip_country="us", city="Phoenix", language="en-US"),
    ]
    batch3 = [
        row("r-erin-1", "orders", "2025-06-10T09:00:00", "Cedar Grocers",
             screen_width="1600", screen_length="900", ip_country="us", city="Seattle", language="en-US"),
        row("r-erin-2", "orders", "2025-06-10T15:00:00", "Pinehill Cafe",
             screen_width="1600", screen_length="900", ip_country="us", city="Seattle", language="en-US"),


        row("r-travel-1", "orders", "2025-07-14T10:00:00", "Cedar Grocers",
             screen_width="1200", screen_length="800", ip_country="us", city="Denver", language="en-US"),
        row("r-travel-2", "orders", "2025-07-17T10:00:00", "Cedar Grocers",
             screen_width="1200", screen_length="800", ip_country="us", city="Phoenix", language="es-US"),


        row("r-lonewolf-1", "orders", "2025-09-01T08:00:00", "Acme Kiosk",
             screen_width="390", screen_length="844", ip_country="mx", city="Monterrey", language="es-MX"),
    ]

    return [batch1, batch2, batch3]
