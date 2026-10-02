"""One entry point for a question: route with Jev, answer in code, fall back to OpenAI."""

import logging
import os

from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from answers import Reply, answer
from router import route
from sheet_data import ProjectData, download_workbook, parse_workbook

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_SHEET_ID = "1uj9e6AmA-uFtFRBd2SsKyKfFKwc093CA"


def load_data() -> ProjectData:
    return parse_workbook(download_workbook(os.getenv("SHEET_ID", DEFAULT_SHEET_ID)))


def make_client() -> TypeSafeClient:
    return TypeSafeClient(api_key=os.getenv("TYPESAFE_API_KEY"))


def ask(question: str, data: ProjectData, client: TypeSafeClient) -> Reply:
    try:
        jev_route = route(client, question, data)
    except Exception:
        # Jev being down shouldn't take the chatbot down; OpenAI can still answer with the full data.
        logger.exception("Jev routing failed")
        jev_route = None
    return answer(question, jev_route, data)
