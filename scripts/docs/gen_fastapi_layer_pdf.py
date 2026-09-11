# -*- coding: utf-8 -*-
"""Generate 'FastAPI Layer -- apm_connectors/api/' reference PDF: a
from-zero Python syntax primer, a from-zero FastAPI tutorial, then a
full deep dive into this repo's API layer and the design patterns it
uses -- written to double as interview-prep material. See
scripts/docs/README.md for the overall doc-generation convention.

Run standalone with `python scripts/docs/gen_fastapi_layer_pdf.py`;
writes docs/fastapi-layer-reference.pdf by default (override with the
OUT_OVERRIDE env var). Re-run after any change to
src/apm_connectors/api/{app,dependencies,schemas,tools_routes,_responses}.py.
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
OUT = Path(os.environ.get("OUT_OVERRIDE", REPO_ROOT / "docs" / "fastapi-layer-reference.pdf"))

story = []

# ===========================================================================
story.append(Paragraph("FastAPI Layer — apm_connectors/api/", styles["title"]))
story.append(Paragraph(
    "A from-zero Python syntax primer, a from-zero FastAPI tutorial, then a complete deep dive into "
    "this repo's API layer and the design patterns it uses — written as a standalone reference, "
    "including for interview prep.",
    styles["subtitle"],
))
story.append(rule())

# ---------------------------------------------------------------------------
# PART 0 — PYTHON SYNTAX PRIMER
# ---------------------------------------------------------------------------
story.append(h1("Part 0 — Python syntax you'll see throughout this document"))
story.append(bl(
    "If you're new to Python, read this part first — every construct here reappears constantly in "
    "Parts 1-4. Each one is explained with a plain toy example, then the actual line from this "
    "codebase that uses it."
))

story.append(h2("0.1 Imports — how one file uses code from another"))
story.append(code_block(
    "from fastapi import FastAPI          # \"from the fastapi package, bring in the name FastAPI\"\n"
    "import os                            # \"bring in the whole os module; refer to it as os.something\"\n"
    "from apm_connectors.graph import resume_process, start_action\n"
))
story.append(bl(
    "A <i>module</i> is just one <font name='Courier'>.py</font> file; a <i>package</i> is a folder "
    "of modules (like <font name='Courier'>apm_connectors.api</font>, the folder this whole document "
    "is about). <font name='Courier'>from X import Y</font> pulls one specific name — a function, a "
    "class, a variable — out of module/package X so you can use it directly by that name, instead of "
    "writing <font name='Courier'>X.Y</font> every time."
))

story.append(h2("0.2 Functions — parameters, default values, return type hints"))
story.append(code_block(
    "def greet(name, excited=False):        # `excited` has a default -- calling greet(\"Sam\") is fine\n"
    "    if excited:\n"
    "        return name + \"!\"\n"
    "    return name\n\n"
    "greet(\"Sam\")             # \"Sam\"   -- excited defaults to False\n"
    "greet(\"Sam\", True)       # \"Sam!\"\n"
    "greet(name=\"Sam\")        # same as the first call, but naming the argument explicitly\n"
))
story.append(bl(
    "Any parameter with <font name='Courier'>= something</font> after it becomes optional — the "
    "caller may omit it, and the default is used. Calling with <font name='Courier'>name=\"Sam\"</font> "
    "instead of just <font name='Courier'>\"Sam\"</font> is a <i>keyword argument</i> — same effect, "
    "more explicit at the call site. This repo's route functions do this constantly: "
    "<font name='Courier'>def list_items(limit: int = 10):</font> means <font name='Courier'>limit</font> "
    "is optional and defaults to 10."
))

story.append(h2("0.3 Type hints — annotations that tools read, but plain Python doesn't enforce"))
story.append(bl(
    "Writing <font name='Courier'>x: int</font> instead of just <font name='Courier'>x</font> "
    "<i>documents</i> that x should be an integer — bare Python itself does not stop you from passing "
    "a string anyway. What makes type hints load-bearing in this codebase specifically is that "
    "<b>Pydantic and FastAPI read them at runtime</b> and actively validate against them (§1.4) — the "
    "hint stops being just a comment and becomes an enforced rule, but only because a library chose "
    "to enforce it, not because Python itself does."
))
story.append(code_block(
    "age: int                    # a plain int\n"
    "name: str | None = None     # either a str, or None -- and optional, since it has a default\n"
    "tags: list[str]             # a list containing only strings\n"
    "tools: dict[str, BaseTool]  # a dict whose keys are str and whose values are BaseTool instances\n"
))
story.append(bl(
    "<font name='Courier'>X | None</font> (Python 3.10+) is the modern way to write \"this is either "
    "type X, or the value None\" — you may also see the older, equivalent "
    "<font name='Courier'>Optional[X]</font> from the <font name='Courier'>typing</font> module in "
    "other codebases; they mean the same thing. <font name='Courier'>list[str]</font> and "
    "<font name='Courier'>dict[str, X]</font> are <i>generic</i> type hints — they say not just \"a "
    "list\" but \"a list of specifically these\". You'll see this exact shape everywhere in "
    "schemas.py: <font name='Courier'>process_id: str | None = None</font> — optional, defaults to "
    "None if the caller doesn't send one."
))

story.append(h2("0.4 Classes — self, inheritance, and attribute declarations"))
story.append(code_block(
    "class Animal:\n"
    "    def __init__(self, name):     # runs automatically when you write Animal(\"Rex\")\n"
    "        self.name = name          # `self` = \"this particular instance\"\n"
    "    def speak(self):\n"
    "        return self.name + \" makes a sound\"\n\n"
    "class Dog(Animal):                # Dog inherits everything Animal has, then can add/override\n"
    "    def speak(self):\n"
    "        return self.name + \" barks\"\n\n"
    "Dog(\"Rex\").speak()   # \"Rex barks\"\n"
))
story.append(bl(
    "<font name='Courier'>self</font> is just a name (by convention, always the first parameter of a "
    "method) referring to the specific instance the method was called on — Python passes it in "
    "automatically whenever you write <font name='Courier'>instance.method()</font>; you never pass "
    "it yourself. <font name='Courier'>class Dog(Animal):</font> means Dog <i>inherits</i> from "
    "Animal — it starts with everything Animal has, and can add new behavior or override existing "
    "methods. Pydantic's <font name='Courier'>BaseModel</font> (§1.4) uses this exact mechanism: "
    "every request schema in this repo is <font name='Courier'>class SomeRequest(BaseModel):</font>, "
    "inheriting all of Pydantic's validation behavior for free."
))
story.append(bl(
    "One more thing worth flagging because it looks unusual the first time: inside a "
    "<font name='Courier'>BaseModel</font> subclass, a line like <font name='Courier'>name: "
    "str</font> with no <font name='Courier'>self.</font> and no function body is <i>not</i> a "
    "regular Python statement — it's Pydantic-specific class syntax declaring \"this model has a "
    "required field called name, of type str\". You won't see this pattern outside of Pydantic "
    "models (and the similar standard-library <font name='Courier'>@dataclass</font>)."
))

story.append(h2("0.5 Decorators — what @something above a function actually does"))
story.append(bl(
    "A decorator is a function that takes your function as input and gives back a (possibly "
    "different) function. Writing <font name='Courier'>@decorator</font> directly above a "
    "<font name='Courier'>def</font> is shorthand for calling the decorator on it afterward:"
))
story.append(code_block(
    "@app.get(\"/health\")\n"
    "def health():\n"
    "    ...\n\n"
    "# is (roughly) shorthand for:\n\n"
    "def health():\n"
    "    ...\n"
    "health = app.get(\"/health\")(health)     # app.get(...) returns a decorator, which wraps health\n"
))
story.append(bl(
    "This is how a library \"registers\" or \"wraps\" your function without you writing an extra line "
    "of registration code yourself. <font name='Courier'>@app.get(\"/health\")</font> registers the "
    "function as a route handler (§1.2); <font name='Courier'>@lru_cache</font> (§2.3) wraps a "
    "function so repeated calls with the same arguments return a cached result instead of "
    "recomputing. Same mechanism both times — only what the decorator <i>does</i> to your function "
    "differs."
))

story.append(h2("0.6 f-strings — building a string with values inside it"))
story.append(code_block(
    'name = "Sam"\n'
    'greeting = f"Hello, {name}!"     # "Hello, Sam!" -- whatever\'s inside {} is evaluated and inserted\n'
))
story.append(bl(
    "The <font name='Courier'>f</font> right before the opening quote is what activates this — "
    "without it, <font name='Courier'>{name}</font> would just be four literal characters, not a "
    "substitution. This repo builds human-readable audit descriptions this way constantly: "
    "<font name='Courier'>f\"Create Salesforce {body.object_name} record\"</font>."
))

story.append(h2("0.7 Dicts, lists, and comprehensions"))
story.append(code_block(
    '{"to": to, "subject": subject}          # a dict literal -- key: value pairs\n'
    "[r.__dict__ for r in results]           # a list comprehension\n\n"
    "# the comprehension above is shorthand for:\n"
    "output = []\n"
    "for r in results:\n"
    "    output.append(r.__dict__)\n"
))
story.append(bl(
    "A <i>list comprehension</i> — <font name='Courier'>[expression for item in iterable]</font> — "
    "builds a new list in one line instead of a multi-line for-loop with "
    "<font name='Courier'>.append(...)</font>; every read route in this repo ends with exactly this "
    "shape to convert a list of connector objects into plain JSON-able dicts. "
    "<font name='Courier'>r.__dict__</font> is worth knowing specifically: every ordinary Python "
    "object keeps its attributes internally as a dict named <font name='Courier'>__dict__</font> — "
    "accessing it directly is a quick way to turn an object into a plain "
    "<font name='Courier'>dict</font> FastAPI can serialize to JSON."
))

story.append(h2("0.8 Exception handling — try/except, and raise ... from ..."))
story.append(code_block(
    "try:\n"
    "    risky_call()\n"
    "except ValueError as exc:      # only catches ValueError -- others propagate up\n"
    "    handle(exc)\n\n"
    "try:\n"
    "    results = tool.query_records(process_id, soql=body.soql)\n"
    "except Exception as exc:\n"
    "    raise upstream_error(exc) from exc    # wraps exc, keeping it attached\n"
))
story.append(bl(
    "<font name='Courier'>except Exception as exc:</font> catches the error and binds it to the "
    "name <font name='Courier'>exc</font> so you can inspect or reuse it. "
    "<font name='Courier'>raise NewError(...) from exc</font> is Python's <i>exception chaining</i>: "
    "it raises a new, more specific exception (in this repo, always an "
    "<font name='Courier'>HTTPException</font> — §1.7) while keeping the original exception attached "
    "as context, so a server-side traceback shows both \"here's the clean error the caller saw\" and "
    "\"here's what actually broke underneath it\", instead of losing the original cause."
))

story.append(h2("0.9 async def and await — a quick pointer"))
story.append(bl(
    "You'll see <font name='Courier'>async def</font> instead of plain <font name='Courier'>def</font> "
    "on some functions, and <font name='Courier'>await</font> before some calls inside them. This is "
    "covered properly in §1.6 once you've seen how FastAPI runs — the short version for now: "
    "<font name='Courier'>async def</font> marks a function as one that can pause and let other work "
    "happen while it waits on something slow (a network call), and "
    "<font name='Courier'>await</font> marks exactly where it pauses."
))

story.append(h2("0.10 A local import inside a function body"))
story.append(code_block(
    "def get_state_store():\n"
    "    if settings.database_url:\n"
    "        from apm_connectors.state.postgres_store import PostgresStateStore   # imported HERE, not at the top of the file\n"
    "        return PostgresStateStore(...)\n"
    "    return StateStore()\n"
))
story.append(bl(
    "Imports usually live at the very top of a file, but here's one deliberately placed inside the "
    "function instead. This delays loading the Postgres driver until this exact line actually runs — "
    "which only happens if <font name='Courier'>DATABASE_URL</font> is set. Without this, importing "
    "<font name='Courier'>apm_connectors.api.dependencies</font> at all would require the Postgres "
    "driver to be installed, even for a deployment that never sets "
    "<font name='Courier'>DATABASE_URL</font> and only wants the zero-infrastructure file-backed "
    "default (§2.3). You'll see this same local-import pattern again for the same reason."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 1 — FASTAPI FROM ZERO
# ---------------------------------------------------------------------------
story.append(h1("Part 1 — FastAPI from zero"))

story.append(h2("1.1 What FastAPI actually is"))
story.append(bl(
    "FastAPI is a Python web framework for building HTTP APIs. Three facts explain almost everything "
    "else about it:"
))
story.append(bl(
    "<b>It's built on Starlette</b> (the actual ASGI toolkit that handles routing, requests, "
    "responses, middleware) <b>and Pydantic</b> (the data-validation library). FastAPI itself is "
    "mostly glue: it reads your Python type hints and wires them into Starlette's routing and "
    "Pydantic's validation automatically. <b>It's ASGI, not WSGI</b> — ASGI (Asynchronous Server "
    "Gateway Interface) is the newer standard that supports async request handling, WebSockets, and "
    "long-lived connections; WSGI (what Flask/Django classically used) is synchronous, one thread "
    "per request. <b>It generates its own API documentation</b> from your code — every route's "
    "parameters, types, and response shape are introspected at startup and served live at "
    "<font name='Courier'>/docs</font> (Swagger UI) and <font name='Courier'>/redoc</font>, with zero "
    "extra work from you."
))

story.append(h2("1.2 Path operations — the core building block"))
story.append(bl(
    "A <b>path operation</b> is a Python function decorated to handle one HTTP method on one URL "
    "path:"
))
story.append(code_block(
    "from fastapi import FastAPI\n\n"
    "app = FastAPI()\n\n"
    "@app.get(\"/health\")\n"
    "def health() -> dict:\n"
    '    return {"status": "ok"}\n'
))
story.append(bl(
    "<font name='Courier'>@app.get</font> registers this function against <font name='Courier'>GET "
    "/health</font>; there's a matching <font name='Courier'>@app.post</font>, "
    "<font name='Courier'>@app.put</font>, <font name='Courier'>@app.delete</font>, etc. Whatever you "
    "<font name='Courier'>return</font> — a dict, a list, a Pydantic model — FastAPI serializes to "
    "JSON automatically. This decorator pattern is the entire routing mechanism: there's no separate "
    "URL-config file to maintain, the route lives right next to the function that handles it."
))

story.append(h2("1.3 Getting data in: path params, query params, request body"))
story.append(bl("Three ways a caller sends FastAPI data in, distinguished purely by where you put the parameter:"))
story.append(code_block(
    "@app.get(\"/items/{item_id}\")           # path parameter -- part of the URL itself\n"
    "def get_item(item_id: int):              # GET /items/42  ->  item_id = 42\n"
    "    ...\n\n"
    "@app.get(\"/items\")                      # query parameter -- a plain, non-body function arg\n"
    "def list_items(limit: int = 10):          # GET /items?limit=5  ->  limit = 5\n"
    "    ...\n\n"
    "class Item(BaseModel):                    # request body -- a Pydantic model as the arg type\n"
    "    name: str\n"
    "    price: float\n\n"
    "@app.post(\"/items\")                     # POST /items, JSON body {\"name\":..., \"price\":...}\n"
    "def create_item(item: Item):\n"
    "    ...\n"
))
story.append(bl(
    "FastAPI decides which of these a parameter is purely from <i>how it's declared</i>: named in the "
    "URL path template → path parameter; a plain scalar type not in the path → query parameter; a "
    "Pydantic <font name='Courier'>BaseModel</font> subclass → request body, parsed from JSON. No "
    "separate parsing code anywhere — this repo's routes take the request-body form exclusively, "
    "covered in Part 2."
))

story.append(h2("1.4 Pydantic models: type hints that validate themselves"))
story.append(bl(
    "A <font name='Courier'>BaseModel</font> subclass isn't just a type-hint convenience — FastAPI "
    "uses it to validate every incoming request body before your function body ever runs:"
))
story.append(code_block(
    "class GmailSendRequest(BaseModel):\n"
    "    to: str\n"
    "    subject: str\n"
    "    body: str\n"
    "    process_id: str | None = None    # optional -- a default makes a field non-required\n"
))
story.append(bl(
    "POST a body missing <font name='Courier'>subject</font>, or with <font name='Courier'>to</font> "
    "as a number instead of a string, and FastAPI returns a <font name='Courier'>422 Unprocessable "
    "Entity</font> with a field-by-field error list — <i>before</i> your route function is called at "
    "all. You never write "
    "<font name='Courier'>if \"subject\" not in body: raise ...</font> — the type hints "
    "<i>are</i> the validation rules."
))

story.append(h2("1.5 Dependency Injection — the concept that makes FastAPI's design different"))
story.append(bl(
    "This is the single most distinctive FastAPI idea, and the one most worth understanding "
    "properly (this repo leans on it heavily — see §2.3). The problem: a route often needs some "
    "shared object — a database connection, a config, an authenticated user — and you don't want to "
    "construct it by hand inside every single route function. <b>Depends()</b> solves this: declare a "
    "parameter's default as <font name='Courier'>Depends(some_function)</font>, and FastAPI calls "
    "<font name='Courier'>some_function()</font> for you before your route runs, then passes its "
    "return value in as that parameter."
))
story.append(code_block(
    "def get_db():\n"
    "    return Database(...)          # could open a connection, read config, anything\n\n"
    "@app.get(\"/users/{id}\")\n"
    "def get_user(id: int, db: Database = Depends(get_db)):\n"
    "    return db.query(...)          # `db` arrived already built -- this function never called get_db() itself\n"
))
story.append(bl(
    "This is real dependency injection, not just a naming convention: the route function declares "
    "<i>what it needs</i> (a <font name='Courier'>Database</font>), and something outside the "
    "function decides <i>how to build it</i>. Swap what <font name='Courier'>get_db</font> returns — "
    "a real database in production, a fake one in tests — and every route using it changes behavior "
    "with zero edits to the routes themselves. FastAPI also builds a dependency <i>graph</i>: a "
    "dependency can itself take a <font name='Courier'>Depends(...)</font> parameter, and FastAPI "
    "resolves the whole chain, caching each dependency's result once per request by default so "
    "calling the same dependency twice in one request doesn't rebuild it twice."
))

story.append(h2("1.6 async def vs def — when it actually matters"))
story.append(bl(
    "FastAPI lets a path operation be either <font name='Courier'>async def</font> or plain "
    "<font name='Courier'>def</font>, and both work — the difference is about the server's event "
    "loop, not correctness. An ASGI server (see §1.8) runs one event loop handling many requests "
    "concurrently by <i>interleaving</i> them whenever a request hits an <font name='Courier'>await</font> "
    "(e.g. an async database call, an async HTTP request). If a route is <font name='Courier'>async "
    "def</font> but calls something <i>blocking</i> inside it (a synchronous network call, a heavy "
    "CPU loop) without awaiting it, that call blocks the <i>entire event loop</i> — every other "
    "in-flight request stalls too, not just this one. A plain <font name='Courier'>def</font> route "
    "is automatically run by FastAPI in a separate thread pool instead, so a blocking call inside it "
    "only blocks that one thread. Rule of thumb: <font name='Courier'>async def</font> only if "
    "everything inside genuinely uses <font name='Courier'>await</font>; otherwise plain "
    "<font name='Courier'>def</font> is the safer default."
))

story.append(h2("1.7 Response models, status codes, and error handling"))
story.append(code_block(
    "@app.post(\"/items\", response_model=ItemOut, status_code=201)\n"
    "def create_item(item: Item) -> ItemOut:\n"
    "    ...\n\n"
    "from fastapi import HTTPException\n\n"
    "@app.get(\"/items/{id}\")\n"
    "def get_item(id: int):\n"
    "    if id not in db:\n"
    '        raise HTTPException(status_code=404, detail="not found")\n'
    "    return db[id]\n"
))
story.append(bl(
    "<font name='Courier'>response_model</font> does two things: it filters the returned object down "
    "to exactly that shape (extra attributes on what you return are silently dropped, not leaked to "
    "the caller), and it's what populates the auto-generated docs' \"response schema\" section. "
    "<font name='Courier'>HTTPException</font> is how a route signals a clean, intentional error — "
    "raise it anywhere in a route (or in a dependency) and FastAPI turns it into a proper JSON error "
    "response with that status code, short-circuiting the rest of the function."
))

story.append(h2("1.8 How it actually runs: ASGI servers and Uvicorn"))
story.append(bl(
    "FastAPI itself is just an application object — something needs to actually accept TCP "
    "connections, parse HTTP, and call into it. That's an <b>ASGI server</b>, almost always "
    "<b>Uvicorn</b> in practice:"
))
story.append(code_block("uvicorn apm_connectors.api.app:app --reload --port 8000"))
story.append(bl(
    "<font name='Courier'>apm_connectors.api.app:app</font> means \"import the module "
    "<font name='Courier'>apm_connectors.api.app</font> and use its module-level variable named "
    "<font name='Courier'>app</font>\" — that variable is the actual FastAPI instance Uvicorn drives. "
    "<font name='Courier'>--reload</font> watches source files and restarts on change (dev only). "
    "This detail matters for understanding this repo's <font name='Courier'>app.py</font> in Part 2, "
    "which ends with exactly that module-level <font name='Courier'>app = create_app()</font> line."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 2 — THIS REPO'S API LAYER
# ---------------------------------------------------------------------------
story.append(h1("Part 2 — This repo's FastAPI layer, file by file"))

story.append(bl(
    "src/apm_connectors/api/ has five files. Read them in this order — each one only makes sense "
    "once you've seen the one before it:"
))
layout_rows = [
    ["<b>File</b>", "<b>Lines</b>", "<b>Role</b>"],
    ["schemas.py", "148", "Pydantic request/response models — the request-body shape for every route."],
    ["dependencies.py", "133", "Builds the shared tools/state-store/action-graph once per process; the Depends() targets."],
    ["_responses.py", "30", "Two tiny shared helpers: error translation, and RunOutcome → response conversion."],
    ["tools_routes.py", "319", "The actual /tools/* routes — one read + one write route pair per connector."],
    ["app.py", "57", "Builds the FastAPI app, mounts tools_routes' router, adds /health and /processes/*."],
]
story.append(simple_table(layout_rows, [1.3 * inch, 0.6 * inch, USABLE_W - 1.9 * inch]))

story.append(h2("2.1 schemas.py — the request/response contract"))
story.append(bl(
    "One <font name='Courier'>BaseModel</font> per route, one field per keyword argument the "
    "matching connector method takes, plus an always-optional <font name='Courier'>process_id</font>:"
))
story.append(code_block(
    "class GmailSendRequest(BaseModel):\n"
    "    process_id: str | None = None\n"
    "    to: str\n"
    "    subject: str\n"
    "    body: str\n\n"
    "class RunOutcomeResponse(BaseModel):\n"
    '    """Mirrors apm_connectors.graph.RunOutcome. Exactly one of\n'
    "    pending_action / final_result is set.\"\"\"\n"
    "    action_id: str\n"
    "    summary: str | None\n"
    "    pending_action: dict[str, Any] | None\n"
    "    final_result: dict[str, Any] | None\n"
))
story.append(bl(
    "Two design choices worth naming. First, <b>process_id is optional everywhere</b> — a calling "
    "reasoning layer won't always have an internal case id, and shouldn't need to invent one just to "
    "call a connector; the server generates one internally when omitted (§2.4). Second, "
    "<b>RunOutcomeResponse is a discriminated-by-convention union</b>: exactly one of "
    "<font name='Courier'>pending_action</font>/<font name='Courier'>final_result</font> is ever "
    "non-null, and every write route shares this one response shape — a caller checks which field is "
    "set rather than branching on route-specific response types."
))

