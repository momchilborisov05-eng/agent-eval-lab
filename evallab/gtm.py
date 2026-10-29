"""
GTM bonus: turn support conversations into structured lead and intent data.

Every support conversation is also market research: what people ask for, which products they want,
who is about to buy and who is about to churn. The extractor returns one fixed-schema record per
conversation (Structured Outputs), which is stored in SQLite and summarised with SQL (analytics.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .conversation import Conversation, format_transcript
from .llm import Usage, ask_json

INTENTS = ["order_status", "appointment", "return_refund", "product_question", "purchase_inquiry",
           "complaint", "account_security", "off_topic", "other"]
LEVELS = ["none", "low", "medium", "high"]

LEAD_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_intent": {"type": "string", "enum": INTENTS},
        "product_interest": {"type": ["string", "null"]},
        "purchase_intent": {"type": "string", "enum": LEVELS},
        "upsell_opportunity": {"type": ["string", "null"]},
        "churn_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "sentiment": {"type": "string", "enum": ["negative", "neutral", "positive"]},
        "contact_captured": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": ["primary_intent", "product_interest", "purchase_intent", "upsell_opportunity", "churn_risk",
                 "sentiment", "contact_captured", "summary"],
    "additionalProperties": False,
}


@dataclass
class LeadInfo:
    primary_intent: str
    product_interest: str | None
    purchase_intent: str
    upsell_opportunity: str | None
    churn_risk: str
    sentiment: str
    contact_captured: bool
    summary: str
    extractor: str = "llm"

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = (
    "You analyse customer-support conversations of Brightway Appliances (a home-appliance retailer) for the "
    "sales and marketing team. Extract structured data about the CUSTOMER, based only on the transcript.\n"
    "- primary_intent: the main reason for contacting support.\n"
    "- product_interest: the product the customer wants to buy or asked about (not products they already own "
    "and only want serviced), or null.\n"
    "- purchase_intent: how likely the customer is to buy something new soon (none/low/medium/high).\n"
    "- upsell_opportunity: one concrete, relevant cross-sell or service (e.g. installation, extended warranty), or null.\n"
    "- churn_risk: risk that this customer stops buying from Brightway, based on frustration and outcome.\n"
    "- contact_captured: true if the customer shared an email or phone number.\n"
    "- summary: one sentence for a CRM note. Do not include personal data in the summary."
)


class LLMLeadExtractor:
    name = "llm"

    def __init__(self, client, usage: Usage | None = None):
        self.client = client
        self.usage = usage

    def extract(self, conversation: Conversation) -> LeadInfo:
        data = ask_json(self.client, SYSTEM_PROMPT, format_transcript(conversation, with_tools=False),
                        LEAD_SCHEMA, max_tokens=2000, effort="low", usage=self.usage)
        return LeadInfo(**data, extractor=self.name)
