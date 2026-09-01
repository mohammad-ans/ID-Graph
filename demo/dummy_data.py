from __future__ import annotations
import hashlib
from identityresolver.graph_model import GraphRow
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

def build_showcase_rows():
    rows = []
    rows.append(row("r-nadia-1", "orders", "2024-03-01T09:00:00", "Northwind Foods",
                      email="nadia@example.com", phone="555-030-0001",
                      screen_width="1440", screen_length="900", ip_country="us", city="Seattle", language="en-US"))

    rows.append(row("r-omar-1", "orders", "2024-01-10T10:00:00", "Bluebird Books",
                      email="omar@example.com",
                      screen_width="1920", screen_length="1080", ip_country="us", city="Portland", language="en-US"))
    rows.append(row("r-omar-2", "orders", "2024-03-10T15:00:00", "BulkBuy Outlet",
                      email="omar@example.com",
                      screen_width="390", screen_length="844", ip_country="us", city="Portland", language="en-US"))

    rows.append(row("r-priya-1", "orders", "2024-05-15T11:30:00", "Northwind Foods",
                      phone="555-030-0002",
                      screen_width="1280", screen_length="800", ip_country="us", city="Boston", language="en-US"))

    
    rows.append(row("r-quinn-1", "orders", "2024-02-01T13:00:00", "Bluebird Books",
                      email="quinn@example.com", phone="555-030-0003",
                      screen_width="1536", screen_length="864", ip_country="us", city="Chicago", language="en-US"))
    rows.append(row("r-quinn-2", "orders", "2024-02-01T13:40:00", "BulkBuy Outlet",
                      email="quinn@example.com", phone="555-030-0003",
                      screen_width="1536", screen_length="864", ip_country="us", city="Chicago", language="en-US"))

    rows.append(row("r-rosa-1", "orders", "2024-07-20T08:15:00", "Northwind Foods",
                      email="rosa@example.com",
                      screen_width="414", screen_length="896", ip_country="us", city="Denver", language="en-US"))

    rows.append(row("r-sam-1", "orders", "2024-01-01T09:00:00", "Northwind Foods",
                      email="sam@example.com", phone="555-030-0004",
                      screen_width="1600", screen_length="900", ip_country="us", city="Austin", language="en-US"))
    rows.append(row("r-sam-2", "orders", "2024-04-01T09:00:00", "Bluebird Books",
                      email="sam@example.com", phone="555-030-0004",
                      screen_width="1600", screen_length="900", ip_country="us", city="Austin", language="en-US"))
    rows.append(row("r-sam-3", "orders", "2024-08-01T09:00:00", "BulkBuy Outlet",
                      email="sam@example.com", phone="555-030-0004",
                      screen_width="360", screen_length="780", ip_country="us", city="Austin", language="en-US"))
    supernode_people = [
        ("555-040-0001", "1366", "768", "us", "Miami", "en-US"),
        ("555-040-0002", "360", "800", "us", "Chicago", "en-US"),
        ("555-040-0003", "1536", "864", "ca", "Toronto", "en-CA"),
        ("555-040-0004", "414", "896", "us", "Seattle", "en-US"),
        ("555-040-0005", "1920", "1200", "us", "Boston", "en-US"),
        ("555-040-0006", "393", "852", "mx", "Monterrey", "es-MX"),
    ]
    for i, (phone, sw, sl, country, city, lang) in enumerate(supernode_people, start=1):
        rows.append(row(f"r-showcase-promo-{i}", "orders", f"2025-06-01T08:{i*3:02d}:00", "BulkBuy Outlet",
                          email="megasale@bulkbuy.example", phone=phone,
                          screen_width=sw, screen_length=sl, ip_country=country, city=city, language=lang))


    return rows


SCHEMA_COLS = {
    "identifiers": [
        {"name": "email", "column": "hashed_email", "pre_hashed": True, "include_in_belongs_to": True},
        {"name": "phone", "column": "hashed_phone", "pre_hashed": True, "include_in_belongs_to": True},
        {"name": "maid", "column": "maid", "pre_hashed": False, "include_in_belongs_to": False}
     ],
     "signal_groups": [
         {"name": "device_props", "columns": ["screen_width", "screen_length"]},
         {"name": "ip_loc", "columns": ["ip_country", "city", "language"]}
     ],
     "passthrough": ["transaction_date", "merchant_name", "merchant_url", "source_table"],
    "record_id": ["record_id"],
    "probabilistic": [{"active_learning_min_labels": 5}]}