story.append(h2("2.2 _responses.py — the error-translation seam"))
story.append(code_block(
    "def upstream_error(exc: Exception) -> HTTPException:\n"
    '    """Turn an unexpected failure ... into a clean 502 response with a\n'
    "    readable message, instead of letting an unhandled 500 with a raw\n"
    '    Python traceback reach the caller."""\n'
    '    return HTTPException(status_code=502, detail=f"Upstream tool error: {exc}")\n\n'
    "def to_response(outcome: RunOutcome) -> RunOutcomeResponse:\n"
    "    return RunOutcomeResponse(\n"
    "        action_id=outcome.process_id, summary=outcome.summary,\n"
    "        pending_action=outcome.pending_action, final_result=outcome.final_result,\n"
    "    )\n"
))
story.append(bl(
    "Two tiny functions, but they exist specifically so <font name='Courier'>app.py</font> and "
    "<font name='Courier'>tools_routes.py</font> never need to import from each other — both import "
    "this shared, dependency-free module instead. <font name='Courier'>upstream_error</font> is the "
    "one place a raw connector-level exception (a network error, an exhausted retry) becomes a clean "
    "API error; every route wraps its risky call in "
    "<font name='Courier'>try/except Exception as exc: raise upstream_error(exc) from exc</font>."
))

