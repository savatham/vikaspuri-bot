"""Streamlit chat UI for the Vikaspuri project sheet. Run with: streamlit run app.py"""

import logging
import os
import re

import streamlit as st

from answers import Reply
from chatbot import ask, load_data, make_client
from sheet_data import SECTION_NAMES, ProjectData, inr_short

logger = logging.getLogger(__name__)

MAX_QUESTIONS_PER_SESSION = int(os.getenv("MAX_QUESTIONS_PER_SESSION", "30"))
MAX_QUESTION_LENGTH = 300
WELCOME = (
    "Hello! I'm the Vikaspuri Project Assistant. Ask me anything about the project's land, "
    "construction and related expenses, floor owners, water and electricity details, or the "
    "builder agreement."
)
EXAMPLES = [
    "How much have we paid Nagoor?",
    "What did we spend in August 2026?",
    "Who owns the 3rd floor?",
    "What is each owner's share of the total cost?",
    "Top 5 payees for building construction",
    "Which builder agreement items are extra cost?",
]

# On Streamlit Community Cloud, keys live in st.secrets instead of .env.
try:
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "OPENAI_MODEL", "SHEET_ID"):
        if key in st.secrets and not os.getenv(key):
            os.environ[key] = st.secrets[key]
except FileNotFoundError:
    pass


@st.cache_data(ttl=600, show_spinner="Loading project data...")
def get_data() -> ProjectData:
    return load_data()


@st.cache_resource
def get_client():
    return make_client()


@st.cache_data(ttl=3600, max_entries=2000, show_spinner=False)
def cached_reply(question: str, data_version: str) -> Reply:
    # Keyed on the normalized question and the sheet version, so a repeated question costs nothing
    # until the sheet changes.
    return ask(question, get_data(), get_client())


def normalize(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower()).rstrip("?.! ")


def show(reply: Reply) -> None:
    st.markdown(reply.text)
    if reply.table is not None:
        # Drop columns with nothing in them so tables fit narrow phone screens.
        table = reply.table.loc[:, (reply.table != "").any()]
        st.dataframe(table, hide_index=True, width="stretch")


def pick_example() -> None:
    st.session_state.pending = st.session_state.example
    st.session_state.example = None


def stat_cards(data: ProjectData) -> str:
    totals = data.expenses.groupby("section")["amount"].sum()
    cards = [("Total project", totals.sum())] + [(SECTION_NAMES[s], v) for s, v in totals.items()]
    return '<div class="stats">' + "".join(
        f'<div class="stat"><div class="label">{label}</div><div class="value">{inr_short(value)}</div></div>'
        for label, value in cards
    ) + "</div>"


# Cards wrap to two per row on phones; padding and the title shrink on narrow screens.
STYLE = """
<style>
[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; padding-bottom: 6rem; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.5rem; margin: 0.25rem 0 1rem; }
.stat { border: 1px solid rgba(128, 128, 128, 0.25); border-radius: 0.6rem; padding: 0.55rem 0.75rem; }
.stat .label { font-size: 0.75rem; opacity: 0.7; }
.stat .value { font-size: 1.2rem; font-weight: 600; }
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding: 1rem 0.75rem 6rem; }
  h1 { font-size: 1.5rem !important; }
  .stat .value { font-size: 1.05rem; }
}
</style>
"""

st.set_page_config(page_title="Vikaspuri Project Assistant", page_icon="🏗️", layout="centered", initial_sidebar_state="collapsed")
st.markdown(STYLE, unsafe_allow_html=True)
st.title("🏗️ Vikaspuri Project Assistant")
st.caption("Answers about the Vikaspuri building project, based on the latest project records.")

try:
    data = get_data()
except Exception:
    logger.exception("Loading the project sheet failed")
    st.error("The project data couldn't be loaded right now. Please try again in a few minutes.")
    st.stop()

st.markdown(stat_cards(data), unsafe_allow_html=True)

st.session_state.setdefault("messages", [])
st.session_state.setdefault("asked", 0)

with st.chat_message("assistant"):
    st.markdown(WELCOME)
if not st.session_state.messages and "pending" not in st.session_state:
    st.pills("Try asking", EXAMPLES, key="example", on_change=pick_example)
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            show(message["reply"])
        else:
            st.markdown(message["text"])

question = st.chat_input("Ask about expenses, owners, utilities or the builder agreement") or st.session_state.pop("pending", None)
if question:
    question = question[:MAX_QUESTION_LENGTH]
    st.session_state.messages.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        if st.session_state.asked >= MAX_QUESTIONS_PER_SESSION:
            reply = Reply("You've reached the question limit for this session. Please come back a little later.", path="canned")
        else:
            st.session_state.asked += 1
            with st.spinner("Looking that up..."):
                try:
                    reply = cached_reply(normalize(question), data.version)
                except Exception:
                    logger.exception("Answering failed for question: %s", question)
                    reply = Reply("Sorry, I couldn't answer that just now. Please try again in a moment.", path="canned")
        show(reply)
    st.session_state.messages.append({"role": "assistant", "reply": reply})