def make_rows():
    raw = {
        "match-1a": row("match-1a", "orders", "2025-01-01T09:00:00", "Northwind", screen_width="1440", screen_length="900", ip_country="us", city="Austin", language="en-US"),
        "match-1b": row("match-1b", "orders", "2025-01-02T09:00:00", "Northwind", screen_width="1440", screen_length="900", ip_country="us", city="Austin", language="en-US"),
        "match-2a": row("match-2a", "orders", "2025-02-01T09:00:00", "Bluebird", screen_width="1920", screen_length="1080", ip_country="us", city="Denver", language="en-US"),
        "match-2b": row("match-2b", "orders", "2025-02-03T09:00:00", "Bluebird", screen_width="1920", screen_length="1080", ip_country="us", city="Denver", language="en-US"),
        "match-3a": row("match-3a", "orders", "2025-03-01T09:00:00", "Cedar", screen_width="360", screen_length="780", ip_country="ca", city="Toronto", language="en-CA"),
        "match-3b": row("match-3b", "orders", "2025-03-01T09:00:00", "Cedar", screen_width="360", screen_length="780", ip_country="ca", city="Toronto", language="en-CA"),
        "match-4a": row("match-4a", "orders", "2025-07-01T09:00:00", "NorthWind", screen_width="1336", screen_length="768", ip_country="us", city="Miami", language="en-US"),
        "match-4b": row("match-4b", "orders", "2025-07-02T09:00:00", "NorthWind", screen_width="1336", screen_length="768", ip_country="us", city="Miami", language="en-US"),
        "match-5a": row("match-5a", "orders", "2025-08-01T09:00:00", "Bluebird", screen_width="414", screen_length="896", ip_country="gb", city="London", language="en-GB"),
        "match-5b": row("match-5b", "orders", "2025-080-04T09:00:00", "Bluebird", screen_width="414", screen_length="896", ip_country="gb", city="London", language="en-GB"),
        "nonmatch-1a": row("nonmatch-1a", "orders", "2025-04-01T09:00:00", "Northwind", screen_width="1440", screen_length="900", ip_country="us", city="Austin", language="en-US"),
        "nonmatch-1b": row("nonmatch-1b", "orders", "2025-09-01T09:00:00", "BulkBuy", screen_width="393", screen_length="852", ip_country="mx", city="Monterrey", language="es-MX"),
        "nonmatch-2a": row("nonmatch-2a", "orders", "2025-05-01T09:00:00", "Bluebird", screen_width="1920", screen_length=1080, ip_country="us", city="Denver", language="en-US"),
        "nonmatch-2b": row("nonmatch-2b", "orders", "2025-10-01T09:00:00", "Cedar", screen_width="1280", screen_length="800", ip_country="gb", city="London", language="en-GB"),
        "nonmatch-3a": row("nonmatch-3a", "orders", "2025-01-15T09:00:00", "Cedar", screen_width="1600", screen_length="900", ip_country="us", city="Seatle", language="en-US"),
        "nonmatch-3b": row("nonmatch-3b", "orders", "2025-11-01T09:00:00", "Northwind", screen_width="1024", screen_length="768", ip_country="ca", city="Vancouver", language="en-CA"),
        "nonmatch-4a": row("nonmatch-4a", "orders", "2025-02-15T09:00:00", "Bluebird", screen_width="1536", screen_length="864", ip_country="us", city="Chicago", language="en-US"),
        "nonmatch-4b": row("nonmatch-4b", "orders", "2025-12-01T09:00:00", "Bulkbuy", screen_width="390", screen_length="844", ip_country="mx", city="Monterrey", language="es-MX"),
        "nonmatch-5a": row("nonmatch-5a", "orders", "2025-03-15T09:00:00", "Northwind", screen_width="1920", screen_length="1200", ip_country="us", city="Boston", language="en-US"),
        "nonmatch-5b": row("nonmatch-5b", "orders", "2025-12-15T09:00:00", "Cedar", screen_width="360", screen_length="800", ip_country="ca", city="Toronto", language="en-CA"),
        "borderline-a": row("borderline-a", "orders", "2025-06-01T09:00:00", "Cedar", screen_width="1440", screen_length="900", ip_country="us", city="Austin", language="en-US"),
        "borderline-b": row("borderline-b", "orders", "2025-06-15T09:00:00", "Cedar", screen_width="1920", screen_length="1080", ip_country="us", city="Austin", language="en-US")
    }
    return {rid: GraphRow.from_db_row(r, SCHEMA_COLS) for rid, r in raw.items()}