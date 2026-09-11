# -*- coding: utf-8 -*-
"""Generate 'Action Graph Layer -- apm_connectors/graph.py' reference
PDF: the Python constructs this file introduces that the FastAPI-layer
doc doesn't cover, a from-zero LangGraph tutorial, then a full deep
dive into this repo's action graph and the design patterns it uses --
written to double as interview-prep material. See
scripts/docs/README.md for the overall doc-generation convention.

Run standalone with `python scripts/docs/gen_action_graph_pdf.py`;
writes docs/action-graph-reference.pdf by default (override with the
OUT_OVERRIDE env var). Re-run after any change to
src/apm_connectors/graph.py.
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
OUT = Path(os.environ.get("OUT_OVERRIDE", REPO_ROOT / "docs" / "action-graph-reference.pdf"))

story = []

# ===========================================================================
story.append(Paragraph("Action Graph Layer — apm_connectors/graph.py", styles["title"]))
story.append(Paragraph(
    "The Python constructs this file adds on top of the FastAPI-layer doc, a from-zero LangGraph "
    "tutorial, then a complete deep dive into this repo's approval-gated action graph — written as a "
    "standalone reference, including for interview prep.",
    styles["subtitle"],
))
story.append(rule())

# ---------------------------------------------------------------------------
# PART 0 — PYTHON SYNTAX THIS FILE ADDS
# ---------------------------------------------------------------------------
story.append(h1("Part 0 — Python syntax this file adds"))
story.append(bl(
    "This continues the FastAPI-layer doc's Part 0 (imports, functions/defaults, type hints, "
    "classes, decorators, f-strings, comprehensions, exception chaining — read that first if any of "
    "those are still new). graph.py leans on five constructs that document didn't need to cover. "
    "Each gets a toy example, then the real line from this file."
))

story.append(h2("0.1 Closures — a function that remembers variables from where it was created"))
story.append(bl(
    "This is the single most important Python idea in this file — all three of the graph's nodes are "
    "built this way. A closure is an inner function, defined inside an outer function, that keeps "
    "access to the outer function's local variables even after the outer function has returned:"
))
story.append(code_block(
    "def make_multiplier(factor):        # outer function -- called once, with a specific factor\n"
    "    def multiply(x):                # inner function -- defined fresh each time make_multiplier runs\n"
    "        return x * factor           # `factor` isn't a global or a parameter of multiply --\n"
    "    return multiply                 # it's \"remembered\" from the enclosing call\n\n"
    "double = make_multiplier(2)\n"
    "triple = make_multiplier(3)\n"
    "double(5)   # 10\n"
    "triple(5)   # 15  -- double and triple each remember a *different* factor\n"
))
story.append(bl(
    "graph.py uses exactly this shape to build each node, so the node function has access to "
    "<font name='Courier'>state_store</font> (or <font name='Courier'>tools</font>) without those "
    "having to be threaded through LangGraph's own call signature, which only ever passes a node one "
    "argument — the current state:"
))
story.append(code_block(
    "# outer function -- called once, at graph-build time\n"
    "def _propose_node(state_store: StateStore):\n"
    "    # inner function -- this is the actual node LangGraph calls\n"
    "    def propose_node(state: GraphState) -> dict[str, Any]:\n"
    "        ...\n"
    "        state_store.add_pending_action(...)   # remembered from the closure\n"
    "        ...\n"
    "    return propose_node   # return the closure itself, not its result\n\n"
    "# _propose_node(state_store) runs once, right here, producing the closure\n"
    "# that LangGraph will then call repeatedly, once per invocation, later\n"
    "graph.add_node(\"propose\", _propose_node(state_store))\n"
))
story.append(bl(
    "Notice <font name='Courier'>_propose_node(state_store)</font> is <i>called</i> immediately, "
    "right there in <font name='Courier'>add_node(...)</font> — what gets registered as the node is "
    "its <i>return value</i>, the inner <font name='Courier'>propose_node</font> function, not "
    "<font name='Courier'>_propose_node</font> itself. This is the exact same "
    "\"take dependencies as parameters, return a built thing\" factory shape the FastAPI doc covered "
    "for <font name='Courier'>create_app()</font> — closures are just Python's version of that idea "
    "applied at function scope instead of class/app scope."
))

story.append(h2("0.2 TypedDict — a dict with a declared, checkable shape"))
story.append(code_block(
    "from typing import TypedDict\n\n"
    "class GraphState(TypedDict, total=False):\n"
    "    process_id: str\n"
    "    decision: bool | None\n"
))
story.append(bl(
    "A <font name='Courier'>TypedDict</font> looks like a class but behaves like a plain "
    "<font name='Courier'>dict</font> at runtime — <font name='Courier'>GraphState</font> instances "
    "are ordinary dicts (<font name='Courier'>{\"process_id\": \"...\", \"decision\": True}</font>), "
    "just with a type checker able to verify which keys are expected and what type each holds. "
    "<font name='Courier'>total=False</font> means no key is required — every field is optional, "
    "matching how this graph's nodes each only ever set a few keys at a time (§2.1). This is purely a "
    "static-typing aid; nothing about it changes how the dict behaves when the program actually runs."
))

story.append(h2("0.3 @dataclass — a quick way to define a plain data-holding class"))
story.append(code_block(
    "from dataclasses import dataclass\n\n"
    "@dataclass(frozen=True)\n"
    "class RunOutcome:\n"
    "    process_id: str\n"
    "    summary: str | None\n"
))
story.append(bl(
    "Without <font name='Courier'>@dataclass</font>, defining a simple \"bag of fields\" class means "
    "hand-writing <font name='Courier'>__init__</font> (to accept and store each field), "
    "<font name='Courier'>__repr__</font> (so printing the object is readable), and "
    "<font name='Courier'>__eq__</font> (so two instances with equal fields compare equal). "
    "<font name='Courier'>@dataclass</font> generates all of that automatically from the type-hinted "
    "attributes — the same field-declaration style as a Pydantic <font name='Courier'>BaseModel</font> "
    "(FastAPI doc §0.4), but from Python's standard library, with no validation performed. "
    "<font name='Courier'>frozen=True</font> makes instances immutable — attempting "
    "<font name='Courier'>outcome.process_id = \"x\"</font> after construction raises an error, which "
    "suits <font name='Courier'>RunOutcome</font> since it's a finished result handed back to a "
    "caller, never meant to be mutated afterward."
))

story.append(h2("0.4 getattr() — looking up a method by its name at runtime"))
story.append(code_block(
    "tool.send_email(...)                     # normal method call -- name is fixed in the source\n\n"
    "method_name = \"send_email\"\n"
    "method = getattr(tool, method_name)       # equivalent, but the name comes from a variable\n"
    "method(...)\n"
))
story.append(bl(
    "<font name='Courier'>getattr(obj, name)</font> fetches an attribute (here, a bound method) off "
    "an object using a string for its name, instead of writing the name directly in the source with a "
    "dot. execute_node uses exactly this to call whichever method a proposed action named, without "
    "needing an if/elif chain checking every possible method name: "
    "<font name='Courier'>method = getattr(tool, proposed[\"method\"])</font> — "
    "<font name='Courier'>proposed[\"method\"]</font> is a plain string like "
    "<font name='Courier'>\"send_email\"</font> that arrived from outside the process (ultimately, "
    "from an API request body)."
))

story.append(h2("0.5 ** in a function call — spreading a dict as keyword arguments"))
story.append(code_block(
    "def send(to, subject, body):\n"
    "    ...\n\n"
    "payload = {\"to\": \"a@b.com\", \"subject\": \"Hi\", \"body\": \"...\"}\n"
    "send(**payload)      # exactly the same as: send(to=\"a@b.com\", subject=\"Hi\", body=\"...\")\n"
))
story.append(bl(
    "<font name='Courier'>**some_dict</font> in a call \"unpacks\" the dict into individual keyword "
    "arguments — each key becomes a parameter name, each value the argument passed for it. This is "
    "how execute_node calls a method whose exact parameter list it doesn't know in advance: "
    "<font name='Courier'>method(process_id, dry_run=False, **proposed[\"payload\"])</font> passes "
    "<font name='Courier'>process_id</font> positionally, <font name='Courier'>dry_run=False</font> "
    "explicitly, and then spreads whatever fields the original request body had "
    "(<font name='Courier'>to</font>/<font name='Courier'>subject</font>/<font name='Courier'>body</font> "
    "for a Gmail send, <font name='Courier'>object_name</font>/<font name='Courier'>fields</font> for "
    "a Salesforce create) as the rest — one line handles every connector's write method, whatever its "
    "specific parameters are."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 1 — LANGGRAPH FROM ZERO
# ---------------------------------------------------------------------------
story.append(h1("Part 1 — LangGraph from zero"))

story.append(h2("1.1 What problem LangGraph solves"))
story.append(bl(
    "A plain Python function runs start to finish in one go — call it, get a result. That breaks "
    "down the moment a process needs to <i>pause partway through, wait for something external (here, "
    "a human decision), and resume later</i> — possibly in a completely different process, minutes or "
    "hours afterward, with no Python call stack still sitting around waiting. LangGraph is a library "
    "for building exactly that kind of multi-step process: a <b>graph</b> of named <b>nodes</b> (each "
    "a small function), connected by <b>edges</b> that say which node runs next, with built-in "
    "support for a node to pause the entire graph and resume it later from a durable snapshot instead "
    "of a live stack frame. This repo uses none of LangGraph's fancier features (branching, cycles, "
    "multi-agent orchestration) — just the pause/resume mechanism, applied to exactly one purpose: "
    "the human-approval gate."
))

story.append(h2("1.2 Building a graph: nodes, edges, entry point"))
story.append(code_block(
    "from langgraph.graph import END, StateGraph\n\n"
    "graph = StateGraph(GraphState)               # GraphState: the shape of data nodes share (§1.3)\n\n"
    "graph.add_node(\"propose\", propose_node)      # register a node under a name\n"
    "graph.add_node(\"approval\", approval_node)\n"
    "graph.add_node(\"execute\", execute_node)\n\n"
    "graph.set_entry_point(\"propose\")             # where a fresh run starts\n"
    "graph.add_edge(\"propose\", \"approval\")        # after propose, always go to approval\n"
    "graph.add_edge(\"approval\", \"execute\")\n"
    "graph.add_edge(\"execute\", END)               # END is a sentinel meaning \"the graph is finished\"\n\n"
    "compiled = graph.compile(checkpointer=checkpointer)   # turns the graph into something runnable\n"
))
story.append(bl(
    "This repo's graph is deliberately the simplest possible shape: three nodes, wired in a straight "
    "line, no branching or loops. <font name='Courier'>add_edge(a, b)</font> is an <i>unconditional</i> "
    "edge — always go from a to b (LangGraph also supports conditional edges that pick the next node "
    "based on state, not used here). <font name='Courier'>compile()</font> is what actually produces "
    "a runnable object — the un-compiled <font name='Courier'>graph</font> is just a description."
))

story.append(h2("1.3 State: the shared data every node reads and updates"))
story.append(bl(
    "Every node function takes the current state (a <font name='Courier'>GraphState</font>, §0.2) as "
    "its only argument, and returns a <i>partial</i> dict of updates — LangGraph merges whatever keys "
    "a node returns into the overall state before handing it to the next node:"
))
story.append(code_block(
    "def propose_node(state: GraphState) -> dict[str, Any]:\n"
    "    ...\n"
    "    return {\"pending_action_id\": action_record[\"id\"]}   # only this one key is being updated\n"
))
story.append(bl(
    "A node never sees or returns the <i>whole</i> state unless it needs to — it reads whichever keys "
    "it cares about off the <font name='Courier'>state</font> parameter, and returns only the keys "
    "it's changing. This is why <font name='Courier'>propose_node</font> can return just "
    "<font name='Courier'>{\"pending_action_id\": ...}</font> without also repeating "
    "<font name='Courier'>process_id</font> or <font name='Courier'>proposed_action</font> — those "
    "stay whatever they already were."
))

story.append(h2("1.4 The core mechanism: interrupt() and Command(resume=...)"))
story.append(bl(
    "This is LangGraph's actual value proposition for this codebase, and worth understanding "
    "precisely. Calling <font name='Courier'>interrupt(payload)</font> inside a node does two things "
    "at once: it <b>stops the graph's execution right there</b> — no later node runs — and it "
    "<b>surfaces <font name='Courier'>payload</font> back to whoever called the graph</b>, as a signal "
    "that it's now paused and waiting. The graph stays paused indefinitely — seconds, hours, across a "
    "server restart if the checkpointer is durable (§1.5) — until something calls the graph again with "
    "a <font name='Courier'>Command(resume=some_value)</font> instead of a normal input. When that "
    "happens, execution picks back up essentially at the "
    "<font name='Courier'>interrupt()</font> call, which now simply <i>returns</i> "
    "<font name='Courier'>some_value</font> instead of pausing again, and the node keeps running from "
    "there."
))
story.append(code_block(
    "def approval_node(state: GraphState) -> dict[str, Any]:\n"
    "    ...\n"
    "    decision = interrupt({\"type\": \"approval_request\", \"action_id\": action_id, ...})\n"
    "    # <-- graph pauses HERE on first run, resumes HERE (with `decision` set) on the second\n"
    "    approved = bool(decision.get(\"approved\")) if isinstance(decision, dict) else bool(decision)\n"
    "    ...\n"
))
story.append(bl(
    "Two separate calls into the compiled graph make this whole cycle work — "
    "<font name='Courier'>graph.invoke(initial_state, config=...)</font> the first time, then later "
    "<font name='Courier'>graph.invoke(Command(resume=decision), config=...)</font> — and both calls "
    "must pass the <i>same</i> <font name='Courier'>config</font> (specifically, the same "
    "<font name='Courier'>thread_id</font>, §1.5), which is how LangGraph knows which paused run to "
    "resume."
))

story.append(h2("1.5 Checkpointer and thread_id — where paused state actually lives"))
story.append(bl(
    "A <b>checkpointer</b> is where LangGraph saves a graph's state every time it pauses (or "
    "finishes) a step, keyed by a <b>thread_id</b> you supply — a paused run is identified purely by "
    "that id, not by any live Python object. This repo passes "
    "<font name='Courier'>process_id</font> as the thread_id:"
))
story.append(code_block(
    "def _config(process_id: str) -> dict[str, Any]:\n"
    "    return {\"configurable\": {\"thread_id\": process_id}}\n"
))
story.append(bl(
    "The checkpointer implementation determines whether a pause survives a process restart. "
    "<font name='Courier'>MemorySaver</font> keeps checkpoints in a plain Python dict in RAM — fast, "
    "zero setup, but gone the instant the process exits. <font name='Courier'>PostgresSaver</font> "
    "writes them to a real database instead, so a paused approval genuinely survives a redeploy. This "
    "repo's <font name='Courier'>api/dependencies.py</font> picks between the two based on whether "
    "<font name='Courier'>DATABASE_URL</font> is set — the graph code here never changes either way, "
    "since <font name='Courier'>build_action_graph</font> just takes whatever checkpointer it's "
    "handed (§2.4)."
))

story.append(h2("1.6 Replay: the detail that shapes how every node here is written"))
story.append(bl(
    "This is the single most important, least obvious LangGraph fact, and it's the reason "
    "<font name='Courier'>approval_node</font> is written the way it is. <b>On resume, LangGraph does "
    "not continue a suspended Python stack frame</b> — there isn't one to continue; the process that "
    "paused may not even be the process that resumes. Instead, it <b>re-runs the entire interrupted "
    "node function again, from its first line</b>, using the checkpointed state — and the only thing "
    "different this second time is that the specific "
    "<font name='Courier'>interrupt(...)</font> call that previously paused now immediately returns "
    "the resume value instead of pausing again."
))
story.append(quote_block(
    "\"On resume, LangGraph re-runs this node function from the top; interrupt() is the first (and "
    "only) side-effecting statement here so that replay is harmless — everything above it is a plain "
    "read of already-checkpointed state, and everything below it (recording the decision) executes "
    "exactly once, on the resume pass.\""
))
story.append(bl(
    "Concretely for <font name='Courier'>approval_node</font>: on the <i>first</i> run, execution "
    "reaches <font name='Courier'>interrupt(...)</font> and stops there — none of the lines after it "
    "have run yet. On <i>resume</i>, LangGraph runs the function again from line one — re-reading "
    "<font name='Courier'>proposed</font> and <font name='Courier'>action_id</font> off state (harmless, "
    "since those are just reads) — until it reaches the same "
    "<font name='Courier'>interrupt(...)</font> call again, which this time returns immediately with "
    "the decision instead of pausing, and <i>only then</i> do the lines below it — "
    "<font name='Courier'>resolve_pending_action(...)</font> and the return — actually execute, for "
    "the first and only time. If this node did anything with a side effect <i>before</i> the "
    "<font name='Courier'>interrupt()</font> call, replay would silently repeat that side effect on "
    "every resume — which is exactly why <font name='Courier'>propose_node</font>, the one thing that "
    "must fire exactly once, is a completely separate node that never calls "
    "<font name='Courier'>interrupt()</font> at all, and therefore is never replayed (§2.6)."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 2 — THIS REPO'S ACTION GRAPH, SECTION BY SECTION
# ---------------------------------------------------------------------------
story.append(h1("Part 2 — This repo's action graph, section by section"))
story.append(bl(
    "graph.py is one file, ~205 lines. Read it in this order — each section only makes sense once "
    "you've seen the one before it:"
))
layout_rows = [
    ["<b>Section</b>", "<b>What it defines</b>"],
    ["GraphState", "The TypedDict every node reads and partially updates (§1.3)."],
    ["RunOutcome", "The caller-facing result — either paused (pending_action set) or done (final_result set)."],
    ["_propose_node / _approval_node / _execute_node", "The three closure factories building the graph's actual nodes."],
    ["build_action_graph", "Wires the three nodes into a compiled, runnable graph."],
    ["start_action / resume_process", "The only two public entry points — everything else is private (leading underscore)."],
    ["_to_outcome", "Converts LangGraph's raw invoke() result into this repo's RunOutcome shape."],
]
story.append(simple_table(layout_rows, [2.3 * inch, USABLE_W - 2.3 * inch]))

story.append(h2("2.1 GraphState — six optional keys, total=False"))
story.append(code_block(
    "class GraphState(TypedDict, total=False):\n"
    "    process_id: str\n"
    "    category: str\n"
    "    proposed_action: dict[str, Any] | None\n"
    "    pending_action_id: str | None\n"
    "    decision: bool | None\n"
    "    result: dict[str, Any] | None\n"
))
story.append(bl(
    "Each field maps to exactly one moment in the pipeline: <font name='Courier'>proposed_action</font> "
    "is set once, at the very start, by the caller (§2.5); <font name='Courier'>pending_action_id</font> "
    "is set by propose_node; <font name='Courier'>decision</font> by approval_node; "
    "<font name='Courier'>result</font> by execute_node. No node ever needs to see the whole shape at "
    "once — each just reads the keys the node before it promised to set."
))

story.append(h2("2.2 RunOutcome — exactly one of two fields is ever set"))
story.append(code_block(
    "@dataclass(frozen=True)\n"
    "class RunOutcome:\n"
    '    """Either the graph is paused waiting for a human decision\n'
    "    (pending_action set), or it has finished (final_result set).\"\"\"\n"
    "    process_id: str\n"
    "    summary: str | None\n"
    "    pending_action: dict[str, Any] | None\n"
    "    final_result: dict[str, Any] | None\n"
))
story.append(bl(
    "This is the exact same \"discriminated by convention\" shape the FastAPI doc's "
    "<font name='Courier'>RunOutcomeResponse</font> mirrors one-to-one (that Pydantic model is "
    "literally built by copying these same four fields off a <font name='Courier'>RunOutcome</font> "
    "in <font name='Courier'>_responses.to_response</font>) — a caller checks which field is "
    "non-<font name='Courier'>None</font> rather than the code raising a different exception or "
    "return type per case."
))

