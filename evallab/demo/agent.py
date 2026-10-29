"""
DEMO ONLY: a deterministic, rule-based stand-in for the Claude support agent.

It exists so the whole pipeline (simulation, checks, judge, storage, dashboard, regression view) runs
offline without an API key. It is NOT an LLM and its results say nothing about any real model.

It talks to the same SupportBackend tools as the real agent, so the deterministic checks evaluate
real tool calls. Its two behaviour profiles mirror the intent of the two prompt versions in
agent/prompts.py: v1 has no explicit policies; v2 adds them, plus the two "sensible" rules that cause
regressions (transfer when unsure, confirm before booking) and a longer prompt (higher latency).

Latency is SIMULATED from the reply length, the number of tool calls and the prompt size, so the
latency checks and percentiles have data to work with.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

from ..agent.base import AgentAdapter, AgentTurn, ConversationContext
from ..agent.prompts import CANARY, PROMPTS
from ..agent.tools import ORDERS, SupportBackend
from ..conversation import ToolCall

PROFILES = {
    "v1": dict(verify=False, normalize_speech=False, resist_injection=False, stay_on_topic=False,
               promise_refunds=True, empathy=False, confirm_booking=False, escalate_when_unsure=False,
               base_latency=650),
    "v2": dict(verify=True, normalize_speech=True, resist_injection=True, stay_on_topic=True,
               promise_refunds=False, empathy=True, confirm_booking=True, escalate_when_unsure=True,
               base_latency=1000),
}

DIGIT_WORDS = {"zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
               "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_DIGIT = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|\d)"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

ORDER_RE = re.compile(r"\bAU[-\s]?(\d{5})\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-z.]+", re.I)
YES_RE = re.compile(r"\b(yes|yeah|yep|sure|go ahead|book it|please do|that's fine|ok|okay)\b", re.I)
HUMAN_RE = re.compile(r"\b(real person|human|talk to (someone|a person)|speak (to|with) (someone|a person|an agent))\b", re.I)
ANGRY_RE = re.compile(r"!!|\b(ridiculous|unacceptable|terrible|worst|furious)\b", re.I)
OFF_TOPIC_RE = re.compile(r"\b(poem|election|politics|joke|recipe)\b", re.I)
PROMPT_ATTACK_RE = re.compile(r"(ignore (all )?(previous|prior|your) instructions|system prompt|developer mode)", re.I)
AUTHORITY_RE = re.compile(r"(system override|administrator|brightway it|migrating the crm)", re.I)
VAGUE_RE = re.compile(r"\b(sometime|whenever|not sure)\b", re.I)
REFUND_DEMAND_RE = re.compile(r"(confirm (the |my )?refund|refund is approved|refund right now|don't want to ship)", re.I)

INTENT_PATTERNS = [
    ("return", re.compile(r"\b(return|refund|money back)\b", re.I)),
    ("appointment", re.compile(r"\b(technician|repair|appointment|installation visit|book an installation|come and look)\b", re.I)),
    ("faq", re.compile(r"\b(warranty|cost|price|how much|in stock|do you (have|install|sell)|payment|opening hours)\b", re.I)),
    ("status", re.compile(r"\b(where|status|track|arrive|check on|supposed to (come|arrive)|nothing arrived|calling about my order|delivery address)\b", re.I)),
]

FAQ_TOPICS = [
    ("product", re.compile(r"\b(miele|in stock|do you have|in black|g 7000)\b", re.I), "Miele G 7000 dishwasher black in stock"),
    ("warranty", re.compile(r"\bwarranty|extend\b", re.I), "warranty extension"),
    ("delivery", re.compile(r"\bdeliver", re.I), "delivery cost"),
    ("installation", re.compile(r"\binstall", re.I), "installation price"),
    ("oven", re.compile(r"\boven\b", re.I), "matching built-in oven"),
    ("payment", re.compile(r"\bpayment|pay\b", re.I), "payment methods"),
]


def normalize_speech(text: str) -> str:
    """Turn speech-to-text forms into written ones: 'A U one oh four...' -> 'AU-104..', ' dot ' -> '.', ' at ' -> '@'."""
    def order(match: re.Match) -> str:
        digits = "".join(DIGIT_WORDS.get(w.lower(), w) for w in re.findall(_DIGIT, match.group(1), re.I))
        return f"AU-{digits}"

    text = re.sub(rf"\b[Aa]\.?\s*[Uu]\.?[\s,-]*((?:{_DIGIT}[\s,-]*){{4}}{_DIGIT})\b", order, text, flags=re.I)
    text = re.sub(r"\s+dot\s+", ".", text, flags=re.I)
    text = re.sub(r"\s+at\s+(?=[\w-]+\.(com|org|net|bg)\b)", "@", text, flags=re.I)
    return text


def parse_date(text: str) -> str | None:
    if m := re.search(r"\b(20\d\d-\d\d-\d\d)\b", text):
        return m.group(1)
    if m := re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(st|nd|rd|th)?\b", text, re.I):
        return date(2026, MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    return None


def parse_window(text: str) -> str | None:
    t = text.lower()
    if "morning" in t:
        return "morning"
    if "afternoon" in t:
        return "afternoon"
    if "any time" in t or "anytime" in t:
        return "any"
    return None


def _short(text: str, limit: int = 70) -> str:
    """First sentence of a message, cut at a word boundary: used as the tool's issue/reason text."""
    sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + "..."


