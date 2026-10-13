# ENGINE.md — the memory engine map

Extracted from `~/Documents/coding/opthermes/optchat/` at tip `fc0b13e`. Signatures are copied
from the source, not from `CONTRACT.md`. Where the two disagree, **the source is what willia
vendors**, and the drift is listed in §7.

Anchors into the recipe: `~/.hermes/cache/scratch/optchat-gist/optchat.md` (§numbers cite it).

## 1. Vendored modules (the Reuse set)

| File | Lines | Owns | Vendor as |
|---|---|---|---|
| `store.py` | 242 | append-only, day-partitioned log | copy **minus the host ingestion protocol** (§8.1) |
| `tree.py` | 219 | build-once nodes, ready queue | byte-identical |
| `view.py` | 281 | sawtooth view, `due`, merge batch, compaction views, persist | byte-identical |
| `compactor.py` | 274 | scheduling, concurrency, retries | copy; one-line task change (§5.1), one review (§8.9) |
| `prompts.py` | 55 | the fixed prompt + compaction task templates | **rewritten to the recipe §5 text** (§5.1) |
| `text.py` | 52 | byte-bounded splitting | byte-identical |
| `notes.py` | 29 | note import | byte-identical |
| `tools.py` | 108 | `zoom` / `date` handlers | copy, **minus the host media envelope**, with our own child resolution (§8.4, §8.5) |
| `media.py` | 378 | media archive, pending retries | copy **minus the host envelope** (§8.5) |
| `persistence.py` | 63 | JSONL tail repair, atomic_json, sync_directory | byte-identical |

Vendored as **the source with the §6 rename list applied**: `optchat/` → `willia/`, the reply kind
`unii` → `will`, the navigation tools `optchat_zoom`/`optchat_date` → `zoom`/`date`, and the
`OptChat` product name inside warning and `error` strings → `willia`. Nothing else changes — with
the exceptions in §5 items 1 and 2.

**Not vendored (parked):** `engine.py` (83 KB, the Hermes `ContextEngine` adapter),
`turn_view.py`, `shim.py`, `__init__.py` (it imports `engine.py`; P0 writes its own),
`summarizer.py` (imports `agent.auxiliary_client`; §5.2), and **`cache.py`** (the host's
breakpoint planner; §5.4, §8.6).

## 2. Exact interfaces

### `persistence.py`

```python
def sync_directory(path: Path) -> None
def atomic_json(path: Path, value: object) -> None      # fsync'd temp + os.replace + dir sync
def read_jsonl(path: Path, *, seal: bool = True)        # yields (byte offset, JSON value)
```

`read_jsonl` rules (the durability floor for both the log and the tree):
- A complete record missing only its newline is yielded, and (when `seal`) the newline is written.
- An unparseable **tail** fragment is sealed with `NUL + newline` (permanently invalid) and the
  read stops. Only such sealed fragments may be skipped later.
- Ordinary mid-file corruption **raises** `ValueError(f"Corrupt JSONL record at {path}:{offset}")`.
- `seal=False` (read-only) never writes: a tail record is still yielded, a bad fragment is skipped.

### `store.py`

```python
KINDS = frozenset({"user", "will", "tool", "echo", "work", "note"})   # "will" was "unii" (§6)

@dataclass(frozen=True)
class Record:
    i: int; kind: str; text: str; size: int; date: str   # the design's line: {i, kind, text, size, date}

class LogLockedError(RuntimeError): ...

class Log:
    def __init__(self, root: Path, *, read_only: bool = False)
    def append(self, kind: str, text: str) -> int         # returns i
    def get(self, i: int) -> Record | None
    def range(self, lo: int, hi: int) -> list[Record | None]   # inclusive
    def count(self) -> int
    def close(self) -> None
    # context manager; __del__ closes
```

Guarantees:
- One writer per chat: `root/lock` held with `flock(LOCK_EX|LOCK_NB)` for the process lifetime;
  a second `Log` on the same root raises `LogLockedError("Chat log is locked: {root}")`.
- Every append: UTC `date = datetime.now(timezone.utc).isoformat()`, file `main/YYYY-MM-DD.jsonl`
  (from `date[:10]`), compact JSON `ensure_ascii=False, separators=(",", ":")`, `flush()` +
  `os.fsync()`; a missing newline is repaired before the append, so **the id never repeats**.
