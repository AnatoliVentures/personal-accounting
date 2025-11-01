#!/usr/bin/env python3
"""Personal accounting tool.

Features
- CSV storage.
- Add real estate.
- Add cash with live ECB FX (no API keys).
- List accounts.
- Total in EUR.
- Dedupe rows and rewrite CSV.

Usage
  python3 personal_accounting.py add-real-estate \
    --name "House in Athens" --location "Athens, Greece" \
    --square-meters 105 --price-per-sqm 3000 --date 2025-11-01

  python3 personal_accounting.py add-cash \
    --name "401k" --currency USD --amount 119231.14 --date 2025-11-01

  python3 personal_accounting.py list
  python3 personal_accounting.py total
  python3 personal_accounting.py dedupe
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List
from urllib.request import urlopen
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STORAGE = Path("accounts.csv")

CSV_COLUMNS = [
    "id",
    "name",
    "category",
    "subtype",
    "location",
    "quantity",
    "unit",
    "unit_price_eur",
    "valuation_date",
    "value_eur",
    "notes",
]

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Account:
    """A single asset entry normalized to EUR."""

    id: str
    name: str
    category: str              # e.g., "Real Estate", "Cash"
    subtype: str               # e.g., "Property", "USD"
    location: str              # empty for non-location assets
    quantity: float            # amount or size (sqm, currency amount, etc.)
    unit: str                  # "square_meter", "USD", etc.
    unit_price_eur: float      # EUR per unit at valuation time
    valuation_date: str        # ISO "YYYY-MM-DD"
    value_eur: float           # total value in EUR
    notes: str                 # optional notes

    @staticmethod
    def from_csv_row(row: Dict[str, str]) -> "Account":
        return Account(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            subtype=row["subtype"],
            location=row["location"],
            quantity=float(row["quantity"]) if row["quantity"] else 0.0,
            unit=row["unit"],
            unit_price_eur=float(row["unit_price_eur"]) if row["unit_price_eur"] else 0.0,
            valuation_date=row["valuation_date"],
            value_eur=float(row["value_eur"]) if row["value_eur"] else 0.0,
            notes=row["notes"],
        )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def ensure_storage() -> None:
    if not STORAGE.exists():
        with STORAGE.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()


def write_row(acct: Account) -> None:
    ensure_storage()
    with STORAGE.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerow(asdict(acct))


def write_all(rows: List[Account]) -> None:
    ensure_storage()
    with STORAGE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for a in rows:
            w.writerow(asdict(a))


def read_all() -> List[Account]:
    ensure_storage()
    out: List[Account] = []
    with STORAGE.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(Account.from_csv_row(row))
    return out


# ---------------------------------------------------------------------------
# FX utilities
# ---------------------------------------------------------------------------


def get_ecb_rates() -> Dict[str, float]:
    """Fetch latest ECB EUR-base FX rates.

    Returns: currency -> rate such that 1 EUR = rate * CURRENCY.
    EUR value = amount / rate[currency]
    """
    with urlopen(ECB_DAILY_URL, timeout=10) as resp:
        data = resp.read()

    root = ET.fromstring(data)
    rates: Dict[str, float] = {"EUR": 1.0}

    for cube_time in root.findall(".//Cube[@time]"):
        for cube in cube_time.findall("./Cube"):
            cur = cube.attrib.get("currency")
            rate = cube.attrib.get("rate")
            if cur and rate:
                rates[cur.upper()] = float(rate)
        break  # only latest day
    return rates


def eur_from(amount: float, currency: str, rates: Dict[str, float]) -> float:
    cur = currency.upper()
    if cur == "EUR":
        return amount
    if cur not in rates:
        raise ValueError(f"Currency {cur} not in ECB daily rates")
    return amount / rates[cur]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_add_cash(args: argparse.Namespace) -> None:
    amount = float(args.amount)
    currency = args.currency.upper()

    if currency == "EUR":
        value_eur = amount
        unit_price_eur = 1.0
    else:
        try:
            rates = get_ecb_rates()
            value_eur = eur_from(amount, currency, rates)
            unit_price_eur = value_eur / amount if amount else 0.0
        except Exception as e:
            if args.offline_rate:
                value_eur = amount / float(args.offline_rate)
                unit_price_eur = value_eur / amount if amount else 0.0
            else:
                print(f"FX lookup failed: {e}", file=sys.stderr)
                raise

    acct = Account(
        id=args.id,
        name=args.name,
        category="Cash" if args.category is None else args.category,
        subtype=currency,
        location="",
        quantity=amount,
        unit=currency,
        unit_price_eur=unit_price_eur,
        valuation_date=args.date,
        value_eur=value_eur,
        notes=args.notes or "",
    )
    write_row(acct)
    print(f"Added:\n  id={acct.id}\n  name={acct.name}\n  value_eur={acct.value_eur:.2f}")


def cmd_add_real_estate(args: argparse.Namespace) -> None:
    sqm = float(args.square_meters)
    price_per_sqm = float(args.price_per_sqm)
    value_eur = sqm * price_per_sqm

    acct = Account(
        id=args.id,
        name=args.name,
        category="Real Estate",
        subtype="Property",
        location=args.location,
        quantity=sqm,
        unit="square_meter",
        unit_price_eur=price_per_sqm,
        valuation_date=args.date,
        value_eur=value_eur,
        notes=args.notes or "",
    )
    write_row(acct)
    print(f"Added:\n  id={acct.id}\n  name={acct.name}\n  value_eur={acct.value_eur:.2f}")


def cmd_list(_: argparse.Namespace) -> None:
    rows = read_all()
    for a in rows:
        print(
            f"[{a.id}] {a.name} | {a.category} | {a.location or a.subtype} | "
            f"{a.quantity:.2f} {a.unit} @ {a.unit_price_eur:.2f} EUR => {a.value_eur:.2f} EUR | date={a.valuation_date}"
        )


def cmd_total(_: argparse.Namespace) -> None:
    rows = read_all()
    total = sum(a.value_eur for a in rows)
    print(f"Total value: {total:.2f} EUR")


def cmd_dedupe(_: argparse.Namespace) -> None:
    """Remove duplicate rows by (name, date)."""
    rows = read_all()

    # Keep last entry per (name, valuation_date)
    deduped: dict[tuple, Account] = {}
    for a in rows:
        key = (a.name.strip(), a.valuation_date.strip())
        deduped[key] = a  # last occurrence wins

    out = list(deduped.values())
    out.sort(key=lambda x: (x.valuation_date, x.name))
    write_all(out)
    print(f"Deduped from {len(rows)} to {len(out)} rows.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Personal accounting tool")
    sub = p.add_subparsers(dest="command")

    # add-cash
    p_cash = sub.add_parser("add-cash", help="Add a cash/investment position")
    p_cash.add_argument("--id", default=lambda: __import__("uuid").uuid4().hex, type=str,
                        help="Custom id (defaults to random UUID hex)")
    p_cash.add_argument("--name", required=True)
    p_cash.add_argument("--currency", required=True)
    p_cash.add_argument("--amount", required=True, type=float)
    p_cash.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_cash.add_argument("--offline-rate", type=float,
                        help="Manual FX rate when offline (1 EUR = rate * CURRENCY)")
    p_cash.add_argument("--category", help='Override category (default "Cash")')
    p_cash.add_argument("--notes", help="Optional notes")
    p_cash.set_defaults(func=cmd_add_cash)

    # add-real-estate
    p_re = sub.add_parser("add-real-estate", help="Add a real estate asset")
    p_re.add_argument("--id", default=lambda: __import__("uuid").uuid4().hex, type=str,
                      help="Custom id (defaults to random UUID hex)")
    p_re.add_argument("--name", required=True)
    p_re.add_argument("--location", required=True)
    p_re.add_argument("--square-meters", required=True, type=float)
    p_re.add_argument("--price-per-sqm", required=True, type=float)
    p_re.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_re.add_argument("--notes", help="Optional notes")
    p_re.set_defaults(func=cmd_add_real_estate)

    # list
    p_list = sub.add_parser("list", help="List all accounts")
    p_list.set_defaults(func=cmd_list)

    # total
    p_total = sub.add_parser("total", help="Total value in EUR")
    p_total.set_defaults(func=cmd_total)

    # dedupe
    p_dedupe = sub.add_parser("dedupe", help="Remove duplicate rows by (name, category, date)")
    p_dedupe.set_defaults(func=cmd_dedupe)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve dynamic default for id fields
    if hasattr(args, "id") and callable(args.id):
        args.id = args.id()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