story.append(h2("2.3 The three node factories"))
story.append(bl("propose_node — runs to completion, never interrupts, never replayed:"))
story.append(code_block(
    "def _propose_node(state_store: StateStore):\n"
    "    def propose_node(state: GraphState) -> dict[str, Any]:\n"
    "        process_id = state[\"process_id\"]\n"
    "        proposed = state.get(\"proposed_action\")\n"
    "        if not proposed:\n"
    "            return {\"pending_action_id\": None}\n"
    "        action_record = state_store.add_pending_action(\n"
    "            process_id=process_id, tool=proposed[\"tool\"], description=proposed[\"description\"],\n"
    "            payload=proposed, category=state.get(\"category\", \"other\"),\n"
    "        )\n"
    "        return {\"pending_action_id\": action_record[\"id\"]}\n"
    "    return propose_node\n"
))
story.append(bl("approval_node — the gate itself (walked through fully in §1.6):"))
story.append(code_block(
    "def _approval_node(state_store: StateStore):\n"
    "    def approval_node(state: GraphState) -> dict[str, Any]:\n"
    "        proposed = state.get(\"proposed_action\")\n"
    "        action_id = state.get(\"pending_action_id\")\n"
    "        if not proposed or not action_id:\n"
    "            return {\"decision\": None}\n"
    "        decision = interrupt({\"type\": \"approval_request\", \"action_id\": action_id,\n"
    "            \"tool\": proposed[\"tool\"], \"method\": proposed[\"method\"],\n"
    "            \"description\": proposed[\"description\"], \"payload\": proposed[\"payload\"],\n"
    "            \"category\": state.get(\"category\", \"other\")})\n"
    "        approved = bool(decision.get(\"approved\")) if isinstance(decision, dict) else bool(decision)\n"
    "        state_store.resolve_pending_action(action_id, approved=approved)\n"
    "        return {\"decision\": approved}\n"
    "    return approval_node\n"
))
story.append(bl("execute_node — the only place a write ever actually fires:"))
story.append(code_block(
    "def _execute_node(tools: dict[str, BaseTool], state_store: StateStore):\n"
    "    def execute_node(state: GraphState) -> dict[str, Any]:\n"
    "        process_id = state[\"process_id\"]\n"
    "        proposed = state.get(\"proposed_action\")\n"
    "        decision = state.get(\"decision\")\n"
    "        if not proposed or not decision:\n"
    "            outcome = {\"executed\": False, \"reason\": \"no_action_proposed\" if not proposed else \"rejected\"}\n"
    "            state_store.set_status(process_id, stage=\"done\", result=outcome)\n"
    "            return {\"result\": outcome}\n"
    "        tool = tools[proposed[\"tool\"]]\n"
    "        method = getattr(tool, proposed[\"method\"])\n"
    "        action_result = method(process_id, dry_run=False, **proposed[\"payload\"])\n"
    "        outcome = {\"executed\": action_result.executed, \"description\": action_result.description,\n"
    "                   \"details\": action_result.details}\n"
    "        state_store.set_status(process_id, stage=\"done\", result=outcome)\n"
    "        return {\"result\": outcome}\n"
    "    return execute_node\n"
))
story.append(bl(
    "<font name='Courier'>dry_run=False</font> is hardcoded, always, unconditionally, right here — "
    "there is no code path anywhere in this file that can call a tool's write method with "
    "<font name='Courier'>dry_run=True</font> or omit the flag. Combined with the fact that this is "
    "the <i>only</i> place in the entire codebase any write/action method is ever invoked, that one "
    "hardcoded keyword argument is effectively the codebase's whole safety guarantee, expressed as a "
    "single line."
))