story.append(h2("2.3 dependencies.py — the Depends() targets, and the Postgres toggle"))
story.append(bl(
    "Three functions, each decorated <font name='Courier'>@lru_cache</font> — every route's "
    "<font name='Courier'>Depends(get_tools)</font>/<font name='Courier'>Depends(get_action_graph)</font> "
    "points here:"
))
story.append(code_block(
    "@lru_cache\n"
    "def get_state_store() -> StateStoreProtocol:\n"
    "    settings = load_settings()\n"
    "    if settings.database_url:\n"
    "        from apm_connectors.state.postgres_store import PostgresStateStore\n"
    "        return PostgresStateStore(_get_postgres_pool())\n"
    "    return StateStore()\n\n"
    "@lru_cache\n"
    "def get_tools() -> dict[str, BaseTool]:\n"
    "    ...  # builds Gmail/Calendar/Excel/Salesforce/Jira, whichever have credentials configured\n\n"
    "@lru_cache\n"
    "def get_action_graph():\n"
    "    ...  # MemorySaver checkpointer, or PostgresSaver if settings.database_url is set\n"
    "    return build_action_graph(get_tools(), get_state_store(), checkpointer=checkpointer)\n"
))
story.append(bl(
    "<b>Why @lru_cache and not a fresh object per request.</b> Depends() by default resolves a fresh "
    "call <i>per request</i> — but the compiled action graph's checkpointer holds paused, "
    "mid-approval state <i>between</i> requests (a write proposed on one request is approved on a "
    "later, separate request). A per-request "
    "<font name='Courier'>get_action_graph()</font> would silently lose that state between the two "
    "calls. <font name='Courier'>@lru_cache</font> on a zero-argument function makes it a process-wide "
    "singleton instead: built once, on first use, reused for the life of the process. This is also "
    "exactly why the tool set, the state store, and the compiled graph must all be built through "
    "these cached functions and never constructed directly inside a route."
))
story.append(bl(
    "<b>The DATABASE_URL branch is a Strategy pattern, chosen once at startup</b>: the same "
    "<font name='Courier'>Depends(get_state_store)</font> call site works identically whether it "
    "resolves to a JSON-file store or a Postgres-backed one — nothing downstream branches on which. "
    "See the State Store and Persistence sections of the architecture reference doc for the full "
    "story on why this exists."
))