- Ids are dense and are identity: a duplicate id in a file raises; a **gap** raises
  `ValueError("Chat log has a gap in its record IDs")`; a line that parses but does not validate
  is *refused* loudly (`RuntimeWarning`), keeps its id slot, is never reused, and `get` returns
  `None` for it.
- Validation: id a nonnegative int, kind in `KINDS`, text a str, `date[:10] == file stem`,
  `size == len(text.encode("utf-8"))`.
- The host's ingestion protocol — `transaction(ingestion=…)`, `check_ingestion_idle()`, the
  `ingest.json` / `ingest-unavailable.json` files — is **deleted** in willia (§8.1): it reconciled a
  log derived from a host transcript, and willia's log is the primary artifact.
- `read_only=True`: no lock, no mkdir, no sealing — for reading another chat (child scopes).

### `tree.py`

```python
@dataclass(frozen=True)
class Line:
    l: int; i: int; text: str; size: int    # size = len(text.encode("utf-8"))

class Tree:
    def __init__(self, root: Path, node_bytes: int = 512, *, read_only: bool = False)
    def put(self, l: int, i: int, text: str) -> None
    def refused(self, l: int, i: int) -> bool
    def get(self, l: int, i: int) -> Line | None
    def nodes(self) -> dict[tuple[int, int], Line]        # a copy
    def children(self, l: int, i: int) -> tuple[tuple[int, int], tuple[int, int]]
    def free_text(self, l: int, i: int) -> str | None     # text needing NO model call
    def buildable(self, count: int | None = None) -> list[tuple[int, int]]
    def needs_summary(self, l: int, i: int) -> bool
    def save(self) -> None
    def load(self) -> None
```

- Coordinates: `node(l, i)` covers `2^l` messages from `i·2^l` (§2). `children(l,i)` = `(l-1,2i)`,
  `(l-1,2i+1)`; it raises for `l < 1`.
- **Build-once is the invariant.** `put` on an existing key raises
  `ValueError("Node already built: (l, i)")`; `put` with missing children raises unless the load
  path passes `lenient=True`. Two different texts for one coordinate on load raise.
- `free_text`: for `l == 0`, the node's own text if `size <= node_bytes`; for `l > 0`, the two
  children joined by `"\n"` if that fits. Anything else → `None` (needs a model call).
- `buildable()` returns the ready queue (parents whose both children exist and are unbuilt);
  `buildable(count)` filters to `(i + 1) * (1 << l) <= count`.
- `save()` appends pending lines to `tree/YYYY-MM-DD.jsonl`, `flush` + `fsync` per line.
- `load()` reads all day files, refuses invalid lines loudly (and their coordinates are recorded
  in `_refused`, so they are never written again), keeps an already-written node whose children
  are missing (`RuntimeWarning`, then `lenient` insert — never rewritten).
- Refused coordinates and the same tail rule as the log apply here too.

### `view.py`

```python
PLACEHOLDER = "(not summarized yet: zoom it)"

def due(l: int, i: int, T: int) -> float          # (T - ((i + 2) * (1 << l) - 1)) / (1 << l)

class ViewStateUnavailable(RuntimeError): ...

class View:
    def __init__(self, tree: Tree, min_bytes: int = 64_000, max_bytes: int = 128_000,
                 *, records: int | None = None)
    def add_root(self, i: int) -> None                     # must append the next message
    def lines(self) -> list[Line]                          # PLACEHOLDER for unbuilt
    def settled(self) -> bool
    def render(self) -> str                                # "<chat>...</chat>"
    def context_view(self, min_bytes: int = 16_000, max_bytes: int = 32_000,
                     *, end: int | None = None, target: tuple[int, int] | None = None) -> str
    def merge_batch(self, T: int) -> None
    def save(self) -> None
    def load(self) -> None
```

- `render()`: `"<chat>\n" + "\n".join(f"{i << l}+{1 << l}|{text}") + ("\n" if body) + "</chat>"`,
  with `\n` and `\r` inside a line replaced by spaces. No dates (§3).