story.append(h2("2.4 build_action_graph — wiring it together"))
story.append(code_block(
    "def build_action_graph(tools: dict[str, BaseTool], state_store: StateStore, checkpointer: Any):\n"
    "    graph = StateGraph(GraphState)\n"
    "    graph.add_node(\"propose\", _propose_node(state_store))\n"
    "    graph.add_node(\"approval\", _approval_node(state_store))\n"
    "    graph.add_node(\"execute\", _execute_node(tools, state_store))\n"
    "    graph.set_entry_point(\"propose\")\n"
    "    graph.add_edge(\"propose\", \"approval\")\n"
    "    graph.add_edge(\"approval\", \"execute\")\n"
    "    graph.add_edge(\"execute\", END)\n"
    "    return graph.compile(checkpointer=checkpointer)\n"
))
story.append(bl(
    "<font name='Courier'>checkpointer</font> is a required parameter here, not defaulted to "
    "<font name='Courier'>MemorySaver()</font> inside this function — the module docstring is "
    "explicit that this is deliberate, \"so callers decide the persistence story.\" This is the same "
    "Strategy-pattern shape the FastAPI doc's <font name='Courier'>dependencies.py</font> section "
    "covered: the decision of <i>which</i> checkpointer lives entirely at the call site "
    "(<font name='Courier'>api/dependencies.py</font>'s <font name='Courier'>get_action_graph()</font>), "
    "never inside <font name='Courier'>graph.py</font> itself."
))

