#
# Copyright (c) 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
from typing import Tuple

import httpx

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("mqmcpserver")

DEFAULT_URL_BASE = "https://localhost:9443/ibmmq/rest/v3/admin/"
DEFAULT_USER_NAME = "mqreader"
DEFAULT_PASSWORD = "mqreader"

# Client pool keyed by (url_base, username). One persistent client per host/user pair.
_client_pool: dict[Tuple[str, str], httpx.AsyncClient] = {}


def _get_client(url_base: str, username: str, password: str) -> httpx.AsyncClient:
    """Return a cached AsyncClient for the given host and credentials.
    A new client is created if the key is seen for the first time.
    Note: password changes for the same (url_base, username) are not detected;
    create a new session by using a different username if needed.
    """
    key = (url_base.rstrip("/"), username)
    if key not in _client_pool:
        _client_pool[key] = httpx.AsyncClient(
            verify=False,
            auth=httpx.BasicAuth(username=username, password=password),
        )
    return _client_pool[key]


@mcp.tool()
async def dspmq(
    url_base: str = DEFAULT_URL_BASE,
    username: str = DEFAULT_USER_NAME,
    password: str = DEFAULT_PASSWORD,
) -> str:
    """List available queue managers and whether they are running or not

    Args:
        url_base: Base URL of the mqweb REST API (e.g. https://localhost:9443/ibmmq/rest/v3/admin/)
        username: mqweb username
        password: mqweb password
    """
    headers = {
        "Content-Type": "application/json",
        "ibm-mq-rest-csrf-token": "token",
    }

    url = url_base.rstrip("/") + "/qmgr/"

    client = _get_client(url_base, username, password)
    try:
        response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        return prettify_dspmq(response.json())
    except httpx.HTTPStatusError as err:
        return f"HTTP error {err.response.status_code} from mqweb"
    except httpx.RequestError:
        return "Network error: could not reach mqweb"
    except Exception as err:
        return f"Unexpected error: {type(err).__name__}"


def prettify_dspmq(data: dict) -> str:
    """Format queue manager list, one entry per line separated by ---"""
    lines = ["\n---\n"]
    for qmgr in data["qmgr"]:
        lines.append(f"name = {qmgr['name']}, running = {qmgr['state']}\n---\n")
    return "".join(lines)


@mcp.tool()
async def runmqsc(
    qmgr_name: str,
    mqsc_command: str,
    url_base: str = DEFAULT_URL_BASE,
    username: str = DEFAULT_USER_NAME,
    password: str = DEFAULT_PASSWORD,
) -> str:
    """Run an MQSC command against a specific queue manager

    Args:
        qmgr_name: A queue manager name
        mqsc_command: An MQSC command to run on the queue manager
        url_base: Base URL of the mqweb REST API (e.g. https://localhost:9443/ibmmq/rest/v3/admin/)
        username: mqweb username
        password: mqweb password
    """
    headers = {
        "Content-Type": "application/json",
        "ibm-mq-rest-csrf-token": "a",
    }

    # Use json.dumps to safely serialize the command and avoid JSON injection
    data = json.dumps({
        "type": "runCommand",
        "parameters": {"command": mqsc_command},
    })

    url = url_base.rstrip("/") + "/action/qmgr/" + qmgr_name + "/mqsc"

    client = _get_client(url_base, username, password)
    try:
        response = await client.post(url, content=data, headers=headers, timeout=30.0)
        response.raise_for_status()
        return prettify_runmqsc(response.json())
    except httpx.HTTPStatusError as err:
        return f"HTTP error {err.response.status_code} from mqweb"
    except httpx.RequestError:
        return "Network error: could not reach mqweb"
    except Exception as err:
        return f"Unexpected error: {type(err).__name__}"


def prettify_runmqsc(data: dict) -> str:
    """Format MQSC command output, one response per line separated by ---.
    Deals with both z/OS and distributed queue managers.
    Surfaces completionCode warnings and errors alongside the output text.

    The MQ REST API returns completionCode as either an integer (0=success,
    8=warning, 16=error) or a string ("success"/"warning"/"error") depending
    on the API version. text may be a list of strings (z/OS) or a single
    string (distributed).
    """
    lines = ["\n---\n"]
    for entry in data["commandResponse"]:
        text = entry.get("text", [])
        raw_completion = entry.get("completionCode", 0)
        reason = entry.get("reasonCode", 0)

        # Normalise completionCode to a string regardless of API version
        if isinstance(raw_completion, int):
            completion = {0: "success", 8: "warning", 16: "error"}.get(raw_completion, "success")
        else:
            completion = str(raw_completion).lower()

        prefix = ""
        if completion == "warning":
            prefix = f"[WARNING reasonCode={reason}] "
        elif completion == "error":
            prefix = f"[ERROR reasonCode={reason}] "

        if not text:
            if prefix:
                lines.append(f"{prefix}\n---\n")
            continue

        # text may be a list of strings (z/OS) or a single string (distributed)
        if isinstance(text, list):
            # z/OS: strip leading CSQN205I banner and trailing summary line
            if text and text[0].startswith("CSQN205I"):
                for y in text[1:-1]:
                    lines.append(f"{prefix}{y[15:]}\n---\n")
            else:
                for line in text:
                    lines.append(f"{prefix}{line}\n---\n")
        else:
            lines.append(f"{prefix}{text}\n---\n")

    return "".join(lines)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
