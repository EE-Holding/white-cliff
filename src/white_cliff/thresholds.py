"""Screening thresholds and period windows.

The numbers are the CTO's constants. A change to one is a CTO decision.
"""

from __future__ import annotations

from decimal import Decimal

# Quality checks. Comparisons are >= except cash conversion, which is below.
CASH_CONVERSION = Decimal("0.80")
RECEIVABLES_GAP = Decimal("0.10")
INVENTORY_GAP = Decimal("0.10")
ONE_OFF_SHARE = Decimal("0.10")
DILUTION = Decimal("0.03")
MARGIN_POINTS = Decimal("3.0")
TAX_POINTS = Decimal("5.0")

# Period matching.
DURATION_DAYS = 7
YOY_GAP_MIN = 350
YOY_GAP_MAX = 380
QUARTER_MIN = 80
QUARTER_MAX = 100
PRIOR_FILING_MIN = 80
PRIOR_FILING_MAX = 100
YEAR_MIN = 330
YEAR_MAX = 380
