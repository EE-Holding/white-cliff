"""Quality-check arithmetic. Words are applied later from the cleared templates.

Each check uses only the current filing. A missing input is never treated as zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from white_cliff.compare import (
    _band,
    _base,
    _usd,
    day_gap,
    percent_change,
    quarter_band,
    year_band,
)
from white_cliff.explain import _from_filing, _length, _prefer
from white_cliff.facts import Fact
from white_cliff.thresholds import (
    CASH_CONVERSION,
    DILUTION,
    DURATION_DAYS,
    INVENTORY_GAP,
    MARGIN_POINTS,
    ONE_OFF_SHARE,
    QUARTER_MAX,
    RECEIVABLES_GAP,
    TAX_POINTS,
    YOY_GAP_MAX,
    YOY_GAP_MIN,
)

REVENUE = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
)
COST = ("CostOfGoodsAndServicesSold", "CostOfRevenue")
PRETAX = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
)
ONE_OFF = (
    "RestructuringCharges",
    "GoodwillImpairmentLoss",
    "ImpairmentOfIntangibleAssetsExcludingGoodwill",
    "AssetImpairmentCharges",
    "GainLossOnDispositionOfAssets",
    "GainLossOnSaleOfPropertyPlantEquipment",
    "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal",
    "GainsLossesOnExtinguishmentOfDebt",
    "BusinessCombinationAcquisitionRelatedCosts",
)
_GAINS = frozenset(
    {
        "GainLossOnDispositionOfAssets",
        "GainLossOnSaleOfPropertyPlantEquipment",
        "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal",
        "GainsLossesOnExtinguishmentOfDebt",
    }
)

DIFFERENT = "The figures use different definitions in the two periods."
LENGTHS = "The periods are different lengths."
DOLLARS = "The figures are not in US dollars."
MISSING = "{figure} is not in the filing."


@dataclass
class ItemShare:
    fact: Fact
    share: Decimal
    charge: bool


@dataclass
class CheckResult:
    check_id: str
    outcome: str
    reason: str = ""
    facts: tuple[Fact, ...] = ()
    numbers: dict[str, Decimal] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    items: tuple[ItemShare, ...] = ()
    formula: str = ""


def _pct(value: Decimal) -> Decimal:
    return (value * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _one(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _money(fact: Fact) -> str | None:
    if not _from_filing(fact) or fact.concealed:
        return DOLLARS
    if not _usd(fact) or _base(fact.unit) != "USD":
        return DOLLARS
    return None


def _shares(fact: Fact) -> str | None:
    if not _from_filing(fact) or fact.concealed:
        return "The earlier diluted share count is not available."
    if _base(fact.unit) != "shares":
        return DOLLARS
    return None


def _band_for(form: str) -> tuple[int, int]:
    if form == "10-K":
        return year_band()
    return quarter_band()


def _candidates(facts: list[Fact], concept: str, end: str, low: int, high: int) -> list[Fact]:
    pool = []
    for fact in facts:
        if fact.concept != concept or fact.period.kind != "duration" or fact.period.end != end:
            continue
        if not _from_filing(fact) or fact.concealed:
            continue
        days = _length(fact)
        if days is None or days < low or days > high:
            continue
        pool.append(fact)
    return pool


def _near(facts: list[Fact], concept: str, end: str, low: int, high: int) -> Fact | None:
    """One fact for the period. Scale words of the same unit are one group, so the finer figure wins."""
    grouped: dict[str, list[Fact]] = {}
    for fact in _candidates(facts, concept, end, low, high):
        grouped.setdefault(_base(fact.unit), []).append(fact)
    if not grouped:
        return None
    unit = sorted(grouped, key=lambda item: (-len(grouped[item]), item))[0]
    return _prefer(grouped[unit])


def _yoy(facts: list[Fact], current: Fact, low: int, high: int) -> Fact | str:
    """The comparative in this filing, or a not-run reason."""
    chosen: list[Fact] = []
    saw_length = False
    saw_currency = False
    saw_other = False
    for fact in facts:
        if not _from_filing(fact) or fact.concealed or fact.id == current.id:
            continue
        if fact.period.kind != "duration" or not fact.period.end or not current.period.end:
            continue
        gap = day_gap(fact.period.end, current.period.end)
        if gap is None or gap < YOY_GAP_MIN or gap > YOY_GAP_MAX:
            continue
        if fact.concept != current.concept:
            if fact.concept:
                saw_other = True
            continue
        days = _length(fact)
        current_days = _length(current)
        if days is None or current_days is None or abs(days - current_days) > DURATION_DAYS:
            saw_length = True
            continue
        if fact.unit != current.unit:
            saw_currency = True
            continue
        if days < low or days > high:
            saw_length = True
            continue
        chosen.append(fact)
    if chosen:
        ends = {fact.period.end for fact in chosen}
        end = min(ends, key=lambda item: abs((day_gap(item or "", current.period.end or "") or 0) - 365))
        picked = _prefer([fact for fact in chosen if fact.period.end == end])
        if picked is None:
            return DIFFERENT
        return picked
    if saw_length:
        return LENGTHS
    if saw_currency:
        return DOLLARS
    if saw_other:
        return DIFFERENT
    return MISSING


def _shared_duration(
    facts: list[Fact],
    concepts: tuple[str, ...],
    *,
    form: str,
    end: str,
    figure: str,
    measure: str = "money",
) -> tuple[Fact, Fact] | str:
    low, high = _band_for(form)
    if form == "10-Q":
        # Year-to-date cash flow is longer than a quarter. Callers pass the band.
        pass
    current_hits = []
    for concept in concepts:
        found = _near(facts, concept, end, low, high)
        if found is not None:
            current_hits.append(found)
    if not current_hits:
        # A longer year-to-date may be the only duration on a 10-Q.
        if form == "10-Q":
            for concept in concepts:
                found = _longest(facts, concept, end)
                if found is not None:
                    current_hits.append(found)
    if not current_hits:
        return MISSING.format(figure=figure)
    reason = None
    for current in current_hits:
        other = _yoy(facts, current, low, high)
        if isinstance(other, Fact):
            checker = _shares if measure == "shares" else _money
            problem = checker(current) or checker(other)
            if problem:
                return problem
            return current, other
        reason = other
    if reason == DIFFERENT or (len(current_hits) > 1 and reason == MISSING):
        # A concept exists on one side only.
        concepts_now = {fact.concept for fact in current_hits}
        if reason == MISSING and len(concepts_now) == 1:
            return MISSING.format(figure=figure)
        return DIFFERENT if reason == DIFFERENT else (reason or MISSING.format(figure=figure))
    return reason or MISSING.format(figure=figure)


def _longest(facts: list[Fact], concept: str, end: str) -> Fact | None:
    pool = [
        fact
        for fact in facts
        if fact.concept == concept
        and fact.period.kind == "duration"
        and fact.period.end == end
        and _from_filing(fact)
        and not fact.concealed
        and (_length(fact) or 0) > QUARTER_MAX
    ]
    if not pool:
        return None
    longest = max(_length(fact) or 0 for fact in pool)
    return _prefer([fact for fact in pool if _length(fact) == longest])


def _flow_pair(facts: list[Fact], concept: str, *, form: str, end: str, figure: str) -> tuple[Fact, Fact] | str:
    """10-Q cash flow and the profit beside it use the year-to-date duration."""
    if form == "10-Q":
        current = _longest(facts, concept, end) or _near(facts, concept, end, *quarter_band())
    else:
        current = _near(facts, concept, end, *year_band())
    if current is None:
        return MISSING.format(figure=figure)
    low, high = quarter_band() if (_length(current) or 0) <= QUARTER_MAX else (1, 400)
    other = _yoy(facts, current, low, high)
    if isinstance(other, str):
        if other == MISSING:
            return MISSING.format(figure=figure)
        return other
    problem = _money(current) or _money(other)
    if problem:
        return problem
    return current, other


def _not(check_id: str, reason: str) -> CheckResult:
    return CheckResult(check_id, "not_run", reason)


def _growth(current: Decimal, prior: Decimal) -> Decimal | None:
    if prior == 0:
        return None
    return _one((current / prior - 1) * Decimal(100))


def check_cash_flow(facts: list[Fact], *, form: str, period_end: str) -> CheckResult:
    ni = _flow_pair(facts, "NetIncomeLoss", form=form, end=period_end, figure="Net income")
    ocf = _flow_pair(
        facts,
        "NetCashProvidedByUsedInOperatingActivities",
        form=form,
        end=period_end,
        figure="Operating cash flow",
    )
    if isinstance(ni, str):
        return _not("C1", ni if ni != DIFFERENT else ni)
    if isinstance(ocf, str):
        return _not("C1", ocf)
    ni_now, ni_then = ni
    ocf_now, ocf_then = ocf
    if ni_now.period.end != ocf_now.period.end or abs((_length(ni_now) or 0) - (_length(ocf_now) or 0)) > DURATION_DAYS:
        return _not("C1", LENGTHS)
    if ni_now.value <= 0:
        return _not("C1", "There is no profit to compare cash flow with.")
    raw_ratio = ocf_now.value / ni_now.value
    numbers = {"ratio": _one(raw_ratio)}
    used = [ocf_now, ni_now]
    if ni_then.value > 0:
        numbers["ratio_prior"] = _one(ocf_then.value / ni_then.value)
        used.extend([ocf_then, ni_then])
    outcome = "unusual" if raw_ratio < CASH_CONVERSION else "consistent"
    return CheckResult(
        "C1",
        outcome,
        facts=tuple(used),
        numbers=numbers,
        formula="operating cash flow / net income",
    )


def check_receivables(facts: list[Fact], *, form: str, period_end: str) -> CheckResult:
    if form != "10-K":
        return _not("C2", "Needs the annual report.")
    revenue = _shared_duration(facts, REVENUE, form=form, end=period_end, figure="Revenue")
    if isinstance(revenue, str):
        return _not("C2", revenue)
    receivables = _instant_pair(facts, "AccountsReceivableNetCurrent", period_end, "Accounts receivable")
    if isinstance(receivables, str):
        return _not("C2", receivables)
    rev_now, rev_then = revenue
    ar_now, ar_then = receivables
    if ar_then.value <= 0 or rev_then.value <= 0:
        return _not("C2", "The earlier receivables or revenue figure is zero or less.")
    g_ar_raw = ar_now.value / ar_then.value - 1
    g_rev_raw = rev_now.value / rev_then.value - 1
    gap = g_ar_raw - g_rev_raw
    days_now = _one(ar_now.value / rev_now.value * Decimal(365))
    days_then = _one(ar_then.value / rev_then.value * Decimal(365))
    outcome = "unusual" if gap >= RECEIVABLES_GAP else "consistent"
    return CheckResult(
        "C2",
        outcome,
        facts=(ar_now, ar_then, rev_now, rev_then),
        numbers={
            "g_ar": _pct(g_ar_raw),
            "g_rev": _pct(g_rev_raw),
            "days_now": days_now,
            "days_then": days_then,
            "gap": gap,
        },
        formula="(receivables now / receivables earlier - 1) - (revenue now / revenue earlier - 1)",
    )


def _instant_pair(facts: list[Fact], concept: str, end: str, figure: str) -> tuple[Fact, Fact] | str:
    current = _at(facts, concept, end)
    if current is None:
        return MISSING.format(figure=figure)
    problem = _money(current)
    if problem:
        return problem
    earlier = _instant_prior(facts, current)
    if isinstance(earlier, str):
        return MISSING.format(figure=figure) if earlier == MISSING else earlier
    problem = _money(earlier)
    if problem:
        return problem
    return current, earlier


def _at(facts: list[Fact], concept: str, end: str) -> Fact | None:
    pool = [
        fact
        for fact in facts
        if fact.concept == concept
        and fact.period.kind == "instant"
        and fact.period.end == end
        and _from_filing(fact)
        and not fact.concealed
    ]
    return _prefer(pool)


def _instant_prior(facts: list[Fact], current: Fact) -> Fact | str:
    chosen = []
    for fact in facts:
        if fact.concept != current.concept or fact.period.kind != "instant" or not fact.period.end:
            continue
        if not _from_filing(fact) or fact.concealed or fact.id == current.id:
            continue
        gap = day_gap(fact.period.end, current.period.end or "")
        if gap is None or gap < YOY_GAP_MIN or gap > YOY_GAP_MAX:
            continue
        if fact.unit != current.unit:
            return DOLLARS
        chosen.append(fact)
    if not chosen:
        return MISSING
    latest = max(fact.period.end or "" for fact in chosen)
    picked = _prefer([fact for fact in chosen if fact.period.end == latest])
    return picked if picked is not None else MISSING


def check_inventory(facts: list[Fact], *, form: str, period_end: str) -> CheckResult:
    if form != "10-K":
        return _not("C3", "Needs the annual report.")
    current_inv = _at(facts, "InventoryNet", period_end)
    if current_inv is None:
        # No inventory anywhere for this period.
        any_inv = any(fact.concept == "InventoryNet" and _from_filing(fact) for fact in facts)
        if not any_inv:
            return _not("C3", "This company reports no inventory.")
        return _not("C3", MISSING.format(figure="Inventory"))
    pair = _instant_pair(facts, "InventoryNet", period_end, "Inventory")
    if isinstance(pair, str):
        if pair == MISSING.format(figure="Inventory"):
            return _not("C3", "The earlier inventory figure is zero or less.") if False else _not("C3", pair)
        return _not("C3", pair)
    inv_now, inv_then = pair
    if inv_then.value <= 0:
        return _not("C3", "The earlier inventory figure is zero or less.")
    cost = _cost_pair(facts, form=form, end=period_end)
    if isinstance(cost, str):
        return _not("C3", cost)
    cost_now, cost_then, label = cost
    if cost_then.value <= 0:
        if label == "revenue":
            return _not("C3", "The earlier revenue figure is zero or less.")
        return _not("C3", "The earlier cost of sales figure is zero or less.")
    g_inv_raw = inv_now.value / inv_then.value - 1
    g_cost_raw = cost_now.value / cost_then.value - 1
    gap = g_inv_raw - g_cost_raw
    outcome = "unusual" if gap >= INVENTORY_GAP else "consistent"
    return CheckResult(
        "C3",
        outcome,
        facts=(inv_now, inv_then, cost_now, cost_then),
        numbers={"g_inv": _pct(g_inv_raw), "g_cost": _pct(g_cost_raw), "gap": gap},
        labels={"cost": label},
        formula="(inventory now / inventory earlier - 1) - (cost now / cost earlier - 1)",
    )


def _cost_pair(facts: list[Fact], *, form: str, end: str) -> tuple[Fact, Fact, str] | str:
    for concept, label in (
        ("CostOfGoodsAndServicesSold", "cost of sales"),
        ("CostOfRevenue", "cost of sales"),
    ):
        found = _shared_duration(facts, (concept,), form=form, end=end, figure="Cost of sales")
        if isinstance(found, tuple):
            return found[0], found[1], label
        if found == DIFFERENT or found == LENGTHS or found == DOLLARS:
            return found
    revenue = _shared_duration(facts, REVENUE, form=form, end=end, figure="Revenue")
    if isinstance(revenue, str):
        return revenue
    return revenue[0], revenue[1], "revenue"


def _sign_charge(fact: Fact) -> bool:
    if fact.concept in _GAINS:
        return fact.value < 0
    return fact.value >= 0


def check_items(facts: list[Fact], *, form: str, period_end: str) -> CheckResult:
    low, high = _band_for(form)
    operating = _near(facts, "OperatingIncomeLoss", period_end, low, high)
    if operating is None and form == "10-Q":
        operating = _longest(facts, "OperatingIncomeLoss", period_end)
    if operating is None:
        return _not("C4", MISSING.format(figure="Operating income"))
    problem = _money(operating)
    if problem:
        return _not("C4", problem)
    if operating.value == 0:
        tagged = _tagged(facts, operating)
        if not tagged:
            return _not("C4", "No one-off items are tagged.")
        return _not("C4", "Operating income is zero.")
    tagged = _tagged(facts, operating)
    if not tagged:
        return _not("C4", "No one-off items are tagged.")
    shares = []
    for fact in tagged:
        raw_share = abs(fact.value) / abs(operating.value)
        shares.append(ItemShare(fact, raw_share, _sign_charge(fact)))
    flagged = tuple(item for item in shares if item.share >= ONE_OFF_SHARE)
    outcome = "unusual" if flagged else "consistent"
    return CheckResult(
        "C4",
        outcome,
        facts=tuple(item.fact for item in flagged) + (operating,),
        items=flagged,
        numbers={"operating": operating.value},
        formula="absolute item / absolute operating income",
    )


def _tagged(facts: list[Fact], operating: Fact) -> list[Fact]:
    found = []
    for concept in ONE_OFF:
        for fact in facts:
            if fact.concept != concept or not _from_filing(fact) or fact.concealed:
                continue
            if fact.period.kind != "duration" or fact.period.end != operating.period.end:
                continue
            left, right = _length(fact), _length(operating)
            if left is None or right is None or abs(left - right) > DURATION_DAYS:
                continue
            if _base(fact.unit) != "USD":
                continue
            found.append(fact)
    # One fact per concept, preferring agreement.
    kept: list[Fact] = []
    for concept in ONE_OFF:
        group = [fact for fact in found if fact.concept == concept and fact.unit == operating.unit]
        if not group:
            group = [fact for fact in found if fact.concept == concept]
        picked = _prefer(group) if group else None
        if picked is not None:
            kept.append(picked)
    return kept


def check_dilution(facts: list[Fact], *, form: str, period_end: str) -> CheckResult:
    diluted = _shared_duration(
        facts,
        ("WeightedAverageNumberOfDilutedSharesOutstanding",),
        form=form,
        end=period_end,
        figure="Diluted shares",
        measure="shares",
    )
    basic = _shared_duration(
        facts,
        ("WeightedAverageNumberOfSharesOutstandingBasic",),
        form=form,
        end=period_end,
        figure="Basic shares",
        measure="shares",
    )
    if isinstance(diluted, str):
        if diluted == MISSING:
            return _not("C6", "The earlier diluted share count is not available.")
        return _not("C6", diluted)
    if isinstance(basic, str):
        if basic == MISSING:
            return _not("C6", "Basic shares is not in the filing.")
        return _not("C6", basic)
    diluted_now, diluted_then = diluted
    basic_now, basic_then = basic
    for fact in (diluted_now, diluted_then, basic_now, basic_then):
        problem = _shares(fact)
        if problem:
            return _not("C6", problem)
    if diluted_then.value <= 0:
        return _not("C6", "The earlier diluted share count is not available.")
    if basic_now.value <= 0:
        return _not("C6", "The basic share count is zero or less.")
    growth_raw = diluted_now.value / diluted_then.value - 1
    gap_raw = diluted_now.value / basic_now.value - 1
    outcome = "unusual" if growth_raw >= DILUTION or gap_raw >= DILUTION else "consistent"
    return CheckResult(
        "C6",
        outcome,
        facts=(diluted_now, diluted_then, basic_now),
        numbers={"growth": _pct(growth_raw), "gap": _pct(gap_raw)},
        formula="diluted shares now / diluted shares earlier - 1",
    )


def check_margins(facts: list[Fact], *, form: str, period_end: str) -> CheckResult:
    revenue = _shared_duration(facts, REVENUE, form=form, end=period_end, figure="Revenue")
    if isinstance(revenue, str):
        return _not("C7", revenue)
    rev_now, rev_then = revenue
    if rev_now.value <= 0 or rev_then.value <= 0:
        return _not("C7", "Revenue is zero or less in one of the periods.")
    gross = _gross_pair(facts, rev_now, rev_then, form=form, end=period_end)
    operating = _shared_duration(facts, ("OperatingIncomeLoss",), form=form, end=period_end, figure="Operating income")
    numbers: dict[str, Decimal] = {}
    used: list[Fact] = [rev_now, rev_then]
    if isinstance(gross, tuple):
        gp_now, gp_then = gross
        gm_now = gp_now.value / rev_now.value * Decimal(100)
        gm_then = gp_then.value / rev_then.value * Decimal(100)
        numbers["gm_now"] = _one(gm_now)
        numbers["gm_then"] = _one(gm_then)
        numbers["gm_delta"] = gm_now - gm_then
        used.extend([gp_now, gp_then])
    elif gross == "The filing reports no gross profit or cost of sales." and isinstance(operating, str):
        return _not("C7", gross)
    if isinstance(operating, tuple):
        oi_now, oi_then = operating
        om_now = oi_now.value / rev_now.value * Decimal(100)
        om_then = oi_then.value / rev_then.value * Decimal(100)
        numbers["om_now"] = _one(om_now)
        numbers["om_then"] = _one(om_then)
        numbers["om_delta"] = om_now - om_then
        used.extend([oi_now, oi_then])
    if "gm_delta" not in numbers and "om_delta" not in numbers:
        if gross == "The filing reports no gross profit or cost of sales.":
            return _not("C7", gross)
        if isinstance(operating, str):
            return _not("C7", operating)
        return _not("C7", "The filing reports no gross profit or cost of sales.")
    swing = False
    for key in ("gm_delta", "om_delta"):
        if key in numbers and abs(numbers[key]) >= MARGIN_POINTS:
            swing = True
    return CheckResult(
        "C7",
        "unusual" if swing else "consistent",
        facts=tuple(used),
        numbers=numbers,
        formula="profit / revenue",
    )


def _gross_pair(facts, rev_now: Fact, rev_then: Fact, *, form: str, end: str):
    found = _shared_duration(facts, ("GrossProfit",), form=form, end=end, figure="Gross profit")
    if isinstance(found, tuple):
        return found
    cost = None
    for concept in COST:
        picked = _shared_duration(facts, (concept,), form=form, end=end, figure="Cost of sales")
        if isinstance(picked, tuple):
            cost = picked
            break
    if cost is None:
        return "The filing reports no gross profit or cost of sales."
    # Gross profit is revenue minus cost. Represent it by attaching the cost facts;
    # the numbers are computed by the caller from revenue and cost. Return synthetic
    # values through the cost facts by using a lightweight stand-in: the caller
    # expects facts with .value. Build nothing new; compute here and stash on a copy.
    return _difference_facts(rev_now, cost[0]), _difference_facts(rev_then, cost[1])


def _difference_facts(revenue: Fact, cost: Fact) -> Fact:
    return Fact(
        id=revenue.id,
        concept="GrossProfit",
        label="Gross profit",
        value=revenue.value - cost.value,
        unit=revenue.unit,
        period=revenue.period,
        source=revenue.source,
        role="gross_profit",
        origin=revenue.origin,
        decimals=revenue.decimals,
        scale=revenue.scale,
        entity=revenue.entity,
    )


def _tax_rate(tax: Fact, pretax: Fact) -> Decimal | None:
    """Income tax over pre-tax income, using each figure's scale. None when the two are not one measure."""
    if pretax.value == 0 or _base(tax.unit) != _base(pretax.unit):
        return None
    whole = pretax.value * (Decimal(10) ** pretax.scale)
    part = tax.value * (Decimal(10) ** tax.scale)
    if whole == 0:
        return None
    rate = part / whole * Decimal(100)
    if _one(rate) == 0 and tax.value != 0 and pretax.value != 0 and abs(rate) >= Decimal("0.05"):
        return None
    return rate