story.append(h2("2.4 tools_routes.py — the actual routes, and the two shapes"))
story.append(bl(
    "Every one of the eighteen routes here is one of exactly two shapes. A <b>read</b> calls the "
    "tool directly and returns data immediately:"
))
story.append(code_block(
    "@router.post(\"/salesforce/query\")\n"
    "def salesforce_query(body: SalesforceQueryRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[dict]:\n"
    "    tool = _tool(tools, \"salesforce\")\n"
    "    process_id = _resolve_process_id(body.process_id)\n"
    "    try:\n"
    "        results = tool.query_records(process_id, soql=body.soql)\n"
    "    except Exception as exc:\n"
    "        raise upstream_error(exc) from exc\n"
    "    return [r.__dict__ for r in results]\n"
))
story.append(bl(
    "A <b>write</b> never calls the tool's write method at all — it hands the request to the action "
    "graph instead, via the shared <font name='Courier'>_propose</font> helper:"
))
story.append(code_block(
    "def _propose(graph, process_id, tool, method, description, payload) -> RunOutcomeResponse:\n"
    "    try:\n"
    "        outcome = start_action(graph, process_id, tool=tool, method=method,\n"
    "                                description=description, payload=payload)\n"
    "    except Exception as exc:\n"
    "        raise upstream_error(exc) from exc\n"
    "    return to_response(outcome)\n\n"
    "@router.post(\"/salesforce/create\", response_model=RunOutcomeResponse)\n"
    "def salesforce_create(body: SalesforceCreateRequest, tools=Depends(get_tools), graph=Depends(get_action_graph)):\n"
    '    _tool(tools, "salesforce")  # fail fast, before recording a pending action doomed to fail\n'
    "    description = f\"Create Salesforce {body.object_name} record\"\n"
    "    payload = {\"object_name\": body.object_name, \"fields\": body.fields}\n"
    "    return _propose(graph, action_id, \"salesforce\", \"create_record\", description, payload)\n"
))
story.append(bl(
    "Three tiny module-level helpers make every one of the eighteen routes a 3-6 line function: "
    "<font name='Courier'>_tool(tools, name)</font> raises a clean 503 if that connector isn't "
    "configured on this server (rather than the route breaking with an unrelated error); "
    "<font name='Courier'>_resolve_process_id(process_id)</font> generates a "
    "<font name='Courier'>uuid4()</font> when the caller omitted one; "
    "<font name='Courier'>_propose(...)</font> is the one call every write route makes into the "
    "action graph. And there's exactly <b>one</b> decision route, shared by every write, because "
    "approving or rejecting is the same operation no matter which connector proposed the action:"
))
story.append(code_block(
    "@router.post(\"/actions/{action_id}/decision\", response_model=RunOutcomeResponse)\n"
    "def decide_action(action_id: str, body: DecisionRequest, graph=Depends(get_action_graph)) -> RunOutcomeResponse:\n"
    "    try:\n"
    "        outcome = resume_process(graph, action_id, approved=body.approved)\n"
    "    except Exception as exc:\n"
    "        raise upstream_error(exc) from exc\n"
    "    return to_response(outcome)\n"
))
story.append(bl(
    "Note the <font name='Courier'>APIRouter</font> at the top of the file — "
    "<font name='Courier'>router = APIRouter(prefix=\"/tools\", tags=[\"tools\"])</font> — every "
    "route in this file is declared against <font name='Courier'>router</font>, not "
    "<font name='Courier'>app</font> directly. That's what lets <font name='Courier'>app.py</font> "
    "mount this whole file's worth of routes in one line (§2.5): "
    "<font name='Courier'>APIRouter</font> is FastAPI's way of splitting a large app's routes across "
    "files/modules without every route needing a reference to the top-level app object."
))

