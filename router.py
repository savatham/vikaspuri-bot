"""Route a chatbot question with one batched Jev call.

Jev only classifies: what kind of answer is needed and which filters apply. All arithmetic,
dates and lookups happen in code (see answers.py), because Jev is not a calculator.
"""

import re
from dataclasses import dataclass

from typesafe_sdk import Choice, TypeSafeClient

from sheet_data import MILESTONES_FACT, ProjectData

NONE = "none"

INTENTS = {
    "total": "How much money has actually been spent or paid so far (recorded payments), possibly for a payee, category, payment mode, part of the project or month",
    "count": "How many payments or entries there are",
    "list": "Show the individual payment entries or transactions",
    "latest": "The most recent or last payment(s)",
    "ranking": "Who or what received the most or least money: top payees, biggest expenses",
    "breakdown": "A split of spending by month, payee, category, payment mode or part of the project",
    "share_per_owner": "Splitting the recorded project expenses (land, building, other) equally between the owners: each owner's share",
    "fact": "A descriptive fact: floor owners and their children or family, flat layout, size, rooms, interior spending, water or electricity connection, land size or rates, seller, bank, loan, construction milestones or slabs",
    "agreement": "The builder agreement: what is included, allowances, estimated extra costs and buffer, credits or deductions owed by the builder, items to discuss with the builder",
    "open_ended": "Needs explanation, advice, opinion, comparison or reasoning beyond looking up or adding up numbers",
    "off_topic": "A greeting, small talk, or something unrelated to this building project",
}

SECTIONS = {
    "all": "The whole project, or no particular part is mentioned",
    "building": "Building construction: builder, contractors, labour, steel, cement, sand, bricks, painting, granite",
    "land": "Land or property purchase: property cost, registration, broker, advocate, TDS",
    "other": "Other related expenses: permissions, architect, lift, water, electric, tiles, plumbing, pest control, floor mats",
}

GROUPINGS = {
    NONE: "No grouping is asked for",
    "month": "By month or over time",
    "payee": "By person or payee",
    "category": "By expense category",
    "mode": "By payment mode (cash, online, UPI)",
    "section": "By part of the project (land, building, other)",
}

MODE_WORDS = {"Cash": r"cash", "UPI": r"upi|gpay|google pay|phonepe|paytm", "Online": r"online|bank transfer|neft|imps"}


@dataclass(frozen=True)
class Pick:
    value: str
    confidence: float


@dataclass(frozen=True)
class Route:
    intent: Pick
    section: Pick
    payee: Pick
    category: Pick
    mode: Pick
    group_by: Pick
    fact: Pick
    input_tokens: int | None = None


def route(client: TypeSafeClient, question: str, data: ProjectData) -> Route:
    expenses = data.expenses
    payees = sorted(expenses["payee"].dropna().unique())
    categories = sorted(expenses["category"].dropna().unique())
    modes = sorted(expenses["mode"].dropna().unique())

    questions = {
        "intent": Choice(instructions="What kind of answer does this question about a building project need?", criteria=INTENTS),
        "section": Choice(instructions="Which part of the project's expenses does the question refer to?", criteria=SECTIONS),
        "payee": Choice(
            instructions="Which person or payee does the question name?",
            criteria={**{p: None for p in payees}, NONE: "No specific person or payee is named"},
        ),
        "category": Choice(
            instructions="Which expense category does the question ask about?",
            criteria={**{c: None for c in categories}, NONE: "No specific category is mentioned"},
        ),
        "mode": Choice(
            instructions="Which payment method does the question filter on?",
            criteria={**{m: None for m in modes}, NONE: "No payment method is mentioned"},
        ),
        "group_by": Choice(instructions="If the question asks for a split or comparison, what should results be grouped by?", criteria=GROUPINGS),
        "fact": Choice(
            instructions="Which project fact does the question ask about?",
            criteria={
                # A preview of each value tells Jev what vaguely named facts ("Other details") contain.
                **{f: _preview(v) for f, v in data.facts.items() if f != MILESTONES_FACT},
                MILESTONES_FACT: "Slab completion progress and bank loan releases",
                NONE: "None of these facts",
            },
        ),
    }
    response = client.system_one(state={"question": question}, questions=questions)
    picks = {name: Pick(answer.choice, answer.confidence) for name, answer in response.choices.items()}
    result = Route(**picks, input_tokens=response.usage.input_tokens)
    return _apply_literal_matches(question, result, payees, categories)


def _preview(value: str, limit: int = 120) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _apply_literal_matches(question: str, result: Route, payees: list[str], categories: list[str]) -> Route:
    """Names typed in the question beat the model's guess, so set them with full confidence."""
    text = question.lower()
    updates = {}
    for field, names in (("payee", payees), ("category", categories)):
        for name in sorted(names, key=len, reverse=True):
            if re.search(rf"\b{re.escape(name.lower())}\b", text):
                updates[field] = Pick(name, 1.0)
                break
    for mode, pattern in MODE_WORDS.items():
        if re.search(rf"\b({pattern})\b", text):
            updates["mode"] = Pick(mode, 1.0)
            break
    return Route(**{**result.__dict__, **updates})
