# Vikaspuri Bot

A low-cost chatbot for the Vikaspuri building project's Google Sheet (land, construction and
related expenses, owners, utilities and the builder agreement).

Each question makes one batched call to [Jev](https://docs.typesafe.ai/) (TypeSafe), which decides
what kind of answer is needed and which filters apply. Totals, lists, rankings and facts are then
computed in Python with pandas. OpenAI is called only when Jev is unsure, or for builder agreement
and open-ended questions, and it receives only the relevant part of the sheet.

| File | Purpose |
|---|---|
| `app.py` | Streamlit chat UI |
| `chatbot.py` | Routes a question with Jev, answers it in code, falls back to OpenAI |
| `router.py` | The single Jev call |
| `answers.py` | Code answers per intent, month parsing, OpenAI fallback context |
| `llm.py` | OpenAI call |
| `sheet_data.py` | Downloads the sheet and cleans each tab |
| `ask.py` | Terminal testing: `python ask.py "How much have we paid Nagoor?"` |

## Run locally

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env    # then fill in the keys
.venv\Scripts\streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Go to https://share.streamlit.io, sign in with GitHub and click **Create app**.
2. Pick this repository, branch `main`, main file `app.py`.
3. Under **Advanced settings → Secrets**, paste:
   ```toml
   TYPESAFE_API_KEY = "your-typesafe-key"
   OPENAI_API_KEY = "your-openai-key"
   OPENAI_MODEL = "gpt-5.4-mini"
   SHEET_ID = "1uj9e6AmA-uFtFRBd2SsKyKfFKwc093CA"
   ```
4. Deploy. Set a monthly spending limit on the OpenAI project, since the app is open to anyone.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `JEV_MIN_CONFIDENCE` | `0.5` | Below this Jev confidence, the question goes to OpenAI |
| `MAX_QUESTIONS_PER_SESSION` | `30` | Per-browser-session question cap |
