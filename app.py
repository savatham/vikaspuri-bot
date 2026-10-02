"""Streamlit chat UI for the Vikaspuri project sheet. Run with: streamlit run app.py"""

import os
import re

import streamlit as st

from answers import Reply
from chatbot import ask, load_data, make_client
from sheet_data import ProjectData, SECTION_NAMES, inr_short

MAX_QUESTIONS_PER_SESSION = int(os.getenv("MAX_QUESTIONS_PER_SESSION", "30"))
MAX_QUESTION_LENGTH = 300
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


@st.cache_data(ttl=600, show_spinner="Loading the project sheet...")
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
        st.dataframe(reply.table, hide_index=True, width="stretch")
    labels = {"jev": "Answered by Jev + code", "canned": "Answered by Jev + code", "jev+openai": "Jev routed to OpenAI", "openai": "OpenAI (Jev unavailable)"}
    caption = labels.get(reply.path, reply.path)
    if reply.route:
        caption += f" · intent `{reply.route.intent.value}` ({reply.route.intent.confidence:.0%})"
    st.caption(caption)


st.set_page_config(page_title="Vikaspuri Project Assistant", page_icon="🏗️")
st.title("Vikaspuri Project Assistant")

data = get_data()
with st.sidebar:
    totals = data.expenses.groupby("section")["amount"].sum()
    st.metric("Total project expenses", inr_short(totals.sum()))
    for section, amount in totals.items():
        st.write(f"{SECTION_NAMES[section]}: **{inr_short(amount)}**")
    if st.button("Refresh sheet data"):
        get_data.clear()
        st.rerun()
    st.subheader("Try asking")
    for example in EXAMPLES:
        if st.button(example, width="stretch"):
            st.session_state.pending = example

st.session_state.setdefault("messages", [])
st.session_state.setdefault("asked", 0)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        show(message["reply"]) if message["role"] == "assistant" else st.markdown(message["text"])

question = st.chat_input("Ask about expenses, owners, utilities or the builder agreement") or st.session_state.pop("pending", None)
if question:
    question = question[:MAX_QUESTION_LENGTH]
    st.session_state.messages.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        if st.session_state.asked >= MAX_QUESTIONS_PER_SESSION:
            reply = Reply(f"You've reached the limit of {MAX_QUESTIONS_PER_SESSION} questions for this session.", path="canned")
        else:
            st.session_state.asked += 1
            with st.spinner("Thinking..."):
                try:
                    reply = cached_reply(normalize(question), data.version)
                except Exception as error:
                    reply = Reply(f"Sorry, something went wrong answering that ({type(error).__name__}). Please try again.", path="canned")
        show(reply)
    st.session_state.messages.append({"role": "assistant", "reply": reply})
