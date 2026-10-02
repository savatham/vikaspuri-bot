"""Turn a Jev route into a reply. Every number is computed with pandas, never by a model.

Questions go to OpenAI only when Jev's routing is unsure, or when they need reasoning or free
text (builder agreement, advice) that code can't answer.
"""

import calendar
import os
import re
from dataclasses import dataclass

import pandas as pd

from llm import ask_openai
from router import NONE, Route
from sheet_data import MILESTONES_FACT, SECTION_NAMES, ProjectData, inr, inr_short

MIN_CONFIDENCE = float(os.getenv("JEV_MIN_CONFIDENCE", "0.5"))

GREETING = (
    "Hi! I can answer questions about the Vikaspuri project: expenses, payees, owners, "
    "water and electricity details, and the builder agreement. Try *\"How much have we paid Nagoor?\"* "
    "or *\"What did we spend in August 2026?\"*"
)

GROUP_LABELS = {"month": "month", "payee": "payee", "category": "category", "mode": "payment mode", "section": "project area"}

_MONTH_NAMES = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTH_NAMES |= {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
_MONTH_NAMES["sept"] = 9
_MONTH_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True)) + r")(?![a-z])"
    r"(?:[\s,]*(\d{4})|\s*'(\d{2})|(\d{2}))?(?!\d)",
    re.IGNORECASE,
)


@dataclass
class Reply:
    text: str
    table: pd.DataFrame | None = None
    path: str = "jev"  # "jev" (answered in code), "jev+openai", "openai" (Jev unavailable), "canned"
    route: Route | None = None
    llm_tokens: int | None = None


@dataclass(frozen=True)
class Period:
    start: pd.Timestamp
    end: pd.Timestamp  # exclusive
    label: str


def answer(question: str, route: Route | None, data: ProjectData, today: pd.Timestamp | None = None) -> Reply:
    if route is None:
        return _ask_llm(question, data, route, path="openai")
    intent = route.intent.value
    if route.intent.confidence < MIN_CONFIDENCE or intent in ("agreement", "open_ended"):
        return _ask_llm(question, data, route)
    if intent == "off_topic":
        return Reply(GREETING, path="canned", route=route)
    if intent == "fact":
        return _fact(question, data, route)

    filters = _filters(route)
    if any(pick.confidence < MIN_CONFIDENCE for pick in filters.values()):
        return _ask_llm(question, data, route)
    period = parse_period(question, data.expenses["date"], today or pd.Timestamp.today())
    rows = _apply(data.expenses, {k: v.value for k, v in filters.items()}, period)
    scope = _describe({k: v.value for k, v in filters.items()}, period)
    if rows.empty:
        return Reply(f"I couldn't find any payments{scope}.", route=route)

    total, count = rows["amount"].sum(), len(rows)
    if intent == "total":
        text = f"**Total{scope or ' project expenses'}: {inr(total)}** ({inr_short(total)}) across {_payments(count)}."
        return Reply(text, route=route)
    if intent == "count":
        return Reply(f"There are **{_payments(count)}**{scope}, totalling {inr(total)} ({inr_short(total)}).", route=route)
    if intent == "share_per_owner":
        share = total / data.owner_count
        text = (
            f"Total{scope or ' project expenses'} is {inr(total)}. Split equally across {data.owner_count} owners, "
            f"that is **{inr(share)}** ({inr_short(share)}) each."
        )
        return Reply(text, route=route)
    if intent in ("list", "latest"):
        shown = rows.sort_values("date", ascending=False)
        if intent == "latest":
            shown = shown.head(_number_in(question) or 5)
            text = f"Latest {_payments(len(shown))}{scope}:"
        else:
            text = f"{_payments(count).capitalize()}{scope}, totalling {inr(total)}:"
        return Reply(text, table=_payment_table(shown), route=route)

    # ranking / breakdown
    group = route.group_by.value
    if intent == "breakdown" and group == NONE:
        group = "month"
    if intent == "ranking" and group in (NONE, "month"):
        group = "category" if filters.get("section") and filters["section"].value == "other" else "payee"
    grouped = _group(rows, group)
    if intent == "ranking":
        ascending = bool(re.search(r"\b(least|lowest|smallest|minimum|fewest)\b", question, re.IGNORECASE))
        grouped = grouped.sort_values("amount", ascending=ascending).head(_number_in(question) or 10)
        top = grouped.iloc[0]
        text = f"{'Lowest' if ascending else 'Highest'}{scope}: **{top[group]}** with {inr(top['amount'])} ({inr_short(top['amount'])})."
    else:
        text = f"Spending{scope} by {GROUP_LABELS[group]}, {inr(total)} in total:"
    return Reply(text, table=_money_table(grouped, group), route=route)


