# -*- coding: utf-8 -*-
"""Generate 'Connector Layer -- apm_connectors/tools/' reference PDF:
the Python constructs this layer introduces beyond the FastAPI/Action
Graph docs, a from-zero tutorial on the design ideas behind a common
connector interface, then a full deep dive into this repo's connector
layer (base.py, _retry.py, gmail_tool.py as the worked example) and
the design patterns it uses -- written to double as interview-prep
material. See scripts/docs/README.md for the overall doc-generation
convention.

Run standalone with `python scripts/docs/gen_connector_layer_pdf.py`;
writes docs/connector-layer-reference.pdf by default (override with
the OUT_OVERRIDE env var). Re-run after any change to
src/apm_connectors/tools/{base,_retry,gmail_tool}.py.
"""

import os
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from _pdf_template import (
    CODE_BORDER, GRAY_FILL, MARGIN, USABLE_W,
    bl, caption, code_block, esc, footer, h1, h2, quote_block, rule, simple_table, styles,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("OUT_OVERRIDE", REPO_ROOT / "docs" / "connector-layer-reference.pdf"))

story = []

# ===========================================================================
story.append(Paragraph("Connector Layer — apm_connectors/tools/", styles["title"]))
story.append(Paragraph(
    "The Python constructs this layer adds on top of the FastAPI/Action Graph docs, a from-zero "
    "tutorial on why a common connector interface exists, then a complete deep dive into this repo's "
    "connectors and the design patterns they use — written as a standalone reference, including for "
    "interview prep.",
    styles["subtitle"],
))
story.append(rule())

# ---------------------------------------------------------------------------
# PART 0 — PYTHON SYNTAX THIS LAYER ADDS
# ---------------------------------------------------------------------------
story.append(h1("Part 0 — Python syntax this layer adds"))
story.append(bl(
    "Continues the FastAPI-layer doc's Part 0 and the Action Graph doc's Part 0 — read those first "
    "if imports, type hints, classes, decorators, closures, TypedDict, or @dataclass are still new. "
    "The connector layer adds six more constructs."
))

story.append(h2("0.1 Abstract base classes — a contract subclasses must fulfill"))
story.append(code_block(
    "from abc import ABC, abstractmethod\n\n"
    "class Shape(ABC):                  # ABC = cannot be instantiated directly\n"
    "    @abstractmethod\n"
    "    def area(self) -> float:       # no body -- every subclass MUST implement this\n"
    "        ...\n\n"
    "class Circle(Shape):\n"
    "    def __init__(self, r): self.r = r\n"
    "    def area(self) -> float:\n"
    "        return 3.14159 * self.r ** 2\n\n"
    "Shape()      # TypeError -- can't instantiate an ABC directly\n"
    "Circle(2).area()   # 12.566 -- fine, area() was implemented\n"
))
story.append(bl(
    "A class inheriting from <font name='Courier'>ABC</font> can declare methods as "
    "<font name='Courier'>@abstractmethod</font> — no body, just a signature (and usually a "
    "docstring). Python then refuses to let you create an instance of any subclass that hasn't "
    "actually implemented every abstract method — you get a <font name='Courier'>TypeError</font> at "
    "the moment of instantiation, not a confusing failure later when the missing method finally gets "
    "called. This repo's <font name='Courier'>BaseTool(ABC)</font> uses exactly this to guarantee "
    "every connector implements <font name='Courier'>health_check</font> (§2.3) — forgetting to "
    "would be caught immediately, the first time anyone tries to construct that connector."
))

story.append(h2("0.2 Protocol — an interface defined by shape, not by inheritance"))
story.append(code_block(
    "from typing import Protocol\n\n"
    "class Honks(Protocol):\n"
    "    def honk(self) -> str: ...\n\n"
    "class Car:                    # note: does NOT inherit from Honks at all\n"
    "    def honk(self) -> str:\n"
    "        return \"beep\"\n\n"
    "def make_it_honk(x: Honks) -> str:   # accepts ANYTHING with a honk() method\n"
    "    return x.honk()\n\n"
    "make_it_honk(Car())    # \"beep\" -- Car satisfies Honks just by having the right method\n"
))
story.append(bl(
    "This is <i>structural</i> typing (\"if it walks like a duck and honks like a duck...\") as "
    "opposed to the <i>nominal</i> typing <font name='Courier'>ABC</font> uses (§0.1), where a class "
    "must explicitly say <font name='Courier'>class Car(Honks):</font> to count. A "
    "<font name='Courier'>Protocol</font> class is never instantiated and never inherited from — it's "
    "purely a shape description a type checker compares other classes against. The "
    "<font name='Courier'>...</font> (Python's <font name='Courier'>Ellipsis</font> literal) is a "
    "real, valid expression often used exactly this way — as a placeholder body meaning \"no "
    "implementation here, this is just a signature.\" gmail_tool.py's "
    "<font name='Courier'>GmailClient(Protocol)</font> (§2.4) is why both the real Gmail API wrapper "
    "and a test's fake client work as a <font name='Courier'>GmailTool</font>'s client argument "
    "without either one inheriting from anything — they just both happen to have matching methods."
))