story.append(h2("2.5 app.py — assembling the app"))
story.append(code_block(
    "def create_app() -> FastAPI:\n"
    '    app = FastAPI(title="APM Connectors & Enterprise Systems API")\n'
    "    app.include_router(tools_router)          # every /tools/* route, mounted in one line\n\n"
    '    @app.get("/health")\n'
    "    def health() -> dict[str, str]:\n"
    '        return {"status": "ok"}\n\n'
    '    @app.get("/processes/{process_id}/status")\n'
    "    def get_process_status(process_id: str, store: StateStore = Depends(get_state_store)) -> dict:\n"
    "        status = store.get_status(process_id)\n"
    "        if status is None:\n"
    '            raise HTTPException(status_code=404, detail=f"unknown process_id: {process_id}")\n'
    "        return status\n\n"
    "    # ... /processes, /processes/{id}/history, /processes/{id}/pending, same shape ...\n"
    "    return app\n\n"
    "app = create_app()   # module-level instance -- what uvicorn actually imports and runs\n"
))
story.append(bl(
    "<b>Why a factory function (create_app()) instead of just a module-level FastAPI() call.</b> A "
    "function that <i>builds and returns</i> an app can be called more than once, with different "
    "results each time — critically, this is what lets tests build a fresh app per test case rather "
    "than sharing one global mutable instance across an entire test run (see §2.8). The module-level "
    "<font name='Courier'>app = create_app()</font> at the bottom exists purely for Uvicorn, which "
    "needs a real importable variable to point at (§1.8) — it's not what tests use."
))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 3 — DESIGN PATTERNS, NAMED
# ---------------------------------------------------------------------------
story.append(h1("Part 3 — Design patterns used here, named explicitly"))
story.append(bl(
    "Interview-relevant framing: these aren't decorative labels, each one is doing real work in this "
    "codebase. Being able to name the pattern <i>and</i> point at the concrete problem it solves here "
    "is the difference between having read about a pattern and having used one."
))