def check_tax(facts: list[Fact], *, form: str, period_end: str) -> CheckResult:
    tax = _shared_duration(facts, ("IncomeTaxExpenseBenefit",), form=form, end=period_end, figure="Income tax")
    if isinstance(tax, str):
        return _not("C8", tax)
    pretax = _shared_duration(facts, PRETAX, form=form, end=period_end, figure="Pre-tax income")
    if isinstance(pretax, str):
        return _not("C8", pretax)
    tax_now, tax_then = tax
    pre_now, pre_then = pretax
    if pre_now.value <= 0 or pre_then.value <= 0:
        return _not("C8", "A tax rate isn't meaningful on a pre-tax loss.")
    rate_now_raw = _tax_rate(tax_now, pre_now)
    rate_then_raw = _tax_rate(tax_then, pre_then)
    if rate_now_raw is None or rate_then_raw is None:
        return _not("C8", DIFFERENT)
    delta = rate_now_raw - rate_then_raw
    outcome = "unusual" if abs(delta) >= TAX_POINTS else "consistent"
    return CheckResult(
        "C8",
        outcome,
        facts=(tax_now, tax_then, pre_now, pre_then),
        numbers={"rate_now": _one(rate_now_raw), "rate_then": _one(rate_then_raw), "delta": delta},
        formula="income tax / pre-tax income",
    )


def run_checks(facts: list[Fact], *, form: str, period_end: str | None) -> list[CheckResult]:
    end = period_end or ""
    return [
        check_cash_flow(facts, form=form, period_end=end),
        check_receivables(facts, form=form, period_end=end),
        check_inventory(facts, form=form, period_end=end),
        check_items(facts, form=form, period_end=end),
        check_dilution(facts, form=form, period_end=end),
        check_margins(facts, form=form, period_end=end),
        check_tax(facts, form=form, period_end=end),
    ]