story.append(h2("2.5 start_action / resume_process — the only two public entry points"))
story.append(code_block(
    "def start_action(graph, process_id, tool, method, description, payload, category=\"manual\") -> RunOutcome:\n"
    "    proposed_action = {\"tool\": tool, \"method\": method, \"description\": description, \"payload\": payload}\n"
    "    initial_state: GraphState = {\"process_id\": process_id, \"proposed_action\": proposed_action, \"category\": category}\n"
    "    result = graph.invoke(initial_state, config=_config(process_id))\n"
    "    return _to_outcome(process_id, result)\n\n"
    "def resume_process(graph, process_id, approved: bool) -> RunOutcome:\n"
    "    result = graph.invoke(Command(resume={\"approved\": approved}), config=_config(process_id))\n"
    "    return _to_outcome(process_id, result)\n"
))
story.append(bl(
    "Every other function in this file has a leading underscore "
    "(<font name='Courier'>_propose_node</font>, <font name='Courier'>_config</font>, "
    "<font name='Courier'>_to_outcome</font>) — Python's convention for \"internal, not part of this "
    "module's public interface,\" enforced by nothing but the reader's own discipline (there's no "
    "access-control keyword like <font name='Courier'>private</font> in Python). "
    "<font name='Courier'>start_action</font> and <font name='Courier'>resume_process</font> are the "
    "two callers actually use — <font name='Courier'>tools_routes.py</font>'s "
    "<font name='Courier'>_propose</font> helper calls the former, its "
    "<font name='Courier'>decide_action</font> route calls the latter (see the FastAPI-layer doc §2.4)."
))