story.append(h2("0.3 Enum — a fixed, named set of values"))
story.append(code_block(
    "from enum import Enum\n\n"
    "class Capability(str, Enum):\n"
    "    READ = \"read\"\n"
    "    WRITE = \"write\"\n"
    "    ACTION = \"action\"\n\n"
    "Capability.READ            # Capability.READ\n"
    "Capability.READ == \"read\"  # True -- because it also inherits from str\n"
))
story.append(bl(
    "An <font name='Courier'>Enum</font> restricts a value to one of a fixed, named set — "
    "<font name='Courier'>Capability.READ</font> is a real, distinct object, not just the string "
    "<font name='Courier'>\"read\"</font>, which catches typos a plain string constant wouldn't "
    "(<font name='Courier'>Capability.RAED</font> is an <font name='Courier'>AttributeError</font> at "
    "the point of the typo; a misspelled string just silently fails to match later). Inheriting from "
    "<font name='Courier'>str</font> <i>as well as</i> <font name='Courier'>Enum</font> — "
    "<font name='Courier'>class Capability(str, Enum):</font> — is a common combination meaning "
    "\"restricted to these values, but still comparable to and serializable as plain strings,\" useful "
    "anywhere the value needs to cross a boundary (JSON, a log line) that only understands plain "
    "strings."
))

story.append(h2("0.4 A decorator that takes its own arguments"))
story.append(bl(
    "The FastAPI doc's §0.5 covered a plain <font name='Courier'>@decorator</font>. "
    "<font name='Courier'>@with_retry()</font> — note the parentheses — is one level more: a "
    "function that, when <i>called</i>, <i>returns</i> a decorator. Three layers, each with one job:"
))
story.append(code_block(
    "def with_retry(attempts=3):     # 1. called with config, e.g. with_retry(attempts=5)\n"
    "    def decorator(func):        # 2. receives the function being decorated\n"
    "        def wrapper(*args, **kwargs):   # 3. runs on each actual call\n"
    "            for i in range(attempts):\n"
    "                try:\n"
    "                    return func(*args, **kwargs)\n"
    "                except OSError:\n"
    "                    if i == attempts - 1:\n"
    "                        raise\n"
    "        return wrapper\n"
    "    return decorator\n\n"
    "# with_retry(attempts=5) runs immediately, returns `decorator`, which\n"
    "# then wraps call_api exactly like a plain @decorator would\n"
    "@with_retry(attempts=5)\n"
    "def call_api():\n"
    "    ...\n"
))
story.append(bl(
    "<font name='Courier'>*args, **kwargs</font> in <font name='Courier'>wrapper</font>'s own "
    "signature is the receiving side of the unpacking the Action Graph doc covered (§0.5 there) — it "
    "means \"accept any positional and keyword arguments at all,\" so this one "
    "<font name='Courier'>wrapper</font> can retry a call to <i>any</i> function, whatever "
    "arguments it happens to take. This is exactly this repo's "
    "<font name='Courier'>with_retry()</font> (§2.5), just simplified — the real one also uses "
    "<font name='Courier'>functools.wraps(func)</font> right above "
    "<font name='Courier'>wrapper</font>'s definition, which copies "
    "<font name='Courier'>func</font>'s original name/docstring onto "
    "<font name='Courier'>wrapper</font> — without it, every decorated method would misleadingly "
    "show up as a function literally named <font name='Courier'>wrapper</font> in stack traces and "
    "debuggers."
))