patterns = [
    ["<b>Pattern</b>", "<b>Where</b>", "<b>What problem it actually solves here</b>"],
    ["Dependency Injection",
     "Every route's <font name='Courier'>Depends(get_tools)</font> / <font name='Courier'>Depends(get_action_graph)</font>",
     "Routes declare what they need, not how to build it — swapping real tools for fake ones in tests needs zero route-code changes (§2.8)."],
    ["Singleton (via @lru_cache)",
     "dependencies.py's three cached functions",
     "The compiled action graph's checkpointer must persist paused state across separate requests — a fresh instance per request would lose it (§2.3)."],
    ["Factory Function",
     "create_app(), build_action_graph(...), build_server(...) (MCP layer)",
     "Same shape everywhere in this codebase: take dependencies as parameters, return a built object, so tests inject different dependencies without subclassing anything."],
    ["Strategy (pluggable implementation)",
     "get_state_store()'s DATABASE_URL branch",
     "Two interchangeable persistence backends (file vs. Postgres) behind one call site — the caller never branches on which is active."],
    ["Adapter / Protocol",
     "StateStoreProtocol (state/store.py)",
     "Callers depend on a method surface, never a concrete class — this is what makes the file-store-to-Postgres swap possible without touching routes."],
    ["Facade",
     "tools_routes.py's route functions",
     "Each route is a thin 3-6 line facade over a much larger subsystem (the connector layer + the action graph) — callers never see that complexity."],
    ["Chain of Responsibility (error translation)",
     "raw exception → HTTPException (here) → ConnectorAPIError (MCP client) → ToolError (MCP server)",
     "Each layer boundary owns translating failures into its own vocabulary, so nothing downstream ever sees a raw traceback."],
    ["Router / Module pattern",
     "APIRouter(prefix=\"/tools\") + app.include_router(...)",
     "Splits a large app's routes across files without every route needing direct access to the top-level FastAPI instance."],
]
story.append(simple_table(patterns, [1.3 * inch, 1.7 * inch, USABLE_W - 3.0 * inch]))