def parse_period(question: str, dates: pd.Series, today: pd.Timestamp) -> Period | None:
    """Find a month, month range or year in the question. Jev reads dates as text, so code does this."""
    text = question.lower()
    this_month = pd.Timestamp(today.year, today.month, 1)
    if "this month" in text:
        return Period(this_month, this_month + pd.offsets.MonthBegin(1), f"{this_month:%b %Y}")
    if "last month" in text or "previous month" in text:
        start = this_month - pd.offsets.MonthBegin(1)
        return Period(start, this_month, f"{start:%b %Y}")
    if "this year" in text:
        return _year(today.year)
    if "last year" in text:
        return _year(today.year - 1)

    months = []
    for match in _MONTH_RE.finditer(text):
        name, year4, year_apos, year_attached = match.groups()
        year = year4 or (f"20{year_apos or year_attached}" if (year_apos or year_attached) else None)
        if name == "may" and not year and not re.search(r"\b(in|of|during|for|since|till|until)\s+may\b", text):
            continue  # "may" as a verb
        month = _MONTH_NAMES[name]
        months.append(pd.Timestamp(int(year) if year else _latest_year(month, dates, today), month, 1))
    if months:
        start, last = min(months), max(months)
        end = last + pd.offsets.MonthBegin(1)
        label = f"{start:%b %Y}" if start == last else f"{start:%b %Y} to {last:%b %Y}"
        return Period(start, end, label)

    year = re.search(r"\b(20\d{2})\b", text)
    return _year(int(year.group(1))) if year else None


def _year(year: int) -> Period:
    return Period(pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1), str(year))


def _latest_year(month: int, dates: pd.Series, today: pd.Timestamp) -> int:
    years = dates[(dates.dt.month == month) & (dates <= today)].dt.year
    return int(years.max()) if not years.empty else today.year


def _payments(count: int) -> str:
    return f"{count} payment{'' if count == 1 else 's'}"


def _number_in(question: str) -> int | None:
    match = re.search(r"\b(?:last|latest|recent|top|first|bottom)\s+(\d{1,3})\b", question, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _filters(route: Route) -> dict:
    filters = {}
    if route.payee.value != NONE:
        filters["payee"] = route.payee
    elif route.category.value != NONE:
        filters["category"] = route.category
    elif route.section.value != "all":
        filters["section"] = route.section
    if route.mode.value != NONE:
        filters["mode"] = route.mode
    return filters


def _apply(expenses: pd.DataFrame, filters: dict[str, str], period: Period | None) -> pd.DataFrame:
    rows = expenses
    for column, value in filters.items():
        rows = rows[rows[column] == value]
    if period:
        rows = rows[(rows["date"] >= period.start) & (rows["date"] < period.end)]
    return rows


def _describe(filters: dict[str, str], period: Period | None) -> str:
    parts = []
    if "section" in filters:
        parts.append(f" on {SECTION_NAMES[filters['section']].lower()} expenses")
    if "payee" in filters:
        parts.append(f" paid to {filters['payee']}")
    if "category" in filters:
        parts.append(f" for {filters['category']}")
    if "mode" in filters:
        parts.append(f" by {filters['mode']}")
    if period:
        parts.append(f" in {period.label}")
    return "".join(parts)


def _group(rows: pd.DataFrame, group: str) -> pd.DataFrame:
    if group == "month":
        key = rows["date"].dt.to_period("M").astype(str)
    elif group == "payee":
        key = rows["payee"].fillna(rows["item"])
    elif group == "section":
        key = rows["section"].map(SECTION_NAMES)
    else:
        key = rows[group].fillna(rows["section"].map(SECTION_NAMES))
    grouped = rows.groupby(key.rename(group))["amount"].agg(amount="sum", payments="count").reset_index()
    if group == "month":
        grouped = grouped.sort_values(group)
        grouped[group] = pd.to_datetime(grouped[group]).dt.strftime("%b %Y")
        return grouped
    return grouped.sort_values("amount", ascending=False)


def _money_table(grouped: pd.DataFrame, group: str) -> pd.DataFrame:
    table = grouped.copy()
    table["amount"] = table["amount"].map(inr)
    return table.rename(columns={group: GROUP_LABELS[group].capitalize(), "amount": "Amount", "payments": "Payments"})


def _payment_table(rows: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": rows["date"].dt.strftime("%d %b %Y"),
            "Paid to / Item": rows["payee"].fillna(rows["item"]),
            "Details": rows["item"].where(rows["payee"].notna(), rows["category"]),
            "Mode": rows["mode"],
            "Amount": rows["amount"].map(inr),
            "Notes": rows["notes"],
        }
    ).fillna("")