story.append(h2("0.5 @staticmethod — a method that doesn't need self"))
story.append(code_block(
    "class Converter:\n"
    "    @staticmethod\n"
    "    def celsius_to_fahrenheit(c: float) -> float:\n"
    "        return c * 9 / 5 + 32     # doesn't touch `self` at all\n\n"
    "Converter.celsius_to_fahrenheit(100)   # 212.0 -- no instance required\n"
))
story.append(bl(
    "A regular method's first parameter is always <font name='Courier'>self</font> (FastAPI doc "
    "§0.4). <font name='Courier'>@staticmethod</font> removes that — the method doesn't receive an "
    "instance at all, because it doesn't need one; it's grouped inside the class purely for "
    "organization (it's conceptually \"about\" that class) rather than because it operates on a "
    "particular instance's data. gmail_tool.py's "
    "<font name='Courier'>_to_summary</font> (§2.4) is exactly this shape — it transforms a raw dict "
    "into an <font name='Courier'>EmailSummary</font> without ever touching <font name='Courier'>self</font>."
))

story.append(h2("0.6 A few smaller pieces you'll see in this layer"))
bullets_06 = [
    ("<font name='Courier'>frozenset({...})</font>",
     "An immutable set — like a frozen tuple is to a list. capabilities: frozenset[Capability] means "
     "the set of what a connector can do is fixed at construction and can't be mutated afterward."),
    ("<font name='Courier'>f\"{subject!r}\"</font>",
     "The !r inside an f-string (FastAPI doc §0.6) formats the value with repr() instead of str() -- "
     "for a string, that means it prints with quotes around it, making it obvious in a log line where "
     "the value starts and ends."),
    ("A dict comprehension over nested data",
     "{h[\"name\"].lower(): h[\"value\"] for h in raw.get(\"payload\", {}).get(\"headers\", [])} -- "
     "same [expr for item in iterable] shape as a list comprehension (Action Graph doc §0.7 in the "
     "FastAPI doc's numbering), just building a dict instead of a list."),
    ("<font name='Courier'>TypeVar</font> / <font name='Courier'>Callable[..., T]</font>",
     "T = TypeVar(\"T\") declares a placeholder type used to say \"this decorator preserves whatever "
     "type the wrapped function returns\" -- Callable[..., T] means \"a callable taking any arguments, "
     "returning T.\""),
]
for term, meaning in bullets_06:
    story.append(bl(f"<b>{term}</b> — {meaning}"))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 1 — CONNECTOR-INTERFACE DESIGN, FROM ZERO
# ---------------------------------------------------------------------------
story.append(h1("Part 1 — Connector-interface design, from zero"))

story.append(h2("1.1 The problem: five external systems, one caller"))
story.append(bl(
    "Gmail, Google Calendar, Excel, Salesforce, and Jira each have their own SDK, their own "
    "authentication scheme, their own data shapes. Without a shared interface, the Action Graph's "
    "execute_node (see that doc, §2.3) would need to know, in detail, how to call each one — an "
    "if/elif chain checking which connector it's dealing with, one branch per system, growing every "
    "time a new connector is added. A <b>common interface</b> — a promise that every connector "
    "exposes the same shaped methods (§1.2) — lets calling code stay completely generic: "
    "execute_node's <font name='Courier'>getattr(tool, proposed[\"method\"])</font> (Action Graph doc "
    "§0.4) works identically whether <font name='Courier'>tool</font> is a "
    "<font name='Courier'>GmailTool</font> or a <font name='Courier'>JiraTool</font>, because both "
    "promise the same shape."
))

story.append(h2("1.2 Interfaces as contracts, and two ways to express one in Python"))
story.append(bl(
    "An <b>interface</b>, in the general software-design sense, is a promise: \"anything claiming to "
    "be an X will have these methods, with these signatures.\" Calling code writes against the "
    "interface, never caring which concrete implementation it was actually handed. This repo "
    "expresses that promise <i>two different ways</i>, deliberately, for two different relationships:"
))
story.append(simple_table(
    [
        ["<b></b>", "<b>ABC (nominal)</b>", "<b>Protocol (structural)</b>"],
        ["How a class opts in", "Explicit: class GmailTool(BaseTool):", "Implicit: just have matching methods"],
        ["Used for", "BaseTool -- the connector's own public shape", "GmailClient -- the HTTP client a connector wraps"],
        ["Why this one here", "Connectors are a small, closed set this repo owns and controls the shape of", "A test fake and the real API client shouldn't have to share a base class just to both qualify"],
    ],
    [1.6 * inch, (USABLE_W - 1.6 * inch) / 2, (USABLE_W - 1.6 * inch) / 2],
))
story.append(bl(
    "This contrast is worth sitting with (it reappears explicitly in §3): ABC is the right tool when "
    "you own every implementation and want Python to actively enforce completeness at construction "
    "time (§0.1). Protocol is the right tool when you don't want to force unrelated things (a real "
    "API client, a test fake) into a shared inheritance hierarchy just to prove they're interchangeable."
))

