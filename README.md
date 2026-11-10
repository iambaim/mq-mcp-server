# IBM MQ MCP Server

> **Derived from** [ibm-messaging/mq-mcp-server](https://github.com/ibm-messaging/mq-mcp-server) (IBM Corp., Apache 2.0).
> This fork refactors the original into a proper Python package with an installable entry point, per-call connection parameters, a shared HTTP client pool, and improved error handling.

MCP (Model Context Protocol) is an open standard that allows LLMs and AI agents to discover and interact with external services such as databases, REST APIs, files, and other resources.
You can read up on the details of MCP [here](https://modelcontextprotocol.io/introduction).

This repo contains a simple MCP server, written in Python, that exposes a subset of the [MQ Administrative REST API](https://www.ibm.com/docs/en/ibm-mq/9.4.x?topic=administering-administration-using-rest-api) as two MCP tools:

- `dspmq` — lists queue managers accessible via the mqweb server and whether they are running
- `runmqsc` — runs any MQSC command against a specific queue manager, using the [plain text MQSC API](https://www.ibm.com/docs/en/ibm-mq/9.4.x?topic=adminactionqmgrqmgrnamemqsc-post-plain-text-mqsc-command)

Both tools accept `url_base`, `username`, and `password` as call-time parameters, so a single server instance can target multiple MQ hosts within the same session.

For FTM tenants, `ftm_dspmq` and `ftm_runmqsc` accept a Kubernetes namespace
instead. The server resolves the QueueManager, its admitted mqweb Route and
the referenced `MQ_APP_PASSWORD` Secret without returning the password to the
MCP client. The namespace must contain exactly one QueueManager and one
matching web Route. Tenant-mode calls reject endpoint and credential overrides.

Tenant MQSC is limited to single-line `DISPLAY` commands. The standalone
`runmqsc` tool retains its existing command behavior.

You can use this MCP server with any LLM that has an MCP client, for example [IBM Bob](https://www.ibm.com/products/bob) or [IBM Watsonx Orchestrate](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=servers-importing-tools-from-mcp-server).

## Prerequisites

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed
- A running IBM MQ installation with `mqweb` accessible

## Running directly from GitHub

```sh
uvx --from "git+https://github.com/ibm-messaging/mq-mcp-server.git" mqmcp
```

This installs and runs the server in one step with no local clone required.

## Running from a local clone

```sh
git clone https://github.com/ibm-messaging/mq-mcp-server.git
cd mq-mcp-server
uv sync
uv run mqmcp
```

The server starts on `stdio` by default, which is compatible with IBM Bob and most MCP clients.

## Configuration

The server ships with fallback defaults:

```python
DEFAULT_URL_BASE = "https://localhost:9443/ibmmq/rest/v3/admin/"
DEFAULT_USER_NAME = "mqreader"
DEFAULT_PASSWORD  = "mqreader"
```

You do not need to edit source to change these. Pass `url_base`, `username`, and `password` directly in each tool call, and the LLM will forward them to the correct MQ host.

> **Note on permissions:** if the mqweb user is a member of the `MQWebAdmin` or `MQWebUser` roles, `runmqsc` can modify your MQ configuration. Use a read-only user in production environments.

## FTM tenant access

Run the server in a Kubernetes pod with a dedicated service account. In each
permitted tenant namespace it needs `get`/`list` on `queuemanagers.mq.ibm.com`
and `routes.route.openshift.io`, and `get` on Secrets. It does not list Secrets.
The QueueManager's `MQ_APP_PASSWORD` environment entry must reference a Secret
key. The server reads it on each call, so password rotations take effect without
a restart.

Tenant-mode mqweb connections verify TLS. The CA bundle defaults to
`/etc/kagent-ca/ca-bundle.crt`; set `MQMCP_CA_BUNDLE` to use another file. The
standalone tools retain their existing TLS behavior.

## Connecting to an LLM

Follow the instructions provided by your LLM client for connecting via `stdio`. A [wide range](https://modelcontextprotocol.io/clients) of clients support MCP, including IBM Bob and IBM Watsonx Orchestrate.