def _fact(question: str, data: ProjectData, route: Route) -> Reply:
    fact = route.fact
    if fact.value == NONE or fact.confidence < MIN_CONFIDENCE:
        return _ask_llm(question, data, route)
    if fact.value == MILESTONES_FACT:
        table = data.milestones.assign(
            date=data.milestones["date"].dt.strftime("%d %b %Y"),
            paid_so_far=data.milestones["paid_so_far"].map(lambda v: "" if pd.isna(v) else inr(v)),
        ).rename(columns={"date": "Date", "event": "Milestone", "paid_so_far": "Building paid so far"})
        return Reply("Construction milestones and loan releases recorded in the sheet:", table=table, route=route)
    value = data.facts[fact.value]
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if lines and all(line.endswith(":") for line in lines):
        return Reply(f"**{fact.value}** haven't been filled in the sheet yet.", route=route)
    return Reply(f"**{fact.value}:**  \n" + "  \n".join(lines), route=route)


def _ask_llm(question: str, data: ProjectData, route: Route | None, path: str = "jev+openai") -> Reply:
    text, tokens = ask_openai(question, build_context(data, route))
    return Reply(text, path=path, route=route, llm_tokens=tokens)


def build_context(data: ProjectData, route: Route | None) -> str:
    """Send OpenAI only the part of the sheet the question is about, to keep tokens down."""
    expenses = data.expenses
    totals = expenses.groupby("section")["amount"].sum()
    overview = [f"{SECTION_NAMES[s]} expenses: {inr(v)}" for s, v in totals.items()]
    overview += [f"Total project expenses: {inr(totals.sum())}", f"Number of owners sharing costs: {data.owner_count}"]
    parts = ["OVERVIEW\n" + "\n".join(overview), "FACTS\n" + "\n".join(f"{k}: {v}" for k, v in data.facts.items())]

    intent = route.intent.value if route else None
    if intent == "agreement" or route is None:
        summary = "\n".join(f"{k}: {v}" for k, v in data.agreement_summary.items())
        parts.append("BUILDER AGREEMENT ITEMS (CSV)\n" + data.agreement.to_csv(index=False) + summary)
    if intent not in ("agreement", "fact", "off_topic"):
        rows = expenses
        if route and route.section.value != "all" and route.section.confidence >= MIN_CONFIDENCE:
            rows = rows[rows["section"] == route.section.value]
        csv = rows.assign(date=rows["date"].dt.strftime("%Y-%m-%d")).to_csv(index=False)
        parts.append("EXPENSE ENTRIES (CSV)\n" + csv)
        milestones = data.milestones.assign(date=data.milestones["date"].dt.strftime("%Y-%m-%d"))
        parts.append("MILESTONES (CSV)\n" + milestones.to_csv(index=False))
    return "\n\n".join(parts)