story.append(h2("2.6 _to_outcome — reading LangGraph's own sentinel key"))
story.append(code_block(
    "def _to_outcome(process_id: str, result: dict[str, Any]) -> RunOutcome:\n"
    "    if \"__interrupt__\" in result:\n"
    "        return RunOutcome(process_id=process_id, summary=result.get(\"summary\"),\n"
    "            pending_action=result[\"__interrupt__\"][0].value, final_result=None)\n"
    "    return RunOutcome(process_id=process_id, summary=result.get(\"summary\"),\n"
    "        pending_action=None, final_result=result.get(\"result\"))\n"
))
story.append(bl(
    "<font name='Courier'>graph.invoke(...)</font> returns a plain dict either way — LangGraph "
    "communicates \"this run just paused\" by including a special "
    "<font name='Courier'>\"__interrupt__\"</font> key in that dict (a list of interrupt objects; "
    "<font name='Courier'>[0].value</font> is the payload the paused "
    "<font name='Courier'>interrupt(...)</font> call was given). This function is the one place in "
    "the codebase that reads that LangGraph-specific detail and translates it into this repo's own "
    "vocabulary (<font name='Courier'>RunOutcome.pending_action</font>) — everything above graph.py, "
    "all the way out through the API layer, only ever deals with <font name='Courier'>RunOutcome</font>, "
    "never LangGraph's own result shape directly."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 3 — DESIGN PATTERNS, NAMED
# ---------------------------------------------------------------------------
story.append(h1("Part 3 — Design patterns used here, named explicitly"))
patterns = [
    ["<b>Pattern</b>", "<b>Where</b>", "<b>What problem it actually solves here</b>"],
    ["Closure-based Factory",
     "_propose_node/_approval_node/_execute_node",
     "Gives each node access to state_store/tools without LangGraph's call signature needing to pass them — the closure remembers them from build time (§0.1)."],
    ["State Machine / Pipeline",
     "The 3-node graph: propose -> approval -> execute",
     "Models a multi-step process with an explicit, inspectable shape instead of one long function — each stage has a name and a single responsibility."],
    ["Command Pattern",
     "Command(resume={\"approved\": approved})",
     "Wraps \"resume this paused run with this value\" as a single object passed to invoke(), instead of a special-cased resume() method with its own signature."],
    ["Memento / Checkpoint",
     "The checkpointer (MemorySaver / PostgresSaver)",
     "Captures a paused run's full state externally, so it can be restored later by an unrelated process invocation, not just resumed within the same call stack."],
    ["Strategy (pluggable implementation)",
     "build_action_graph's checkpointer parameter",
     "The graph never picks its own persistence — the caller decides in-memory vs. durable, matching the FastAPI doc's DATABASE_URL toggle."],
    ["Idempotency by construction",
     "propose_node never calls interrupt(); approval_node's side effect sits after it",
     "Guarantees a pending action is recorded exactly once and a decision resolved exactly once, despite LangGraph replaying interrupted nodes on every resume (§1.6)."],
    ["Facade",
     "start_action / resume_process",
     "Two public functions hide the graph-invocation details (Command objects, thread_id config, the __interrupt__ sentinel) from every caller."],
]
story.append(simple_table(patterns, [1.5 * inch, 1.7 * inch, USABLE_W - 3.2 * inch]))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 4 — INTERVIEW-PREP CHEAT SHEET
# ---------------------------------------------------------------------------
story.append(h1("Part 4 — Interview-prep Q&A"))
story.append(bl(
    "Practice answering by pointing at the actual code, not reciting the definition."
))

qa = [
    ("Q: What does interrupt() actually do, mechanically?",
     "A: It stops the graph's execution at that point and surfaces its payload to the caller as a "
     "signal that the run is paused. The graph doesn't keep a live, waiting Python stack frame -- the "
     "paused state is written to the checkpointer, and a completely separate later call "
     "(graph.invoke(Command(resume=...))) is what continues it (§1.4)."),
    ("Q: What happens to the code before interrupt() when a node resumes -- does it run again?",
     "A: Yes -- LangGraph replays the entire node function from its first line on resume; only the "
     "specific interrupt() call that previously paused now returns immediately instead of pausing "
     "again. Every node in this file is written assuming that replay, which is why "
     "interrupt() is deliberately the first side-effecting statement in approval_node (§1.6)."),
    ("Q: Why is there a separate propose_node instead of recording the pending action inside "
     "approval_node, right before its interrupt() call?",
     "A: Because approval_node gets replayed on resume and propose_node doesn't. If recording the "
     "pending action happened just before interrupt() inside the same node, it would re-run (and "
     "double-record) every time that node replays. Splitting it into its own node that never calls "
     "interrupt() guarantees it fires exactly once (§2.6, the module's own docstring makes this "
     "explicit)."),
    ("Q: What is a checkpointer, and what's the practical difference between MemorySaver and "
     "PostgresSaver?",
     "A: It's where LangGraph persists a paused (or finished) run's state, keyed by thread_id. "
     "MemorySaver keeps it in an in-process dict -- fast, zero setup, gone on restart. PostgresSaver "
     "writes it to a real database, so a paused approval survives a redeploy or a crash -- this "
     "repo's live-verified scenario for exactly that (§1.5)."),
    ("Q: What is thread_id here, and where does it come from?",
     "A: It's the key LangGraph uses to know which paused run a given invoke() call is resuming. "
     "This repo passes process_id as the thread_id (_config()) -- the same id used for the API's "
     "action_id and for audit-trail grouping, so one id ties the whole flow together end to end."),
    ("Q: getattr(tool, proposed['method']) -- why not just call the method directly, e.g. "
     "tool.send_email(...)?",
     "A: execute_node is generic across every connector and every write method -- it doesn't know at "
     "write-time whether it's handling a Gmail send, a Salesforce create, or a Jira update. getattr "
     "looks the method up by the name that arrived in the request instead of the code needing an "
     "if/elif branch per method (§0.4)."),
    ("Q: Where, precisely, is dry_run=False set, and why does that matter?",
     "A: One hardcoded keyword argument inside execute_node's call: "
     "method(process_id, dry_run=False, **proposed['payload']). Combined with execute_node being the "
     "only place in the entire codebase any write/action method is ever called, that single line is "
     "effectively the whole enforcement mechanism, backed up independently by each connector's own "
     "require_dry_run_guard (see the FastAPI-layer doc)."),
    ("Q: Walk through what happens end to end when a write is proposed and later approved.",
     "A: start_action builds the initial GraphState and calls graph.invoke -- propose_node records "
     "the pending action and returns pending_action_id; approval_node calls interrupt(), pausing the "
     "graph; _to_outcome sees __interrupt__ in the result and returns a RunOutcome with "
     "pending_action set. Later, resume_process calls graph.invoke(Command(resume={'approved': "
     "True})) with the same thread_id; approval_node replays, interrupt() now returns immediately, "
     "resolve_pending_action logs the approval, execute_node runs the real write, and _to_outcome "
     "returns a RunOutcome with final_result set instead."),
]
for q, a in qa:
    story.append(caption(q))
    story.append(bl(a))

story.append(Spacer(1, 10))
story.append(h1("Vocabulary cheat-sheet"))
vocab = [
    ["Closure", "An inner function that keeps access to variables from the outer function it was defined in, even after the outer call returns (§0.1)."],
    ["TypedDict", "A dict with a statically-declared, checkable key/value shape -- behaves as a plain dict at runtime (§0.2)."],
    ["@dataclass", "Standard-library decorator that auto-generates __init__/__repr__/__eq__ from type-hinted attributes (§0.3)."],
    ["getattr(obj, name)", "Looks up an attribute (e.g. a method) on an object using a string name instead of a fixed dot-name (§0.4)."],
    ["**dict unpacking", "Spreads a dict's items as individual keyword arguments in a function call (§0.5)."],
    ["Node / Edge", "A node is one step (a function); an edge says which node runs next after it."],
    ["StateGraph / compile()", "StateGraph describes the graph; compile() turns that description into a runnable object."],
    ["interrupt()", "Pauses graph execution at that exact point and surfaces its argument to the caller (§1.4)."],
    ["Command(resume=...)", "What you pass to invoke() to resume a paused run with a value for the interrupt() call to return."],
    ["Checkpointer / thread_id", "Where a paused run's state is stored, keyed by an id you supply -- MemorySaver (in-process) or PostgresSaver (durable) here."],
    ["Replay", "LangGraph re-running an interrupted node from its top on resume -- the reason node code must be written to tolerate repeated execution before its interrupt() call (§1.6)."],
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
    "That's the whole layer: one file, three nodes, a straight-line graph, and one interrupt() call "
    "that is the entire reason this package can promise a write never executes without a separate, "
    "later, human-approved decision -- durable across process restarts whenever a real checkpointer "
    "backs it."
))

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(
    str(OUT), pagesize=letter,
    leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=0.95 * inch,
    title="Action Graph Layer -- apm_connectors/graph.py",
)
DOC_FOOTER = footer("APM Connectors & Enterprise Systems — Action Graph Layer Reference")
doc.build(story, onFirstPage=DOC_FOOTER, onLaterPages=DOC_FOOTER)
print("wrote", OUT)
