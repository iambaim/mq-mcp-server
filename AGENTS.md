# AGENTS.md

## Overview
IBM MQ MCP server. Core logic lives in `mqmcp/server.py`.

## Toolchain
- **Python 3.13** (pinned via `.python-version`; ignore README's claim of "3.10+")
- **`uv` is required** — no `requirements.txt` or `pip` workflow exists

```sh
uv sync --dev                              # install deps including pytest
uv run mqmcp                               # run via entry point
uv run pytest tests/ -v                    # unit tests only (default)
uv run pytest tests/test_integration.py -v -m integration  # integration tests (require live MQ)
```

No build, lint, typecheck, or format commands are configured.

## Configuration
Defaults are defined as module-level constants in `mqmcp/server.py`:

```python
DEFAULT_URL_BASE = "https://localhost:9443/ibmmq/rest/v3/admin/"
DEFAULT_USER_NAME = "mqreader"
DEFAULT_PASSWORD  = "mqreader"
```

There is no `.env` file or environment variable support. These are **fallback defaults only** — both tools accept `url_base`, `username`, and `password` as call-time parameters, so the LLM can target any host per invocation without editing source.

Requires a live IBM MQ instance with `mqweb` accessible at the target URL.

## Architecture
- Uses `FastMCP` from `mcp.server.fastmcp` with two `@mcp.tool()` async functions:
  - `dspmq(url_base, username, password)` — GETs `<url_base>/qmgr/` to list queue managers and their states
  - `runmqsc(qmgr_name, mqsc_command, url_base, username, password)` — POSTs MQSC to `<url_base>/action/qmgr/<name>/mqsc`
- Transport: `stdio` only
- **Shared client pool** (`_client_pool`) — one persistent `httpx.AsyncClient` per `(url_base, username)` pair; supports multiple hosts in the same session without reconnecting

## Quirks
- **TLS verification is disabled** (`verify=False`) — intentional for self-signed MQ certs. Do not "fix" it.
- **`runmqsc` uses `json.dumps`** to serialize the MQSC command safely. Do not revert to string concatenation.
- **`prettify_runmqsc`** handles both z/OS and distributed response shapes:
  - `text` may be a **single string** (distributed) or a **list of strings** (z/OS). Both are handled.
  - z/OS responses are detected by `text[0].startswith("CSQN205I")`; the banner and trailing summary line are stripped.
  - Both branches must stay intact.
- **`completionCode`** may be an **integer** (`0`=success, `8`=warning, `16`=error) or a **string** (`"success"`/`"warning"`/`"error"`) depending on MQ REST API version. Both are normalised internally. Unknown integer codes default to `"error"`.
- **`reasonCode`** is surfaced in `runmqsc` output alongside `completionCode` on partial failures that do not produce an HTTP error status.
- The `ibm-mq-rest-csrf-token` header is set to the module-level constant `_CSRF_TOKEN = "token"` on all requests — required by the MQ REST API; the value is arbitrary.
- **Client pool does not detect password changes** for the same `(url_base, username)` key. If credentials change, use a different username or restart the server.
- The `pyproject.toml` registers `mqmcp = "mqmcpserver:main"` as a script entry point. `uv sync` must be run (or `tool.uv.package = true` / a build-system must be present) for the entry point to be installed — both are already configured via `hatchling`.

## Tests
- `tests/test_server.py` — unit tests for pure functions (`prettify_dspmq`, `prettify_runmqsc`, signatures). Run by default with `pytest tests/`.
- `tests/test_integration.py` — integration tests requiring a live MQ container. Marked with `pytest.mark.integration` and excluded from the default run. The `clear_client_pool` autouse fixture clears `_client_pool` between tests to avoid event-loop binding issues with `asyncio.run()`.