story.append(h2("3.1 Testing pattern: dependency_overrides"))
story.append(bl(
    "FastAPI's dependency injection has a matching testing mechanism: "
    "<font name='Courier'>app.dependency_overrides</font> is a dict mapping a dependency function to "
    "a replacement, checked before FastAPI would normally call the real one:"
))
story.append(code_block(
    "app = create_app()\n"
    "app.dependency_overrides[get_tools] = lambda: fake_tools_dict\n"
    "app.dependency_overrides[get_action_graph] = lambda: fake_action_graph\n\n"
    "client = TestClient(app)\n"
    'response = client.post("/tools/salesforce/query", json={"soql": "SELECT Id FROM Account"})\n'
))
story.append(bl(
    "This is the direct payoff of §2.3's design choice: because every route depends on "
    "<font name='Courier'>get_tools</font>/<font name='Courier'>get_action_graph</font> rather than "
    "importing concrete tool classes, a test can redirect <i>only those two functions</i> and every "
    "route automatically uses fake, no-live-credentials-needed connectors — no route code changes, "
    "no monkeypatching internals. <font name='Courier'>TestClient</font> itself runs requests "
    "in-process against the ASGI app object directly (no real socket, no separately-running Uvicorn) — "
    "the same in-process-ASGI idea the MCP server layer's own tests reuse via "
    "<font name='Courier'>httpx.ASGITransport</font>."
))

story.append(h2("3.2 Full route table"))
route_rows = [
    ["<b>Route</b>", "<b>Kind</b>", "<b>Connector method</b>"],
    ["POST /tools/gmail/search, /read", "read", "search_emails, read_message"],
    ["POST /tools/gmail/send", "write", "send_email"],
    ["POST /tools/calendar/search, /read", "read", "search_events, read_event"],
    ["POST /tools/calendar/create-event", "write", "create_event"],
    ["POST /tools/excel/worksheets, /read", "read", "list_worksheets, read_range"],
    ["POST /tools/excel/write", "write", "write_range"],
    ["POST /tools/salesforce/query, /read", "read", "query_records, get_record"],
    ["POST /tools/salesforce/create, /update", "write", "create_record, update_record"],
    ["POST /tools/jira/search, /read", "read", "search_issues, get_issue"],
    ["POST /tools/jira/create, /update", "write", "create_issue, update_issue"],
    ["POST /tools/actions/{action_id}/decision", "shared decision", "resume_process"],
    ["GET /health, /processes, /processes/{id}/*", "status/audit", "StateStore reads"],
]
story.append(simple_table(route_rows, [2.6 * inch, 1.1 * inch, USABLE_W - 3.7 * inch]))

story.append(rule())

# ---------------------------------------------------------------------------
# PART 4 — INTERVIEW-PREP CHEAT SHEET
# ---------------------------------------------------------------------------
story.append(h1("Part 4 — Interview-prep Q&A"))
story.append(bl(
    "Likely questions this codebase can answer concretely, not just in the abstract. Practice "
    "answering by pointing at the actual code, not reciting the definition."
))

