#!/usr/bin/env python3
# personal_accounting.py
# Minimal personal accounting tool with CSV storage + ECB FX (no API keys).

import argparse
import csv
import json
import datetime as dt
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

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
        for r in reader:
            try:
                rows.append(Account(
                    id=r["id"],
                    name=r["name"],
                    category=r["category"],
                    subtype=r["subtype"],
                    location=r["location"],
                    quantity=float(r["quantity"] or 0.0),
                    unit=r["unit"],
                    unit_price_eur=float(r["unit_price_eur"] or 0.0),
                    valuation_date=r["valuation_date"],
                    value_eur=float(r["value_eur"] or 0.0),
                    notes=r.get("notes", ""),
                ))
            except Exception:
                # Skip corrupted rows
                continue
    return rows

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
    notes: str = ""

    @staticmethod
    def real_estate(name: str, location: str, sqm: float, price_per_sqm: float, date: str,
                    subtype: str = "Primary Residence") -> "Account":
        total = round(sqm * price_per_sqm, 2)
        unit_price_eur = float(price_per_sqm)
        return Account(
            id=str(uuid4()),
            name=name,
            category="Real Estate",
            subtype=subtype,
            location=location,
            quantity=float(sqm),
            unit="square_meter",
            unit_price_eur=unit_price_eur,
            valuation_date=date,
            value_eur=total,
            notes=""
        )

    @staticmethod
    def cash(name: str, currency: str, amount: float, date: str) -> "Account":
        rates = fetch_eur_fx_rates()
        value_eur = convert(amount, currency, "EUR", rates)
        unit_price_eur = (value_eur / amount) if amount else 0.0
        return Account(
            id=str(uuid4()),
            name=name,
            category="Cash",
            subtype=currency.upper(),
            location="",
            quantity=float(amount),
            unit=currency.upper(),
            unit_price_eur=unit_price_eur,
            valuation_date=date,
            value_eur=round(value_eur, 2),
            notes=f"FX source=ECB; cache={FX_CACHE}"
        )

# ---------- FX (ECB, no keys) ----------
ECB_DAILY_XML = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FX_CACHE = Path(".fx_cache.json")

def _load_cached_fx() -> Optional[dict]:
    if FX_CACHE.exists():
        try:
            data = json.loads(FX_CACHE.read_text(encoding="utf-8"))
            # Return both date and rates so caller can decide. We reuse as-is.
            if isinstance(data, dict) and "rates" in data:
                return data
        except Exception:
            return None
    return None

def _save_cached_fx(asof: str, rates: dict) -> None:
    FX_CACHE.write_text(json.dumps({"asof": asof, "rates": rates}, indent=2), encoding="utf-8")

def fetch_eur_fx_rates() -> dict:
    """
    Returns dict like {"EUR": 1.0, "USD": 1.0853, "GBP": 0.8431, ...}
    Values are units of foreign currency per 1 EUR.
    """
    # Try online first
    try:
        with urllib.request.urlopen(ECB_DAILY_XML, timeout=10) as resp:
            xml = resp.read()
        root = ET.fromstring(xml)
        # ECB sometimes uses namespaces; tolerate both
        time_nodes = root.findall(".//Cube[@time]") or root.findall(".//{*}Cube[@time]")
        if not time_nodes:
            raise RuntimeError("ECB format not recognized")
        time_cube = time_nodes[0]
        asof = time_cube.attrib["time"]
        rates = {"EUR": 1.0}
        for c in time_cube:
            cur = c.attrib.get("currency")
            rate = c.attrib.get("rate")
            if cur and rate:
                rates[cur.upper()] = float(rate)
        _save_cached_fx(asof, rates)
        return rates
    except Exception:
        # Fallback to cache
        cached = _load_cached_fx()
        if cached and "rates" in cached:
            return cached["rates"]
        raise RuntimeError("Unable to fetch ECB FX and no cache available")

def convert(amount: float, from_ccy: str, to_ccy: str, rates: dict) -> float:
    """
    Convert using EUR as base. 'rates' are foreign units per 1 EUR.
    """
    f = from_ccy.upper()
    t = to_ccy.upper()
    if f == t:
        return float(amount)
    if f != "EUR" and f not in rates:
        raise ValueError(f"FX rate not available for {f}")
    if t != "EUR" and t not in rates:
        raise ValueError(f"FX rate not available for {t}")
    # to EUR
    eur = float(amount) if f == "EUR" else float(amount) / rates[f]
    # from EUR
    return eur if t == "EUR" else eur * rates[t]

# ---------- CLI ----------
def cmd_add_real_estate(args: argparse.Namespace) -> None:
    acct = Account.real_estate(
        name=args.name,
        location=args.location,
        sqm=args.square_meters,
        price_per_sqm=args.price_per_sqm,
        date=args.date,
        subtype=args.subtype,
    )
    write_row(acct)
    print(f"Added account:\n  id={acct.id}\n  name={acct.name}\n  value_eur={acct.value_eur:.2f}")

def cmd_add_cash(args: argparse.Namespace) -> None:
    acct = Account.cash(
        name=args.name,
        currency=args.currency,
        amount=args.amount,
        date=args.date,
    )
    write_row(acct)
    print(f"Added account:\n  id={acct.id}\n  name={acct.name}\n  value_eur={acct.value_eur:.2f}")

def cmd_list(_args: argparse.Namespace) -> None:
    rows = read_all()
    for a in rows:
        unit_part = f"{a.quantity:.2f} {a.unit}"
        if a.category == "Real Estate":
            unit_part = f"{a.quantity:.2f} {a.unit}"
            price_part = f"{a.unit_price_eur:.2f} EUR"
        else:
            price_part = f"{a.unit_price_eur:.6f} EUR"
        loc = f" | {a.location}" if a.location else ""
        print(f"[{a.id}] {a.name} | {a.category}{loc} | {unit_part} @ {price_part} => {a.value_eur:.2f} EUR | date={a.valuation_date}")

def cmd_total(_args: argparse.Namespace) -> None:
    total = sum(a.value_eur for a in read_all())
    print(f"{total:.2f} EUR")

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Personal accounting tool with CSV and ECB FX.")
    sub = p.add_subparsers(dest="command", required=True)

    # add-real-estate
    pre = sub.add_parser("add-real-estate", help="Add a real estate asset")
    pre.add_argument("--name", required=True)
    pre.add_argument("--location", required=True)
    pre.add_argument("--square-meters", type=float, required=True)
    pre.add_argument("--price-per-sqm", type=float, required=True)
    pre.add_argument("--date", required=True, help="Valuation date YYYY-MM-DD")
    pre.add_argument("--subtype", default="Primary Residence")
    pre.set_defaults(func=cmd_add_real_estate)

    # add-cash
    pc = sub.add_parser("add-cash", help="Add a cash or account balance in any currency")
    pc.add_argument("--name", required=True)
    pc.add_argument("--currency", required=True, help="e.g., EUR, USD, GBP")
    pc.add_argument("--amount", type=float, required=True)
    pc.add_argument("--date", required=True, help="Valuation date YYYY-MM-DD")
    pc.set_defaults(func=cmd_add_cash)

    # list
    pl = sub.add_parser("list", help="List all accounts")
    pl.set_defaults(func=cmd_list)

    # total
    pt = sub.add_parser("total", help="Sum total value in EUR")
    pt.set_defaults(func=cmd_total)

    return p

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