- Merge target: **batch** semantics only — `_merge_pairs` returns immediately unless
  `pending` or `size > max_bytes`; then it merges the most due legal pair, ranked
  `(due(l, i, T), -(i << l), pos)` taken as a maximum, until `size <= min_bytes` (§3.2).
  A pair is legal only if `i` is even, `pairs[pos+1] == (l, i+1)`, and `tree.get(l+1, i//2)`
  exists. If no legal pair exists it returns `True` (batch still pending) — so the sawtooth
  resumes at the next message instead of spinning.
- `View(records=N)`: the owner tells the view how many records the chat has.
- `load()`: `view.json` missing **and** no nodes **and** no records → the empty view is correct
  (saved silently). Missing with records/nodes → **`ViewStateUnavailable`, never a rebuild**,
  nothing written. A legacy bare-list `pairs` file is still accepted. `version` must be `2`.
- `save()` writes `view.json` through `atomic_json`:
  `{"version": 2, "pairs": [[l, i], ...], "batch_pending": bool, "compaction_views": [{"min_bytes", "max_bytes", "pairs", "batch_pending", "contexts"}]}`.
  Read-back validation: pairs must cover a contiguous prefix (`(i << l) == cursor`); a compaction
  view's pairs must all be built; a context may not exceed its boundary.
- `context_view(...)`: §4 of the recipe. Per `(min_bytes, max_bytes)` budget pair it keeps a
  **maintained** working view that only advances (`cursor` walks built level-0 nodes), plus
  **pinned** contexts keyed `node:{l}:{i}` or `end:{N}` — the first request for a target pins its
  exact line list and later requests reuse the identical bytes. A late target splits only
  straddling nodes by descending into children, so no line leaks a later message.
- A `target=(l, i)` fixes `end` to `i` for `l == 0`, else `(i + 1) << l`; a conflicting `end`
  raises.

### `compactor.py`

```python
@dataclass(frozen=True)
class CompactionRequest:
    system: str; context: str; task: str; tools: list

Summarizer = Callable[[CompactionRequest], str]
COMPACT_CONCURRENCY = 8

class Compactor:
    def __init__(self, tree: Tree, summarize: Summarizer, *,
                 node_bytes: int = 512, max_retries: int = 5, view: View | None = None)
    # public state the harness sets before run_pending: .system (turn system prompt), .tools (turn schemas)
    def seed(self, i: int, text: str, kind: str) -> None
    def submit(self, l: int, i: int) -> None
    def settle(self, max_nodes: int = 64, timeout_s: float = 20.0, *,
               model_calls: bool = False) -> int
    def run_pending(self, limit: int = COMPACT_CONCURRENCY, *, deadline: float | None = None,
                    model_calls: bool = True) -> int
```

- `seed` is the **only** way level-0 nodes appear. It stores `f"{kind}: {text}"` (§5's level-0
  `<input>` form, the kind tag carried from WP2). If that fits `node_bytes` it is `tree.put` with
  no model call; otherwise the source is held in `_sources[i]`, added to `_unbuilt_roots`, and
  submitted as a model job. Re-seeding an id raises.
- Request assembly (`_request`):
  - level 0: `COMPACTION_TASK.format(id=i, ..., input=source)`
  - merge: `COMPACTION_MERGE_TASK.format(a=f"{first}+{child_count}", b=f"{first+child_count}+{child_count}",
    id=first, end=first + (1 << l) - 1, ...)`, where `first = i << l`, `child_count = 1 << (l - 1)`
  - both: `ruler = "-" * node_bytes`, `node_bytes=512`; and `task` **is the template alone** in
    willia (deviation, §5.1: the design's system prompt already carries the compaction
    instructions, so the vendor's `COMPACTION_SYSTEM.format(rubric=RUBRIC) + "\n\n"` prefix is
    dropped).
  - `context = view.context_view(target=(l, i))`; `system`/`tools` are the turn's.
- Retry loop (`_summarize`): up to `max_retries` (5) calls; a raised exception or an empty reply
  warns and returns `None` (the node stays deferred); each reply is flattened
  (`" ".join(reply.splitlines()).strip()`); the shortest seen is kept; over `node_bytes` it gets
  `OVER_LENGTH_NOTICE` appended (with the first 512 bytes as the cut marker) and is retried.
