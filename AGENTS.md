# AGENTS.md

## Overview
IBM MQ MCP server. Core logic lives in `mqmcp/server.py`. No test suite.

## Toolchain
- **Python 3.13** (pinned via `.python-version`; ignore README's claim of "3.10+")
- **`uv` is required** — no `requirements.txt` or `pip` workflow exists

```sh
uv sync           # install deps and register the mqmcp executable
uv run mqmcp      # run via entry point
```

No build, lint, typecheck, format, or test commands are configured. Do not attempt to run a test suite.

## Configuration
Defaults are defined as module-level constants in `mqmcpserver.py`:

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
- **`prettify_runmqsc`** branches on z/OS vs distributed by checking if the first `text` element starts with `"CSQN205I"`. Both branches must stay intact.
- **`completionCode`** (`"success"` / `"warning"` / `"error"`) and `reasonCode` are surfaced in `runmqsc` output — the MQ REST API returns these on partial failures that do not produce an HTTP error status.
- The `ibm-mq-rest-csrf-token` header is hardcoded to `"token"` (dspmq) / `"a"` (runmqsc) — required by the MQ REST API.
- **Client pool does not detect password changes** for the same `(url_base, username)` key. If credentials change, use a different username or restart the server.
- The `pyproject.toml` registers `mqmcp = "mqmcpserver:main"` as a script entry point. `uv sync` must be run (or `tool.uv.package = true` / a build-system must be present) for the entry point to be installed — both are already configured via `hatchling`.