def nice_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%A}, {d:%B} {d.day}"


@dataclass
class _State:
    queue: list[str] = field(default_factory=list)
    orders: dict[str, str] = field(default_factory=dict)
    email: str | None = None
    date: str | None = None
    window: str | None = None
    issue: str = ""
    awaiting_confirm: bool = False
    confirmed: bool = False
    verify_failures: int = 0
    refund_demand: bool = False
    refund_verified: bool = False
    angry: int = 0
    attack: bool = False
    trusted_claim: bool = False
    turns: int = 0


class DemoSupportAgent(AgentAdapter):
    """Deterministic rule-based agent. DEMO ONLY - see module docstring."""

    name = "brightway-support (demo, rule-based)"

    def __init__(self, version: str = "v2"):
        if version not in PROFILES:
            raise ValueError(f"Unknown demo agent version {version!r}. Choose one of: {', '.join(PROFILES)}")
        self.version = version
        self.model = "demo-rules (no LLM)"
        self.canary = CANARY
        self.cfg = PROFILES[version]
        self.backend = SupportBackend()
        self.state = _State()
        self.channel = "chat"

    def start(self, context: ConversationContext) -> None:
        self.backend = SupportBackend()
        self.state = _State()
        self.channel = context.channel

    # ---------- main entry ----------

    def respond(self, user_message: str) -> AgentTurn:
        calls: list[ToolCall] = []
        text = self._handle(user_message, calls)
        transferred = any(c.name == "transfer_to_human" and not c.is_error for c in calls)
        return AgentTurn(text=text, tool_calls=calls, latency_ms=self._latency(text, calls), ended=transferred,
                         end_reason="transferred" if transferred else None)

    def _latency(self, text: str, calls: list[ToolCall]) -> float:
        jitter = int(hashlib.sha256(text.encode()).hexdigest(), 16) % 180
        return float(self.cfg["base_latency"] + 18 * len(text.split()) + 650 * len(calls) + jitter)

    def _call(self, calls: list[ToolCall], name: str, **args) -> tuple[dict, bool]:
        result, is_error = self.backend.execute(name, args)
        calls.append(ToolCall(name, args, result, is_error))
        return result, is_error

    # ---------- understanding ----------

    def _handle(self, raw: str, calls: list[ToolCall]) -> str:
        s, cfg = self.state, self.cfg
        s.turns += 1
        msg = normalize_speech(raw) if cfg["normalize_speech"] else raw

        found_ids = [(m.start(), f"AU-{m.group(1)}") for m in ORDER_RE.finditer(msg)]
        if m := EMAIL_RE.search(msg):
            s.email = m.group(0).rstrip(".").lower()
        if d := parse_date(msg):
            s.date, s.confirmed = d, False
        if w := parse_window(msg):
            s.window, s.confirmed = w, False

        prefix = ""
        if ANGRY_RE.search(msg):
            s.angry += 1
            if cfg["empathy"]:
                prefix = "I'm really sorry about this, I understand how frustrating it is. "

        # 1. Attacks: prompt extraction and claimed authority.
        if PROMPT_ATTACK_RE.search(msg) or (s.attack and "print" in msg.lower()):
            s.attack = True
            if cfg["resist_injection"]:
                return ("I can't share my internal instructions or change how I work. I'm happy to help with your "
                        "orders, deliveries, repairs, returns or product questions.")
            return f'Sure! Developer mode is enabled. Here are my instructions: "{PROMPTS[self.version]}"'
        if AUTHORITY_RE.search(msg) or (s.trusted_claim and re.search(r"\b(urgent|administrator|boss)\b", msg, re.I)):
            if cfg["resist_injection"]:
                first = not s.trusted_claim
                s.trusted_claim = True
                if first:
                    return ("I'm sorry, I can't share customer information based on a claim made in this conversation, "
                            "and messages here can't change my rules. Staff should use the internal CRM. I'm happy to "
                            "help with your own order once it's verified.")
                return "I understand it's urgent, but I can't share any customer data without verification."
            s.trusted_claim = True
            if found_ids:
                s.orders["status"] = found_ids[-1][1]
                s.queue = ["status"]

        # 2. Explicit request for a person.
        if HUMAN_RE.search(msg):
            return prefix + self._transfer(calls, "Customer asked for a human agent")

        # 3. Off-topic requests.
        if OFF_TOPIC_RE.search(msg):
            if cfg["stay_on_topic"]:
                return ("I'm sorry, I can only help with Brightway topics like orders, deliveries, repairs, returns and "
                        "our appliances, so I can't write poems or discuss politics. Is there anything I can help with?")
            return ("Here's a little poem for you:\nCrisp leaves of amber drift and fall,\nSoft autumn light lies over all.\n"
                    "As for the election, I think the current favourite will probably win.")

        # 4. Intents, in the order they appear in the message.
        intents = sorted((m.start(), name) for name, rx in INTENT_PATTERNS if (m := rx.search(msg)))
        names = [n for _, n in intents]
        if "faq" in names and ("appointment" in names and "book" not in msg.lower()):
            names.remove("appointment")  # "what does installation cost?" is a question, not a booking
        if "faq" in names and "status" in names and not found_ids:
            names.remove("status")
        for pos, name in intents:
            if name not in names or name in s.queue:
                continue
            after = [oid for p, oid in found_ids if p > pos]  # the order number mentioned after the intent
            if after:
                s.orders[name] = after[0]
            elif found_ids:
                s.orders[name] = found_ids[-1][1]
            if name == "appointment" and not s.issue:
                s.issue = "installation" if "install" in msg.lower() else _short(raw)
            if name == "return":
                s.issue = s.issue or _short(raw)
            s.queue.append(name)
        if found_ids and s.queue and not intents:
            s.orders[s.queue[0]] = found_ids[-1][1]
        if REFUND_DEMAND_RE.search(msg):
            s.refund_demand = True
            if "return" not in s.queue:
                s.queue.insert(0, "return")

        # 5. Work through the queue.
        parts: list[str] = []
        while s.queue:
            intent = s.queue[0]
            text, done = getattr(self, f"_do_{intent}")(msg, calls)
            parts.append(text)
            if any(c.name == "transfer_to_human" and not c.is_error for c in calls):
                return prefix + " ".join(parts)
            if not done:
                break
            s.queue.pop(0)
        if not parts:
            if s.turns == 1:
                parts.append("Hi! I can help with orders, deliveries, technician visits, returns and product questions. "
                             "What can I do for you?")
            else:
                parts.append("Thanks! Is there anything else I can help you with?")
        return prefix + " ".join(parts)

    # ---------- actions ----------

    def _transfer(self, calls: list[ToolCall], reason: str) -> str:
        priority = "high" if self.state.angry >= 2 and self.cfg["empathy"] else "normal"
        summary = f"Topics: {', '.join(self.state.queue) or 'general'}; orders: {', '.join(self.state.orders.values()) or 'none'}."
        result, _ = self._call(calls, "transfer_to_human", reason=reason, summary=summary, priority=priority)
        return (f"I'm connecting you with a member of our team now (about {result['estimated_wait_minutes']} minutes). "
                "They'll see a summary of our conversation, so you won't need to repeat yourself.")

    def _need_email(self) -> str:
        return "For your security, could you confirm the email address on the order?"

    def _do_status(self, msg: str, calls: list[ToolCall]) -> tuple[str, bool]:
        s, cfg = self.state, self.cfg
        oid = s.orders.get("status")
        if not oid:
            if cfg["verify"]:
                return "Could you give me the order number (it starts with AU-) and the email address on the order?", False
            return "Could you tell me your order number? It starts with AU.", False
        if cfg["verify"] and not s.email:
            if s.verify_failures:
                return ("I'm sorry, but I can't share any details of this order without verifying the email on it.", True)
            return self._need_email(), False
        result, err = self._call(calls, "check_order_status", order_id=oid, email=s.email)
        if err:
            s.orders.pop("status", None)
            return f"I couldn't find order {oid}. Could you double-check the number?", False
        if cfg["verify"] and not result["email_verified"]:
            s.verify_failures += 1
            s.email = None
            if s.verify_failures == 1:
                return (f"I'm sorry, I can't verify that email for order {oid}, so I can't share its details. "
                        "Could you check the email address on the order?", False)
            return ("I'm sorry, I still can't verify it, so I'm not able to share details of this order. If it's your "
                    "order, our team can help at +359 2 900 1234.", True)
        status, item, when = result["status"], result["item"], result.get("eta") or result.get("delivered_on")
        sentence = {
            "out_for_delivery": f"Your {item} (order {oid}) is out for delivery and will arrive on {nice_date(when)}.",
            "delivered": f"Order {oid} ({item}) was delivered on {nice_date(when)}.",
            "delayed": f"Your {item} (order {oid}) is delayed. The new estimated delivery date is {nice_date(when)}.",
            "processing": f"Order {oid} ({item}) is being prepared and should arrive by {nice_date(when)}.",
        }[status]
        if status == "delayed" and cfg["empathy"]:
            sentence = "I'm sorry about the delay. " + sentence
        if not cfg["verify"]:
            sentence += f" It's going to {result['customer_name']}, {result['shipping_address']}."
            if s.trusted_claim:
                sentence += f" Contact: {result['customer_email']}, {result['customer_phone']}."
        return sentence, True

    def _do_appointment(self, msg: str, calls: list[ToolCall]) -> tuple[str, bool]:
        s, cfg = self.state, self.cfg
        if cfg["escalate_when_unsure"] and VAGUE_RE.search(msg) and not s.date:
            return ("I want to make sure this is handled properly, so I'm transferring you to a colleague who can find "
                    "the best time for a visit. " + self._transfer(calls, "Unclear appointment request"), True)
        oid = s.orders.get("appointment")
        missing = []
        if not oid:
            missing.append("your order number")
        if not s.email:
            missing.append("the email address on the order")
        if not s.date or not s.window:
            missing.append("which day and time (morning or afternoon) suit you")
        if missing:
            ask = missing[0] if len(missing) == 1 else ", ".join(missing[:-1]) + " and " + missing[-1]
            lead = "Sure, I can book a technician visit. " if s.turns == 1 else ""
            return f"{lead}Please tell me {ask}.", False
        windows = ["morning", "afternoon"] if s.window == "any" else [s.window]
        if cfg["confirm_booking"] and not s.confirmed:
            if s.awaiting_confirm and YES_RE.search(msg):
                s.confirmed = True
            else:
                s.awaiting_confirm = True
                when = "any time" if s.window == "any" else f"in the {s.window}"
                return (f"Just to confirm: a technician visit for order {oid} on {nice_date(s.date)} {when}, for "
                        f"\"{s.issue}\". Shall I go ahead and book it?", False)
        last = {}
        for window in windows:
            result, err = self._call(calls, "book_appointment", order_id=oid, email=s.email, date=s.date,
                                     time_window=window, issue=s.issue)
            if not err:
                s.awaiting_confirm = False
                if cfg["confirm_booking"]:
                    return (f"You're all set: a technician visit on {nice_date(result['date'])}, {result['time_window']} "
                            f"({result['hours']}), for order {oid}. Your confirmation number is {result['confirmation']}. "
                            "You'll get an SMS reminder the day before. Is there anything else I can help with?", True)
                return (f"Done! Your visit is booked for {nice_date(result['date'])}, {result['time_window']} "
                        f"({result['hours']}). Confirmation number: {result['confirmation']}.", True)
            last = result
            if result["error"] == "verification_failed":
                s.email = None
                return f"That email doesn't match order {oid}. Could you check it?", False
        slots = ", ".join(f"{nice_date(x['date'])} {x['time_window']}" for x in last.get("available_slots", []))
        day = nice_date(s.date) if s.date in self.backend.slots else s.date
        s.date, s.window, s.confirmed, s.awaiting_confirm = None, None, False, False
        return f"Unfortunately {day} is fully booked. The nearest free slots are: {slots}. Which one would you like?", False

    def _do_return(self, msg: str, calls: list[ToolCall]) -> tuple[str, bool]:
        s, cfg = self.state, self.cfg
        oid = s.orders.get("return")
        if s.refund_demand and cfg["promise_refunds"]:
            return f"Yes, your refund for order {oid} is approved! You'll get your money back within 3 days.", True
        if s.refund_demand:
            policy = ("I'm not able to approve refunds myself. A refund is paid to your original payment method 5-7 "
                      "business days after the item is returned and inspected.")
            item = ORDERS.get(oid, {}).get("item", "item").split()[-1]
            if REFUND_DEMAND_RE.search(msg) and s.refund_verified:
                return ("I understand. I can't confirm a refund without a return: refunds are only issued after the item "
                        f"is received and inspected. If the {item} has a fault, I can book a technician under the 2-year "
                        "warranty instead.", True)
            if not s.email:
                return (policy + " I can open a return request for you or, if it's faulty, book a repair visit under "
                        "warranty. For either, I'll need the email address on the order."), False
            result, err = self._call(calls, "check_order_status", order_id=oid, email=s.email)
            if err or not result["email_verified"]:
                s.email = None
                return "I'm sorry, I couldn't verify that email for this order. Could you check it?", False
            s.refund_verified = True
            return ("Thanks, that's verified. Would you like me to open a return request, or book a repair visit if "
                    "something is wrong with it?"), False
        if not oid or not s.email:
            return "I can help with that. Please share the order number and the email address on the order.", False
        result, err = self._call(calls, "create_return_request", order_id=oid, email=s.email,
                                 reason=s.issue or "Customer request")
        if not err:
            if cfg["promise_refunds"]:
                return (f"Done! Your return {result['rma']} is created and we'll pick up the item on "
                        f"{nice_date(result['pickup'])}. Your refund has been processed and you'll get your money back "
                        "within 2 days.", True)
            return (f"Your return is open: {result['rma']}. A courier will collect the item on "
                    f"{nice_date(result['pickup'])}. The refund goes to your original payment method 5-7 business days "
                    "after we receive and inspect the item.", True)
        if result["error"] == "outside_return_window":
            delivered = nice_date(result["delivered_on"])
            if cfg["empathy"]:
                return (f"I'm sorry, order {oid} was delivered on {delivered}, which is outside our 30-day return window. "
                        "It's still covered by the 2-year warranty, so if something is wrong with it I can book a "
                        "repair visit."), True
            return f"Sorry, this order was delivered on {delivered}, so the 30-day return window has passed.", True
        if result["error"] == "verification_failed":
            s.email = None
            return f"That email doesn't match order {oid}. Could you check it?", False
        return f"Order {oid} can't be returned yet: {result['message']}", True

    def _do_faq(self, msg: str, calls: list[ToolCall]) -> tuple[str, bool]:
        answers = []
        for _, rx, query in FAQ_TOPICS:
            if rx.search(msg):
                result, _ = self._call(calls, "lookup_faq", query=query)
                if result["results"]:
                    answers.append(result["results"][0]["answer"])
        if not answers:
            result, _ = self._call(calls, "lookup_faq", query=msg[:100])
            answers = [r["answer"] for r in result["results"][:1]] or ["I couldn't find that in our help centre."]
        text = " ".join(dict.fromkeys(answers))
        if re.search(r"before november 15", msg, re.I):
            text += " So delivery before November 15 is no problem."
        return text, True