qa = [
    ("Q: What is dependency injection, and why not just call the constructor directly in the route?",
     "A: The route declares a parameter typed as Depends(some_function) instead of building the "
     "object itself. FastAPI resolves it before the route runs. The payoff is substitutability: "
     "tests override get_tools/get_action_graph to inject fakes (§3.1) with zero changes to route "
     "code — impossible if routes called GmailTool(...) directly."),
    ("Q: Why @lru_cache instead of a module-level global for the shared state store/tools/graph?",
     "A: @lru_cache on a zero-arg function gives you a lazily-built singleton — built on first call, "
     "not at import time (so tests that override dependency_overrides before first use never "
     "trigger the real construction at all), versus a module-level global that would build "
     "eagerly on import regardless of whether a test needs it."),
    ("Q: How does FastAPI know whether a parameter is a path param, query param, or body?",
     "A: By where it's declared: named in the route's path template -> path param; a plain scalar "
     "not in the path -> query param; a Pydantic BaseModel subclass -> request body, parsed from "
     "JSON (§1.3)."),
    ("Q: What actually happens on a 422 response?",
     "A: Pydantic validation failed on the request body before the route function was even called -- "
     "a required field was missing, or a field's value didn't match its declared type. This repo's "
     "routes never hand-check for missing fields because Pydantic already guarantees they're present "
     "and correctly typed by the time the function body runs."),
    ("Q: async def or def -- how do you decide?",
     "A: async def only if the function awaits everything inside it; otherwise plain def, because "
     "FastAPI runs sync routes in a thread pool automatically, so a blocking call there can't stall "
     "the whole event loop the way it would inside an async def that forgot to await it (§1.6)."),
    ("Q: Why does this API have exactly one decision route instead of e.g. /tools/gmail/send/approve?",
     "A: Approving or rejecting is identical regardless of which connector proposed the action -- it "
     "always resolves to the same resume_process(graph, action_id, approved) call. One shared route "
     "means one place to test and reason about the approval mechanic, instead of duplicating it once "
     "per connector."),
    ("Q: Where would you add a new connector's routes, and what would break if you changed an "
     "existing route's response shape?",
     "A: Add new routes to tools_routes.py following the read/write shapes in §2.4 -- that's "
     "additive. Changing an existing route's request/response shape is a breaking change for any "
     "caller already coded against docs/api-contract.md -- CLAUDE.md calls this out explicitly as "
     "the line between safe and unsafe API changes."),
    ("Q: How is this tested without hitting real Gmail/Salesforce/Jira APIs?",
     "A: dependency_overrides swaps get_tools/get_action_graph for versions built on fake HTTP "
     "clients, and TestClient drives requests through the real ASGI app in-process -- real route "
     "handlers, real Pydantic validation, real graph logic, zero live credentials or network calls "
     "(§3.1)."),
]
for q, a in qa:
    story.append(caption(q))
    story.append(bl(a))

story.append(Spacer(1, 10))
story.append(h1("Vocabulary cheat-sheet"))
vocab = [
    ["Type hint (x: int)", "Advisory annotation of expected type -- ignored by plain Python at runtime, but read and enforced by Pydantic/FastAPI (§0.3)."],
    ["X | None", "Union type meaning \"X, or None\" (Python 3.10+); older code writes the equivalent Optional[X] instead."],
    ["Decorator (@x)", "A function that wraps another function, applied via @ syntax right above a def (§0.5) -- e.g. @app.get(...), @lru_cache."],
    ["List comprehension", "[expr for item in iterable] -- builds a list in one line instead of a for-loop with .append() (§0.7)."],
    ["f-string (f\"...\")", "A string literal that evaluates {expressions} inside it and substitutes the result (§0.6)."],
    ["raise X from Y", "Exception chaining -- raises a new exception while keeping the original one attached as its cause (§0.8)."],
    ["ASGI", "Asynchronous Server Gateway Interface -- the async-capable successor to WSGI; what Uvicorn implements and FastAPI is built on."],
    ["Path operation", "A function decorated with @app.get/@app.post/etc. -- FastAPI's term for one route handler."],
    ["Depends()", "Declares a parameter as resolved by calling another function first -- FastAPI's dependency-injection mechanism."],
    ["Pydantic BaseModel", "A class whose type-hinted fields double as a validation schema, applied automatically to request bodies."],
    ["response_model", "Filters/documents a route's return shape -- extra attributes on the returned object are dropped, not leaked."],
    ["HTTPException", "The way a route (or a dependency) signals a clean, intentional error response."],
    ["APIRouter", "A mountable group of routes, declared without a reference to the top-level app -- assembled via app.include_router(...)."],
    ["@lru_cache", "Standard-library memoization; on a zero-arg function it acts as a lazy, process-wide singleton."],
    ["TestClient / dependency_overrides", "FastAPI's in-process testing mechanism: real ASGI app, real routes, swapped dependencies, no live server or credentials."],
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
    "That's the whole layer: five small files, no reasoning of its own, every route a thin facade "
    "over the connector layer and the action graph — built entirely from ordinary FastAPI primitives "
    "(routing, Pydantic validation, dependency injection) used consistently enough that the same "
    "handful of patterns explain every file."
))

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(
    str(OUT), pagesize=letter,
    leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=0.95 * inch,
    title="FastAPI Layer -- apm_connectors/api/",
)
DOC_FOOTER = footer("APM Connectors & Enterprise Systems — FastAPI Layer Reference")
doc.build(story, onFirstPage=DOC_FOOTER, onLaterPages=DOC_FOOTER)
print("wrote", OUT)
