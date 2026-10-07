"""One way to write numbers and dates everywhere in the UI.

Rules: the sign goes before the currency symbol and uses a real minus sign;
zero (or missing) renders as an em dash; percentages are signed by default.
"""
import math

import pandas as pd

MINUS = "−"
ZERO = "—"
_EPSILON = 0.005


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def money(v, signed: bool = False, cents: bool = False, zero_dash: bool = True) -> str:
    if _missing(v) or (zero_dash and abs(v) < _EPSILON):
        return ZERO
    body = f"${abs(v):,.{2 if cents else 0}f}"
    if v < 0:
        return MINUS + body
    return ("+" + body) if signed else body


def pct(v, signed: bool = True, digits: int = 1) -> str:
    if _missing(v):
        return ZERO
    body = f"{abs(v) * 100:.{digits}f}%"
    if v < 0:
        return MINUS + body
    return ("+" + body) if signed else body


def shares(v) -> str:
    if _missing(v):
        return ZERO
    return "<0.01" if 0 < abs(v) < 0.01 else f"{v:,.2f}"


def date(d) -> str:
    if d is None or pd.isna(d):
        return ZERO
    return pd.Timestamp(d).strftime("%b %d, %Y")


def sign_class(v) -> str:
    """CSS class for P/L-type values: 'pos', 'neg' or 'zero'."""
    if _missing(v) or abs(v) < _EPSILON:
        return "zero"
    return "pos" if v > 0 else "neg"
