#!/usr/bin/env python3
# personal_accounting.py
# Minimal personal accounting tool with CSV storage + ECB FX (no API keys).

import argparse
import csv
import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List
from uuid import uuid4
from urllib.request import urlopen

# ---------- Storage ----------
STORAGE = Path("accounts.csv")

COLUMNS = [
    "id", "name", "category", "subtype", "location",
    "quantity", "unit", "unit_price_eur", "valuation_date", "value_eur", "notes"
]

def ensure_storage() -> None:
    if not STORAGE.exists():
        with STORAGE.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()

def write_row(acct: "Account") -> None:
    ensure_storage()
    with STORAGE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writerow(asdict(acct))

def read_all() -> List["Account"]:
    ensure_storage()
    rows: List[Account] = []
    with STORAGE.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(Account(**row))
    return rows

# ---------- FX Utilities ----------
ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

def get_ecb_rates() -> dict[str, float]:
    with urlopen(ECB_DAILY_URL, timeout=10) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    rates = {"EUR": 1.0}
    for cube_time in root.findall(".//Cube[@time]"):
        for cube in cube_time.findall("./Cube"):
            cur = cube.attrib.get("currency")
            rate = cube.attrib.get("rate")
            if cur and rate:
                rates[cur] = float(rate)
        break
    return rates

def eur_from(amount: float, currency: str, rates: dict[str, float]) -> float:
    currency = currency.upper()
    if currency == "EUR":
        return amount
    if currency not in rates:
        raise ValueError(f"Currency {currency} not in ECB daily rates")
    return amount / rates[currency]

# ---------- Model ----------
@dataclass
class Account:
    id: str
    name: str
    category: str
    subtype: str
    location: str
    quantity: float
    unit: str
    unit_price_eur: float
    valuation_date: str
    value_eur: float
    notes: str

# ---------- Commands ----------
def add_cash(args):
    if args.currency.upper() != "EUR":
        try:
            rates = get_ecb_rates()
            value_eur = eur_from(args.amount, args.currency, rates)
        except Exception:
            if args.offline_rate:
                value_eur = args.amount / args.offline_rate
            else:
                raise
    else:
        value_eur = args.amount

    acct = Account(
        id=str(uuid4()),
        name=args.name,
        category="Investment",
        subtype=args.currency.upper(),
        location="",
        quantity=args.amount,
        unit=args.currency.upper(),
        unit_price_eur=value_eur / args.amount if args.amount else 0,
        valuation_date=args.date,
        value_eur=value_eur,
        notes="",
    )
    write_row(acct)
    print(f"Added account:\n  id={acct.id}\n  name={acct.name}\n  value_eur={acct.value_eur:.2f}")

def add_real_estate(args):
    value_eur = args.square_meters * args.price_per_sqm
    acct = Account(
        id=str(uuid4()),
        name=args.name,
        category="Real Estate",
        subtype="Property",
        location=args.location,
        quantity=args.square_meters,
        unit="square_meter",
        unit_price_eur=args.price_per_sqm,
        valuation_date=args.date,
        value_eur=value_eur,
        notes="",
    )
    write_row(acct)
    print(f"Added account:\n  id={acct.id}\n  name={acct.name}\n  value_eur={acct.value_eur:.2f}")

def list_accounts(args):
    rows = read_all()
    for a in rows:
        print(
            f"[{a.id}] {a.name} | {a.category} | {a.location or a.subtype} | "
            f"{a.quantity} {a.unit} @ {a.unit_price_eur} EUR => {float(a.value_eur):.2f} EUR | date={a.valuation_date}"
        )

def total_accounts(args):
    rows = read_all()
    total = sum(float(a.value_eur) for a in rows)
    print(f"Total value: {total:.2f} EUR")

# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser(description="Personal accounting tool")
    sub = parser.add_subparsers(dest="command")

    # add-cash
    p_cash = sub.add_parser("add-cash")
    p_cash.add_argument("--name", required=True)
    p_cash.add_argument("--currency", required=True)
    p_cash.add_argument("--amount", type=float, required=True)
    p_cash.add_argument("--date", required=True)
    p_cash.add_argument("--offline-rate", type=float, help="Use manual FX rate if offline")
    p_cash.set_defaults(func=add_cash)

    # add-real-estate
    p_re = sub.add_parser("add-real-estate")
    p_re.add_argument("--name", required=True)
    p_re.add_argument("--location", required=True)
    p_re.add_argument("--square-meters", type=float, required=True)
    p_re.add_argument("--price-per-sqm", type=float, required=True)
    p_re.add_argument("--date", required=True)
    p_re.set_defaults(func=add_real_estate)

    # list
    p_list = sub.add_parser("list")
    p_list.set_defaults(func=list_accounts)

    # total
    p_total = sub.add_parser("total")
    p_total.set_defaults(func=total_accounts)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
