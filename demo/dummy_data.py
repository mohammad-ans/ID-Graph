from __future__ import annotations
import hashlib

def sha256_text(value: str):
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()

def row(record_id, source_table, transaction_date, merchant_name, email=None, phone=None, maid=None, screen_width=None, screen_length=None, ip_country=None, city=None, language=None):
    return {
        "record_id": record_id, "source_table": source_table, "transaction_date": transaction_date, "merchant_name": merchant_name, "merchant_url": f"https://{merchant_name.lower().replace(' ', '')}.com",
        "hashed_email": sha256_text(email) if email else None, "hashed_phone": sha256_text(phone) if phone else None, "maid": maid,
        "screen_width": screen_width, "screen_length": screen_length, "ip_country": ip_country, "city": city, "langauge": language
    }

def build_batches():
    pass