story.append(h2("1.3 dry_run, as a general idea"))
story.append(bl(
    "A <b>dry run</b> is a call that goes through all the same logic — validation, logging, building "
    "the request — as a real call, but stops short of actually sending/creating/writing anything, and "
    "reports back what <i>would</i> have happened. It's a common pattern anywhere an action is "
    "expensive, dangerous, or irreversible enough that you want a way to preview it safely. This "
    "repo's twist: <font name='Courier'>dry_run</font> isn't an optional debugging flag here — it's "
    "the literal boolean that separates \"describe this write\" from \"actually perform this write,\" "
    "and the entire human-approval mechanism (Action Graph doc) exists specifically to control when "
    "that flag is allowed to be <font name='Courier'>False</font>."
))

story.append(h2("1.4 Idempotency, retries, and why writes can't be retried blindly"))
story.append(bl(
    "An operation is <b>idempotent</b> if doing it multiple times has the same effect as doing it "
    "once — <font name='Courier'>GET</font>-ing the same resource five times leaves the world in the "
    "same state as fetching it once. A network call can fail <i>after</i> the server did the work but "
    "<i>before</i> the response reaches the caller — from the caller's point of view, indistinguishable "
    "from the request never having arrived at all. Blindly retrying an idempotent read after that kind "
    "of failure is free and safe: worst case, you fetch the same data twice. Blindly retrying a "
    "<i>non</i>-idempotent write — sending an email, creating a record — risks doing it <i>twice</i>: "
    "once the server actually processed before the connection dropped, once more on the retry. This "
    "exact reasoning is why this repo's retry decorator (§2.5) is deliberately applied only to read "
    "methods, and the module docstring says so explicitly."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 2 — THIS REPO'S CONNECTOR LAYER, SECTION BY SECTION
# ---------------------------------------------------------------------------
story.append(h1("Part 2 — This repo's connector layer, section by section"))
layout_rows = [
    ["<b>File</b>", "<b>Role</b>"],
    ["tools/base.py", "Capability, ActionResult, BaseTool -- the shared shape every connector implements (88 lines)."],
    ["tools/_retry.py", "with_retry -- the read-only retry-with-backoff decorator factory (65 lines)."],
    ["tools/gmail_tool.py", "One concrete connector, used throughout this doc as the worked example (226 lines); the other four (calendar, excel_file, salesforce, jira) follow the same shape."],
]
story.append(simple_table(layout_rows, [1.6 * inch, USABLE_W - 1.6 * inch]))

story.append(h2("2.1 Capability — what a connector is allowed to be asked to do"))
story.append(code_block(
    "class Capability(str, Enum):\n"
    "    READ = \"read\"\n"
    "    WRITE = \"write\"\n"
    "    ACTION = \"action\"\n\n"
    "# in GmailTool:\n"
    "capabilities = frozenset({Capability.READ, Capability.ACTION})\n"
))
story.append(bl(
    "Every connector declares its capabilities as a class attribute — Gmail can "
    "<font name='Courier'>READ</font> (search/read messages) and take an <font name='Courier'>ACTION</font> "
    "(send), but has no bare <font name='Courier'>WRITE</font> capability (that's used by connectors "
    "like Excel/Salesforce that overwrite existing data rather than triggering a one-shot action). "
    "<font name='Courier'>can(capability)</font> (§2.3) is the one place this gets checked — mostly "
    "useful for a UI or caller wanting to know upfront what's possible without trying and catching a "
    "failure."
))

story.append(h2("2.2 ActionResult — the uniform write/action return shape"))
story.append(code_block(
    "@dataclass(frozen=True)\n"
    "class ActionResult:\n"
    '    """What a write/action call returns, whether it actually ran or\n'
    "    was a dry run -- callers treat both the same shape, checking\n"
    '    `executed` to tell them apart."""\n'
    "    executed: bool\n"
    "    description: str\n"
    "    details: dict[str, Any]\n"
))
story.append(bl(
    "Every write/action method across every connector — <font name='Courier'>send_email</font>, "
    "<font name='Courier'>create_event</font>, <font name='Courier'>write_range</font>, "
    "<font name='Courier'>create_record</font> — returns exactly this shape. The Action Graph's "
    "execute_node (that doc, §2.3) reads <font name='Courier'>action_result.executed</font> generically, "
    "with zero knowledge of which specific connector produced it. This is the connector-layer "
    "equivalent of <font name='Courier'>RunOutcome</font>'s \"discriminated by convention\" design "
    "from the Action Graph doc — one uniform result shape instead of one bespoke type per connector."
))

story.append(h2("2.3 BaseTool — the shared contract"))
story.append(code_block(
    "class BaseTool(ABC):\n"
    "    name: str\n"
    "    capabilities: frozenset[Capability]\n\n"
    "    def __init__(self, state: StateStore) -> None:\n"
    "        self._state = state\n\n"
    "    def can(self, capability: Capability) -> bool:\n"
    "        return capability in self.capabilities\n\n"
    "    def _log(self, process_id, event_type, summary, details=None) -> None:\n"
    "        self._state.log_event(process_id=process_id, tool=self.name,\n"
    "            event_type=event_type, summary=summary, details=details or {})\n\n"
    "    @abstractmethod\n"
    "    def health_check(self) -> bool:\n"
    '        """... Must never raise -- return False on failure ..."""\n\n'
    "    def require_dry_run_guard(self, dry_run: bool, process_id: str, summary: str) -> None:\n"
    "        event_type = \"action_executed\" if not dry_run else \"action_proposed\"\n"
    "        self._log(process_id, event_type, summary, {\"dry_run\": dry_run})\n"
))
story.append(bl(
    "Four things every subclass inherits for free: a constructor that stashes the shared "
    "<font name='Courier'>StateStore</font>; <font name='Courier'>_log</font>, the single audit-trail "
    "write path every public method is expected to funnel through; "
    "<font name='Courier'>require_dry_run_guard</font>, called at the top of every write/action method "
    "(§1.3); and the <font name='Courier'>@abstractmethod health_check</font> every connector must "
    "implement (§0.1) — deliberately required to <i>never raise</i>, so a UI can poll every "
    "connector's status in a loop without one bad credential crashing the whole check."
))

story.append(h2("2.4 GmailTool — the worked example"))
story.append(bl("The Protocol-typed client (§0.2) — this is the entire surface GmailTool needs:"))
story.append(code_block(
    "class GmailClient(Protocol):\n"
    "    def list_message_ids(self, query: str, max_results: int) -> list[str]: ...\n"
    "    def get_message(self, message_id: str) -> dict[str, Any]: ...\n"
    "    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]: ...\n"
))
story.append(bl("A read method — runs immediately, logs a plain \"read\" event:"))
story.append(code_block(
    "def search_emails(self, process_id: str, query: str, max_results: int = 10) -> list[EmailSummary]:\n"
    "    message_ids = self._client.list_message_ids(query=query, max_results=max_results)\n"
    "    summaries = [self._to_summary(self._client.get_message(mid)) for mid in message_ids]\n"
    "    self._log(process_id, \"read\", f\"Searched Gmail for '{query}', found {len(summaries)} message(s)\",\n"
    "        {\"query\": query, \"count\": len(summaries)})\n"
    "    return summaries\n"
))
story.append(bl("The write method — three independent layers of defense, in order:"))
story.append(code_block(
    "def send_email(self, process_id, to, subject, body, dry_run: bool = True) -> ActionResult:\n"
    "    # 1. refuse fake domains outright\n"
    "    if _is_reserved_placeholder_address(to):\n"
    "        summary = f\"Refused to send to {to}: reserved for documentation/examples\"\n"
    "        self._log(process_id, \"action_failed\", summary, {\"to\": to, \"subject\": subject})\n"
    "        return ActionResult(executed=False, description=summary, details={...})\n\n"
    "    summary = f\"Send email to {to}: {subject!r}\"\n"
    "    # 2. log regardless of outcome\n"
    "    self.require_dry_run_guard(dry_run, process_id, summary)\n\n"
    "    # 3. dry_run is the actual gate\n"
    "    if dry_run:\n"
    "        return ActionResult(executed=False, description=summary, details={...})\n\n"
    "    sent = self._client.send_message(to=to, subject=subject, body=body)\n"
    "    return ActionResult(executed=True, description=summary, details={...})\n"
))
story.append(bl(
    "<font name='Courier'>dry_run: bool = True</font> is a fail-safe default — call "
    "<font name='Courier'>send_email(...)</font> without explicitly passing "
    "<font name='Courier'>dry_run=False</font>, and nothing gets sent, no matter what. The one place "
    "that default gets overridden is the Action Graph's execute_node, hardcoding "
    "<font name='Courier'>dry_run=False</font> (that doc, §2.3) — and only after "
    "<font name='Courier'>interrupt()</font> has returned an approval."
))

story.append(h2("2.5 The placeholder-domain guard — a concrete defense-in-depth example"))
story.append(quote_block(
    "\"RFC 2606 reserves the .test/.example/.invalid/.localhost TLDs ... A safety net against the "
    "reasoner fabricating a plausible-looking placeholder recipient (observed in practice: it "
    "proposed 'customer@example.com' when no real customer address was present anywhere in the "
    "fetched data) -- this check runs regardless of what the reasoner outputs or whether a human "
    "approved it, since a human reviewing a payload has no reason to recognize 'example.com' as fake "
    "rather than a real domain they don't happen to know.\""
))
story.append(bl(
    "Worth reading closely because it's a real bug this guard was written in direct response to, not "
    "a hypothetical: an LLM-based reasoning layer, lacking a real recipient address in its input data, "
    "confidently invented a plausible-looking one. A human approver reviewing that payload has no way "
    "to distinguish a fabricated address from a real one they simply don't recognize — so the check "
    "can't live at the human-approval step; it has to be a hard refusal inside the connector itself, "
    "before dry_run is even considered. This is <i>defense in depth</i> as a concrete, motivated "
    "design choice: three independent layers (this domain check, "
    "<font name='Courier'>require_dry_run_guard</font>'s audit logging, and the Action Graph's "
    "<font name='Courier'>interrupt()</font> gate one level up) each catch a different failure mode, "
    "none of them redundant with the others."
))

story.append(h2("2.6 _retry.py — read-only, on purpose"))
story.append(code_block(
    "TRANSIENT_EXCEPTIONS = (OSError,)   # covers ConnectionError, TimeoutError, etc.\n\n"
    "def with_retry(attempts: int = 3, base_delay_seconds: float = 0.5):\n"
    "    def decorator(func):\n"
    "        @functools.wraps(func)\n"
    "        def wrapper(*args, **kwargs):\n"
    "            for attempt in range(1, attempts + 1):\n"
    "                try:\n"
    "                    return func(*args, **kwargs)\n"
    "                except TRANSIENT_EXCEPTIONS as exc:\n"
    "                    last_error = exc\n"
    "                    if attempt < attempts:\n"
    "                        time.sleep(base_delay_seconds * attempt)   # linear backoff\n"
    "            raise last_error\n"
    "        return wrapper\n"
    "    return decorator\n\n"
    "# usage, in GoogleApiGmailClient:\n"
    "@with_retry()\n"
    "def list_message_ids(self, query: str, max_results: int) -> list[str]:\n"
    "    ...\n\n"
    "# NOT decorated -- see the module docstring:\n"
    "def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:\n"
    "    ...\n"
))
story.append(bl(
    "<font name='Courier'>TRANSIENT_EXCEPTIONS = (OSError,)</font> is deliberately narrow — it "
    "catches connection-level failures (the request never got a real response at all), but not HTTP "
    "error status codes like 429 or a 5xx, which arrive as a different, client-library-specific "
    "exception type carrying response details a caller may actually want to inspect rather than "
    "silently retry past. <font name='Courier'>list_message_ids</font> and "
    "<font name='Courier'>get_message</font> — both reads — get the decorator; "
    "<font name='Courier'>send_message</font> — a write — deliberately does not, straight out of the "
    "idempotency reasoning in §1.4."
))

story.append(h2("2.7 Lazy imports and factory functions"))
story.append(code_block(
    "class GoogleApiGmailClient:\n"
    "    def __init__(self, credentials: Any) -> None:\n"
    "        from googleapiclient.discovery import build   # imported HERE, not at module top\n"
    "        self._service = build(\"gmail\", \"v1\", credentials=credentials)\n\n"
    "def build_gmail_tool(state: StateStore, settings: Settings) -> GmailTool:\n"
    "    from apm_connectors.tools.google_auth import load_credentials\n"
    "    credentials = load_credentials(settings, scopes=[...])\n"
    "    return GmailTool(state, GoogleApiGmailClient(credentials))\n"
))
story.append(bl(
    "Same local-import pattern the FastAPI doc's §0.10 covered for the Postgres driver, here applied "
    "to <font name='Courier'>googleapiclient</font>: importing "
    "<font name='Courier'>gmail_tool</font> — including for unit tests, which construct "
    "<font name='Courier'>GmailTool</font> directly with a fake client (§0.2) — never requires "
    "<font name='Courier'>googleapiclient</font> to be installed at all; only actually building a "
    "<font name='Courier'>GoogleApiGmailClient</font> does. <font name='Courier'>build_gmail_tool</font> "
    "is the same factory-function shape as <font name='Courier'>create_app()</font> and "
    "<font name='Courier'>build_action_graph(...)</font> from the other two docs — take real "
    "dependencies (settings, a state store), run whatever setup is needed (the OAuth flow), return a "
    "fully-built object — used by the running app, deliberately bypassed by tests in favor of "
    "constructing <font name='Courier'>GmailTool</font> directly."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 3 — DESIGN PATTERNS, NAMED
# ---------------------------------------------------------------------------
story.append(h1("Part 3 — Design patterns used here, named explicitly"))
patterns = [
    ["<b>Pattern</b>", "<b>Where</b>", "<b>What problem it actually solves here</b>"],
    ["Template Method (via ABC)",
     "BaseTool -- name, capabilities, health_check abstract; _log, require_dry_run_guard concrete",
     "Every connector gets shared audit-logging/dry-run machinery for free, and Python enforces that health_check is never forgotten."],
    ["Structural typing (Protocol)",
     "GmailClient(Protocol)",
     "Lets the real API client and a test fake both satisfy the interface without sharing a base class -- contrast with BaseTool's nominal ABC, §1.2."],
    ["Value Object",
     "ActionResult, EmailSummary -- both @dataclass(frozen=True)",
     "Immutable, equality-comparable result objects -- once built, can't be silently mutated by something downstream."],
    ["Decorator (Retry)",
     "with_retry() wrapping read-only client methods",
     "Transient network failures get retried transparently, without touching the calling code at all -- and is trivially omittable for writes."],
    ["Defense in depth",
     "Placeholder-domain refusal + require_dry_run_guard + the Action Graph's interrupt()",
     "Three independent layers, each catching a different failure mode -- a fabricated recipient, a missed audit log, and an unapproved write, respectively."],
    ["Fail-safe default",
     "dry_run: bool = True; health_check must never raise",
     "Calling a write method with no explicit dry_run argument is always safe; a broken connector reports unhealthy instead of crashing a status check."],
    ["Factory Function",
     "build_gmail_tool(state, settings)",
     "Same shape as create_app()/build_action_graph() -- take dependencies, run setup, return a built object; tests bypass it entirely."],
]
story.append(simple_table(patterns, [1.5 * inch, 1.7 * inch, USABLE_W - 3.2 * inch]))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 4 — INTERVIEW-PREP CHEAT SHEET
# ---------------------------------------------------------------------------
story.append(h1("Part 4 — Interview-prep Q&A"))
story.append(bl("Practice answering by pointing at the actual code, not reciting the definition."))

qa = [
    ("Q: This codebase uses both ABC and Protocol for 'interfaces'. What's the actual difference, "
     "and how did they choose which to use where?",
     "A: ABC (BaseTool) is nominal typing -- a class must explicitly inherit to count, and Python "
     "enforces every abstract method is implemented before the class can even be instantiated. "
     "Protocol (GmailClient) is structural typing -- anything with matching methods qualifies, no "
     "inheritance needed. They used ABC for BaseTool because they own every connector and want "
     "completeness enforced; Protocol for the HTTP client because a real client and a test fake "
     "shouldn't need a shared base class just to both qualify (§1.2)."),
    ("Q: Where exactly does dry_run live, and how many places actually check it?",
     "A: It's a parameter on every write/action method, defaulting to True. require_dry_run_guard "
     "logs regardless of its value; the if dry_run: branch inside the method itself is what actually "
     "decides whether the real client call happens. The Action Graph's execute_node is the only place "
     "in the whole codebase that ever passes dry_run=False, and only after an approved interrupt() "
     "(§1.3, and see the Action Graph doc)."),
    ("Q: Why is the retry decorator only applied to read methods?",
     "A: Because reads are idempotent -- retrying a fetch after a dropped connection just fetches the "
     "same data again, safely. A write isn't idempotent: if the connection drops after the server "
     "already processed it but before the success response arrives, a blind retry risks sending or "
     "creating something twice. Better for a transient write failure to surface as a failure a human "
     "looks at than to silently retry into a duplicate (§1.4, §2.6)."),
    ("Q: Walk through what happens if a reasoning layer proposes sending an email to "
     "'customer@example.com'.",
     "A: send_email's first check, _is_reserved_placeholder_address, catches it immediately -- "
     "example.com is an RFC 2606 reserved documentation domain. It logs an action_failed event and "
     "returns ActionResult(executed=False, ...) with reason 'reserved_placeholder_domain' -- before "
     "dry_run is even considered, and regardless of whether a human already approved it, because a "
     "human reviewing the payload has no way to recognize a fabricated address as fake (§2.5)."),
    ("Q: What does frozen=True buy you on ActionResult, beyond what a plain dataclass gives?",
     "A: Immutability -- once constructed, none of its fields can be reassigned; attempting to "
     "changes it raises an error. Appropriate here because ActionResult is a finished result handed "
     "back up the call chain, never meant to be mutated by something downstream (same reasoning as "
     "RunOutcome in the Action Graph doc)."),
    ("Q: Why does GoogleApiGmailClient import googleapiclient inside __init__ instead of at the top "
     "of the file?",
     "A: So importing gmail_tool.py at all -- including for unit tests, which use a fake client -- "
     "never requires googleapiclient to be installed. Only code paths that actually construct a real "
     "GoogleApiGmailClient need that dependency present (§2.7, same reasoning as the FastAPI doc's "
     "Postgres-driver example)."),
    ("Q: If you were adding a sixth connector, what would you actually have to implement?",
     "A: Inherit from BaseTool, set name and capabilities, implement health_check (required by "
     "@abstractmethod), route every public method through self._log, and call "
     "require_dry_run_guard at the top of every write/action method before checking dry_run. If the "
     "connector wraps a real HTTP client, define a minimal Protocol for exactly the methods needed, "
     "the same way GmailClient does, rather than depending on the third-party SDK's full client type."),
]
for q, a in qa:
    story.append(caption(q))
    story.append(bl(a))

story.append(Spacer(1, 10))
story.append(h1("Vocabulary cheat-sheet"))
vocab = [
    ["ABC / @abstractmethod", "A base class Python won't let you instantiate until every @abstractmethod is implemented by a subclass (§0.1)."],
    ["Protocol", "A structural-typing interface -- any class with matching methods qualifies, no inheritance required (§0.2)."],
    ["Enum", "A fixed, named set of values, safer against typos than plain string constants (§0.3)."],
    ["Decorator factory", "A function that, when called with arguments, returns a decorator -- e.g. with_retry(attempts=5) (§0.4)."],
    ["@staticmethod", "A method that doesn't receive self -- grouped in the class for organization, not because it needs an instance (§0.5)."],
    ["Idempotent", "An operation where doing it multiple times has the same effect as doing it once -- reads generally are, writes generally aren't (§1.4)."],
    ["dry_run", "A call that runs all the same logic as a real one but stops short of the actual side effect, reporting what would have happened (§1.3)."],
    ["Defense in depth", "Multiple independent checks, each catching a different failure mode, none redundant with the others (§2.5)."],
    ["Adapter", "A class translating one interface (a third-party SDK) into another (this repo's own minimal Protocol) -- GoogleApiGmailClient is the example."],
]
vocab_rows = [["<b>Term</b>", "<b>Meaning here</b>"]] + vocab
vt_rows = [[Paragraph(f"<font name='Courier'><b>{esc(r[0])}</b></font>" if i > 0 else r[0], styles["tablecell"]),
            Paragraph(esc(r[1]) if i > 0 else r[1], styles["tablecell"])]
           for i, r in enumerate(vocab_rows)]
vt = Table(vt_rows, colWidths=[1.9 * inch, USABLE_W - 1.9 * inch])
vt.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_FILL),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LINEBELOW", (0, 0), (-1, -1), 0.4, CODE_BORDER),
    ("BOX", (0, 0), (-1, -1), 0.8, CODE_BORDER),
]))
story.append(vt)

story.append(Spacer(1, 10))
story.append(bl(
    "That's the whole layer: one shared contract (BaseTool), one narrow retry helper, and five "
    "connectors that all look identical from the outside — each one's actual write path defended by "
    "the same three independent layers, whether it's sending an email or updating a Salesforce record."
))

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(
    str(OUT), pagesize=letter,
    leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=0.95 * inch,
    title="Connector Layer -- apm_connectors/tools/",
)
DOC_FOOTER = footer("APM Connectors & Enterprise Systems — Connector Layer Reference")
doc.build(story, onFirstPage=DOC_FOOTER, onLaterPages=DOC_FOOTER)
print("wrote", OUT)