- Scheduling (§4 "the order"): `run_pending` merges the view batch first, then runs waves of at
  most `min(limit, 8)` jobs through a `ThreadPoolExecutor`; each job gets its own
  `contextvars.copy_context()` (host-motivated: the host's route travelled in a ContextVar —
  willia passes the route explicitly; review §8.9);
  results are applied **in queue order**, so admission does not depend on finish order.
  A wave that built nothing defers its waiting keys instead of spinning.
- A level-0 model job is admitted only when fewer than `COMPACT_CONCURRENCY` unbuilt lines
  precede it (`bisect_left(_unbuilt_roots, i) < 8`), so no compaction ever sees a placeholder.
- `settle(...)`: `model_calls=False` by default — **the turn path must never start a model call**
  (a call in flight cannot be interrupted by the deadline). It builds free nodes and stops when
  the view is settled. Model work belongs to the background `run_pending`.
- Failures are deferred and re-queued in `finally`, never lost, never spun on.

### `text.py`

```python
def kind_prefix(kind: str) -> str                       # "{kind}: "
def split_for_kind(text: str, max_bytes: int, kind: str) -> list[str]
def split_text(text: str, max_bytes: int) -> list[str]
```

`split_for_kind` budgets `max_bytes - len(kind_prefix(kind))` for the raw text, so every chunk
still fits once tagged. `split_text` preserves all text, prefers a late whitespace boundary
(`size * 2 >= max_bytes`), and raises if a single character cannot fit.
**This is the long-paste rule:** other long text is never cut, it is logged as several messages
in a row (§1); tool output is the exception, clipped head+tail to 30,000 chars.

### `notes.py`

```python
def import_notes(log: Log, compactor: Compactor, view: View, texts: list[str]) -> int
```

Appends each `split_for_kind(text, node_bytes, "note")` chunk as a `note` record, seeds it, adds
its view root, then `tree.save()`, `run_pending(limit=8)`, `tree.save()`, `merge_batch(count())`,
`view.save()`. Returns the record count (a long text may become several). Used in P3 for
`OPTCHAT_HELLO.md`.

### `tools.py`

```python
def child_chat_dir(root: Path, name: object) -> Path | None     # was child_chat_root (index lookup)
def zoom(log: Log, tree: Tree, view: View | None, id: int | str, n: int = 1, *,
         scope: str | None = None, master_root: Path | None = None) -> str
def date(log: Log, id: int, *, scope: str | None = None) -> str
```

Exact payloads and error strings: `TOOLS.md` §2. Every error is a JSON string
`{"error": "..."}`. The vendor's `envelope=` parameter is gone (§8.5). Child resolution is ours
(§8.4): `<root>/agents/<name>/`, where the name must be a single safe path component and the
directory must hold a `view.json` — no index file, no repointing rules.

### `media.py`

```python
MEDIA_TYPES = {"image":"image","image_url":"image","input_image":"image",
               "audio":"audio","input_audio":"audio","file":"file","input_file":"file"}
class MediaPayloadError(ValueError): ...    # carries .reference verbatim
def has_media_parts(content: Any) -> bool
def archive_media(root: Path, message_id: int, content: Any) -> None
def media_for(root: Path, message_id: int) -> list[dict[str, str]]
def record_pending_media(root, message_id, part_index, kind, reference, error,
                        part=None, entries=None) -> None
def retry_pending_media(root: Path) -> dict[str, int]     # {"archived", "pending", "remote"}
```

Archives decodable media under `assets/{message_id}-{part_index}{ext}` and records it in
`assets/index.json`; a failure records the reference verbatim plus the error in
`assets/pending.json` (never swallowed). `retry_pending_media` re-tries local paths and data URLs;
**remote URLs are preserved untouched** (fetching remote bytes is an open capability — relevant
if `vision` returns images).

**Deleted in willia:** `envelope_media_parts()` and the host `_multimodal` tool-result envelope it
feeds (§8.5). The host converts tool-result parts as text and image; the Go relay rejects list-type
tool content outright, and the design has no envelope — an image reaches the model through the
`vision` tool, which returns text.

### `cache.py` — not vendored

```python
MAX_BREAKPOINTS = 4 ; LOOKBACK_BLOCKS = 20
def plan_view_cache(messages, tools) -> tuple[list, list] | None
```

