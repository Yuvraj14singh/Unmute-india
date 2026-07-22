import hashlib
from decimal import Decimal

def compact_count(value):
    value = int(value or 0)
    for size, suffix in ((1_000_000_000, 'B'), (1_000_000, 'M'), (1_000, 'K')):
        if value >= size:
            amount = Decimal(value) / Decimal(size)
            rendered = f'{amount:.1f}'.rstrip('0').rstrip('.')
            return f'{rendered}{suffix}'
    return str(value)

def request_fingerprint(value, secret):
    return hashlib.sha256(f'{secret}:{value}'.encode()).hexdigest() if value else ''
