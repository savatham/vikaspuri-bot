"""OpenAI fallback for questions Jev routing can't answer from code alone."""

import os

from openai import OpenAI

SYSTEM_PROMPT = """You answer questions about the Vikaspuri building project (land purchase, construction \
and related expenses) for its owners. Use only the project data below. Amounts are in Indian rupees; \
write them in Indian style (e.g. ₹94,00,000 or ₹94 lakh, ₹8.06 crore). Be concise and give exact figures \
from the data. If the data does not contain the answer, say so plainly instead of guessing.
For the builder agreement, keep extra costs (owners pay the builder more) separate from credits \
(the builder deducts for items the owners bought or work that was omitted). Answer only what was \
asked and do not offer follow-up tasks.

PROJECT DATA
{context}"""


def ask_openai(question: str, context: str) -> tuple[str, int | None]:
    """Return the answer text and the total tokens used."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # The data goes first and the question last so OpenAI's automatic prompt caching can reuse the prefix.
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
            {"role": "user", "content": question},
        ],
    )
    usage = response.usage.total_tokens if response.usage else None
    return response.choices[0].message.content or "", usage