The host's breakpoint planner: it marks the view in 4-line blocks for **explicit-breakpoint**
providers so a longer prefix stays cacheable. willia does not vendor it (§5.4, §8.6). The recipe's
cache section is about *when* the view merges — `view.py` and `compactor.py` already implement that
— and the Go route is automatic-prefix, where marks break the relay.

## 3. Invariants and which module enforces each

| Invariant (SCOPE) | Enforced by |
|---|---|
| Append-only, never edit/delete, one writer, flush every write | `store.Log` (flock, fsync, `_index` append-only) |
| Never rebuild the view; save/load it | `view.View.load` raises `ViewStateUnavailable` instead of rebuilding |
| Nodes built once, never rebuilt | `Tree.put` raises on a built key; `load` refuses rewrites of refused coordinates |
| Summaries ≤ 512 bytes, ruler-checked, retried | `Compactor._summarize` + `prompts.RUBRIC`/`OVER_LENGTH_NOTICE` |
| View is a constant-size sawtooth (64–128 KB) | `View._merge_pairs` (batch, `due` order) + `Compactor.run_pending` (merge before build) |
| Compactions reuse `[system][tools]` and have their own `<chat>` view (16–32 KB) | `Compactor._request` (`system`/`tools` = the turn's) + `View.context_view` |
| Nothing carries between turns; no dates/state in the prompt or tools | `prompts.SYSTEM_PROMPT` (fixed text) + the harness's request assembly (`WIRE-FORMATS` §3) |
| Never scan the tree for work | `Tree._ready` / `Compactor._pending` queues |
| Delegates never block the master | harness (`LOOP.md` §6, `DELEGATES.md`) |

## 4. Test map (opthermes `tests/`, 5,593 lines total)

**Vendored in P0 (no host imports):**

| Test | Lines | Covers |
|---|---|---|
| `test_store.py` | 226 | log, lock, ids, refusal, torn tail, read-only |
| `test_tree.py` | 187 | build-once, ready queue, free text, load repair |
| `test_view.py` | 376 | `due`, merge batch, render, view.json, unavailability |
| `test_compactor.py` | 551 | seeding, scheduling, admission, retries, concurrency |
| `test_text.py` | 32 | byte splitting |
| `test_notes.py` | 32 | note import |
| `test_tools.py` | 158 | `zoom`/`date` payloads (imports `optchat` root → see §5) |
| `test_media.py` | 332 | archive, pending retries (same) |

**Parked (import `engine.py` / `turn_view.py` / `shim.py`, or the package root that imports
`engine.py`):** `test_cache.py` (186, the host breakpoint planner), `test_engine.py` (2,377),
`test_compaction_prefix.py` (154, engine), `test_prompts.py` (72, engine), `test_summarizer.py`
(167, host route), `test_registration.py` (122), `test_shim.py` (134), `test_host_identity.py`
(140), `test_turn_view.py` (347). Together ~3,700 lines of host-coupled tests stay in opthermes.

No `conftest.py`, no `pytest.ini`/`pyproject.toml` exists in either repo: tests are plain pytest,
run with `~/.hermes/tools/uv-*/uv run --no-project --with pytest python -m pytest -q` (the repo
venv has no pytest — see the `opthermes` skill).

willia adds tests of its own on top of the vendored subset: the prompt/tool-name guard (§6), the
compaction request shape (`WIRE-FORMATS` §4), the startup reconciliation (`LOOP.md` §5), and one
test per new module (client, loop, REPL, tools, delegates).

## 5. Deviations, swaps and parks (each needs the reason recorded in the vendored file's header)

1. **`prompts.py` is rewritten to the design's single prompt.** The vendor's `SYSTEM_PROMPT` is a
   host-era condensation ("the five lines the spec names as doing the work"): it names
   `optchat_zoom`/`optchat_date`, and it drops the persona, the turns section and the compaction
   section — because Hermes supplied those around the engine. willia has no host, so the design's
   prompt is what it must send: the recipe **§5 block verbatim**, `Unii` renamed to `WillIA`, with
   the paragraph on computers dropped (there is no device shell here; coding is delegated), and
   **the user's own instructions appended** (the recipe: "The user's own instructions follow it:
   who they are, how their files are organized, how they want work done"). One fixed text,
   **identical for turns and compactions**. That is stronger than the vendor's split: the recipe's
   "# Compactions" section *is* the compaction instructions, so a compaction's user message carries
   the task template **alone**, and the vendor's separate `COMPACTION_SYSTEM`/`RUBRIC` constants are
   retired into the system prompt — the one-line deviation in `Compactor._request` (§2). The prompt
   is the cache anchor and must not vary per turn (§3.3, §7.10).
2. **`summarizer.py` is not vendored.** It imports `agent.auxiliary_client.call_llm` and
   `agent.auxiliary_task_config` — Hermes-only. What is kept is its **envelope**, which is the
   contract the new client must reproduce exactly:
   `[{"role":"system","content":request.system}]` + `[{"role":"assistant","content":request.context}]`
   + `[{"role":"user","content":request.task}]`, called with `tools=request.tools or None`.
   The reply is read as **ordinary content only** (never a reasoning field), flattened with
   `" ".join(splitlines()).strip()`, and an empty line raises (FINDINGS: a reasoning-only reply
   must never become a tree line).
3. **`__init__.py` is rewritten.** The vendored copy imports `engine`; willia's own package root
   must not. It exports the memory modules (and later the turn loop), nothing host-shaped.
4. **`cache.py` is not vendored.** It plans Anthropic-style breakpoints for the host's cache seam.
   OpenCode Go is an **automatic-prefix** route — FINDINGS #1: the relay 400s on block-array
   content, exactly what marks produce — and the design asks for no marks: its cache section is
   about *when* the view merges, which `view.py` already does. The module stays in opthermes; if a
   breakpoint-capable provider is ever added, it is re-derived from the design then (§8.6).
5. **The ingestion checkpoint protocol is deleted, not kept.** `ingest.json`,
   `ingest-unavailable.json`, `check_ingestion_idle()` and `transaction(ingestion=True)` were the
   host's way of reconciling a log *derived* from a transcript it did not own. In willia the log is
   the primary artifact — the design's own position, and the whole of its durability contract is
   "append, flush, one owner, never edit, save and load the view, build each node once" (§8.1).
6. **The child registry is ours, not the host's.** `tools.child_chat_root` reads
   `<root>/agents/index.json` — a host-era name→key map with first-mapping-wins and suffixed
   labels. willia replaces it with the simplest thing that satisfies the design's `zoom("Name")`:
   one directory per child, `<root>/agents/<label>/`, the label chosen at creation and validated as
   a single safe path component. No index file, no repointing rules (§8.4, `DELEGATES.md` §5).

## 6. The rename surface (decided: rename everything — this is a new app)

The agent's kind and tool names are **wire text**: they appear in the log records, the level-0 node
prefixes (`{kind}: `), the view the model reads, and every test that asserts them. Free now (no log
exists), a log migration later — so it happens once, in P0.

| Literal | Was | Is |
|---|---|---|
| package | `optchat/` | `willia/` (relative imports inside are unaffected) |
| reply kind | `"unii"` (`store.KINDS`, node prefix, view text) | `"will"` |
| log record field | `Record.id`, serialized `{"id": …}` | `Record.i`, `{"i": …}` — the recipe's own line (§8.11) |
| navigation tools | `optchat_zoom`, `optchat_date` | `zoom`, `date` |
| in-prompt name | `Unii` | `WillIA` |
| product name in strings | `OptChat chat log line …`, `OptChat tree line …`, `OptChat view state is unavailable …`, `OptChat is not active …` | `willia …` |
| imports in the vendored tests | `from optchat.x import y` | `from willia.x import y` |
| doc provenance | reference to the engine repo | kept as provenance only (`opthermes` `fc0b13e`) |

**Not renamed** (already product-neutral, renaming is churn): the data dirs and files (`main/`,
`tree/`, `view.json`, `assets/`, `agents/`, `lock`), the class names (`Log`, `Tree`, `View`,
`Compactor`), the tool payload keys `id` / `n` (the design's own vocabulary — `zoom(id, n)`), and
every byte constant.

The recipe's own warning applies here: the prompt must name the tools **exactly** as registered —
the host build once shipped `zoom`/`date` in the prompt while the tools were `optchat_*`, and
navigation was impossible. A test must read the names from the tool registry and assert each
appears in the system prompt (that guard exists in opthermes; port it in P0).

## 7. Drift: `CONTRACT.md` (v1, 2026-10-10) vs the source

The contract's "Interfaces" block is the v1 skeleton; 19 revisions later the source has grown.
Recorded so nobody briefs from the stale block:

- `Summarizer` is `Callable[[CompactionRequest], str]`, not `Callable[[str], str]`.
- `Compactor.__init__` also takes `view=`; `seed(i, text, kind)` carries the kind;
  `run_pending(limit=8, *, deadline=None, model_calls=True)`; `settle(...)` exists.
- `View.__init__` takes `records=`; `context_view`, `settled`, `ViewStateUnavailable` exist.
- `Log` gained `transaction`, `check_ingestion_idle`, `read_only`, refused ids, gap detection
  (the first two are deleted in willia — §8.1).
- `Tree` gained `refused`, `nodes`, `buildable(count)`, lenient load, refused coordinates.
- `persistence` and `media` are not in the v1 module map at all.
- The contract's Hermes-specific sections (the seam, `select_context`, config shape) are
  **out of scope for willia** — the harness replaces them (`LOOP.md`, `WIRE-FORMATS.md`).

## 8. Hermes-inherited surface: deleted, replaced, kept-with-reason

will.I.A. **implements the UniiChat/OptChat design** with its own harness; it is not a fork of the
engine's host. Anything whose only reason for existing was that host is gone or replaced; anything
kept nonetheless says why. Every row is P0 work.

| # | Item (source) | Verdict | Why |
|---|---|---|---|
| 8.1 | ingestion protocol: `check_ingestion_idle()`, `ingest.json`, `ingest-unavailable.json`, `transaction(ingestion=True)` | **delete** | reconciled a log *derived* from a host transcript; willia's log is primary (recipe §1: append, flush, one owner, never edit). |
| 8.2 | `store`'s duplicate-id / gap / refusal machinery | **keep** | integrity of the primary artifact, and the recipe is silent — loud is right. |
| 8.3 | `persistence.read_jsonl` tail repair + `atomic_json` | **keep** | the recipe wants the view saved and loaded, never rebuilt; a torn tail must not cost a chat. |
| 8.4 | `tools.child_chat_root` + `agents/index.json` + `_register_child`'s name rules | **replace** | the design has `zoom("Name")`; the registry shape was the host's delegate bookkeeping. Ours: a directory per label. |
| 8.5 | `media.envelope_media_parts` + the `_multimodal` envelope + `tools.zoom`'s `envelope=` | **delete** | the host's tool-result envelope; the Go relay rejects list-type tool content anyway. Archive + `media_for` stay. |
| 8.6 | `cache.py` (breakpoint planning) | **do not vendor** | the host's cache seam; the Go route is automatic-prefix and the design prescribes no marks. |
| 8.7 | `engine.py`, `turn_view.py`, `shim.py`, `summarizer.py`, `__init__.py` | **never vendored** | the host adapter, its turn view, its cache shim, its auxiliary route, its collector. |
| 8.8 | `Log`/`Tree`/`View(read_only=True)` lock-free foreign handles | **keep, unused in v1** | they serve a *live* second process owning a child chat; v1's children are our own jobs under our own root. |
| 8.9 | `Compactor`'s `contextvars.copy_context()` per job | **review in P0** | it carried the host's routing ContextVar into the worker pool; willia passes the route explicitly — if the concurrency tests pass without it, drop it. |
| 8.10 | `prompts.SYSTEM_PROMPT` (the seven-line condensation) | **replaced** | host-era; the design's §5 text replaces it (§5.1). |
| 8.11 | `Record.id` → `Record.i` | **rename** | the recipe's log line is `{i, kind, text, size, date}` and the tree line already uses `{l, i, …}`. Tool payloads keep `id`/`n`. |
| 8.12 | `Compactor.settle(model_calls=False)` | **keep, re-justified** | the vendor's reason was the host's uninterruptible synchronous hook; willia keeps it as a turn-side *budget* (`LOOP.md` §2). |

After these, nothing in the program exists for the host's sake: the harness is ours and the memory
modules are the design's.
