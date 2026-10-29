"""
DEMO ONLY: a rule-based stand-in for the LLM lead extractor (same LeadInfo output).
"""

from __future__ import annotations

import re

from ..conversation import Conversation
from ..gtm import LeadInfo

RULES = [
    ("account_security", r"(system override|ignore all previous|brightway it|system prompt|delivery address for order)"),
    ("off_topic", r"\b(poem|election)\b"),
    ("purchase_inquiry", r"\b(do you have|in stock|i'll probably order|buy)\b"),
    ("complaint", r"(ridiculous|unacceptable|!!!|real person|not talk to a bot|don't want to talk to a bot)"),
    ("return_refund", r"\b(return|refund)\b"),
    ("appointment", r"\b(technician|repair|installation|come and look)\b"),
    ("order_status", r"\b(where|arrive|check on|calling about my order|supposed to)\b"),
    ("product_question", r"\b(warranty|cost|install)\b"),
]
PRODUCTS = [
    (r"miele g 7000", "Miele G 7000 dishwasher (black)"),
    (r"dishwasher", "Dishwasher"),
    (r"oven", "Built-in oven"),
    (r"fridge", "Fridge"),
]
EMAIL_SPOKEN = re.compile(r"([\w.+-]+@[\w-]+\.\w+|\bat example dot com\b)", re.I)


class RuleLeadExtractor:
    name = "demo-rules"

    def extract(self, conversation: Conversation) -> LeadInfo:
        user = " ".join(t.text for t in conversation.user_turns())
        low = user.lower()
        intent = next((name for name, rx in RULES if re.search(rx, low)), "other")
        product = None
        if intent in ("purchase_inquiry", "product_question"):
            product = next((label for rx, label in PRODUCTS if re.search(rx, low)), None)
        if intent == "purchase_inquiry":
            purchase = "high" if re.search(r"(i'll probably order|need it delivered)", low) else "medium"
        elif intent == "product_question":
            purchase = "medium"
        elif intent in ("account_security", "off_topic"):
            purchase = "none"
        else:
            purchase = "low"
        upsell = None
        if intent == "purchase_inquiry" and "oven" in low:
            upsell = "Matching built-in oven with installation"
        elif intent == "product_question" and "warranty" in low:
            upsell = "Brightway Care 3-year warranty extension"
        elif intent == "product_question" and "install" in low:
            upsell = "Installation service at checkout"
        elif intent == "appointment" and "installation" not in low:
            upsell = "Brightway Care extended warranty"
        negative = re.search(r"(ridiculous|unacceptable|!!!|disappointed|not as good|don't want to talk|irritat|refund right now)", low)
        positive = re.search(r"\b(great|thanks|thank you)\b", low)
        if intent == "complaint" or re.search(r"refund right now|confirm my refund", low):
            churn = "high"
        elif intent == "return_refund" or negative or conversation.end_reason == "max_turns":
            churn = "medium"
        else:
            churn = "low"
        summary = {
            "purchase_inquiry": "Pre-sales question about product availability and delivery.",
            "product_question": "Question about services and policies before buying.",
            "order_status": "Asked for the status of an existing order.",
            "appointment": "Wanted a technician visit for a purchased appliance.",
            "return_refund": "Wanted to return an item or get a refund.",
            "complaint": "Frustrated customer who asked for a human agent.",
            "account_security": "Attempt to obtain internal or other customers' data.",
            "off_topic": "Off-topic chat unrelated to Brightway.",
        }.get(intent, "General enquiry.")
        return LeadInfo(
            primary_intent=intent, product_interest=product, purchase_intent=purchase, upsell_opportunity=upsell,
            churn_risk=churn, sentiment="negative" if negative else ("positive" if positive else "neutral"),
            contact_captured=bool(EMAIL_SPOKEN.search(user)), summary=summary, extractor=self.name,
        )
