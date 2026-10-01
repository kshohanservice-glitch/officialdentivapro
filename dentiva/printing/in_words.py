"""Convert an integer-paisa amount into human-readable English words,
South-Asian style (lakh/crore) suitable for invoices and cheques.

Examples (in BDT):
    0            -> "Taka: zero only"
    950          -> "Taka: nine hundred fifty only"
    950.50       -> "Taka: nine hundred fifty and 50/100 only"
    1,00,000     -> "one lakh"
    1,00,00,000  -> "one crore"
"""
from __future__ import annotations

UNITS = [
    "", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _below_thousand(n: int) -> str:
    if n == 0:
        return ""
    if n < 20:
        return UNITS[n]
    if n < 100:
        t = TENS[n // 10]
        u = UNITS[n % 10]
        return (t + ("-" + u if u else ""))
    # hundreds
    h = n // 100
    rem = n % 100
    head = UNITS[h] + " hundred"
    if rem:
        return head + " " + _below_thousand(rem)
    return head


def _int_to_words(n: int) -> str:
    """Convert a non-negative integer < 10^12 (10,000 crore) to words.
    Uses South-Asian grouping: ... crore lakh thousand ...
    """
    if n == 0:
        return "zero"
    parts: list[str] = []
    crore = n // 10_000_000
    n %= 10_000_000
    lakh = n // 100_000
    n %= 100_000
    thousand = n // 1000
    rest = n % 1000
    if crore:
        parts.append(_below_thousand(crore) + " crore")
    if lakh:
        parts.append(_below_thousand(lakh) + " lakh")
    if thousand:
        parts.append(_below_thousand(thousand) + " thousand")
    if rest:
        parts.append(_below_thousand(rest))
    # Filter empty parts and join
    out = " ".join(p for p in parts if p)
    # Fix double spaces
    return " ".join(out.split())


def amount_in_words_taka(paisa: int) -> str:
    """Format a paisa integer as "Taka: <words in taka> and <paisa>/100 only".

    Fractional paisa is ignored (we always treat the input as integer paisa).
    Negative amounts return "zero" for safety.
    """
    if paisa is None or paisa <= 0:
        return "Taka: zero only"
    if paisa > 9_999_999_999 * 100:  # 9999 crore taka cap — far beyond any clinic use
        return "Taka: (amount too large to convert to words) only"
    taka = paisa // 100
    p = paisa % 100
    taka_words = _int_to_words(taka) if taka else ""
    if p == 0:
        return f"Taka: {taka_words} only"
    # If only paisa (e.g., 50 paisa with taka=0), show as "Taka: 50/100 only"
    frac = f"{p:02d}/100"
    if taka_words:
        return f"Taka: {taka_words} and {frac} only"
    return f"Taka: {frac} only"
