"""
Integration tests against a real IBM MQ instance.

Requires a running MQ container:

    docker run --detach --name mq-test \
      --env LICENSE=accept \
      --env MQ_QMGR_NAME=QM1 \
      --env MQ_ADMIN_PASSWORD=passw0rd \
      --publish 9443:9443 \
      icr.io/ibm-messaging/mq:9.3.5.1-r2

Then run:

    uv run pytest tests/test_integration.py -v

Environment variables (all optional, fall back to defaults):
  MQ_URL_BASE   - e.g. https://localhost:9443/ibmmq/rest/v3/admin/
  MQ_USERNAME   - default: admin
  MQ_PASSWORD   - default: passw0rd
  MQ_QMGR_NAME  - default: QM1
"""

import asyncio
import os

import pytest

from mqmcp.server import _client_pool, dspmq, runmqsc

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clear_client_pool():
    """Clear the httpx client pool before each test.

    asyncio.run() creates a new event loop per call. httpx AsyncClient instances
    are bound to the event loop they were created in, so reusing a pooled client
    across asyncio.run() calls raises RuntimeError. Clearing the pool forces a
    fresh client (and a fresh event loop binding) for each test.
    """
    _client_pool.clear()
    yield
    _client_pool.clear()

URL_BASE = os.getenv("MQ_URL_BASE", "https://localhost:9443/ibmmq/rest/v3/admin/")
USERNAME = os.getenv("MQ_USERNAME", "admin")
PASSWORD = os.getenv("MQ_PASSWORD", "passw0rd")
QMGR = os.getenv("MQ_QMGR_NAME", "QM1")

# A username that does not exist — used to force 401 responses without
# hitting the client pool cache for the valid USERNAME.
BAD_USERNAME = "_invalid_user_"
BAD_PASSWORD = "wrongpassword"


# ---------------------------------------------------------------------------
# dspmq
# ---------------------------------------------------------------------------

def test_dspmq_returns_qmgr():
    result = asyncio.run(dspmq(url_base=URL_BASE, username=USERNAME, password=PASSWORD))
    assert f"name = {QMGR}" in result
    assert "running = running" in result


def test_dspmq_bad_credentials():
    # Use a distinct username so the client pool does not reuse the valid session.
    result = asyncio.run(dspmq(url_base=URL_BASE, username=BAD_USERNAME, password=BAD_PASSWORD))
    assert "HTTP error 401" in result


# ---------------------------------------------------------------------------
# runmqsc
# ---------------------------------------------------------------------------

def test_runmqsc_display_qmgr():
    result = asyncio.run(runmqsc(
        qmgr_name=QMGR,
        mqsc_command="DISPLAY QMGR",
        url_base=URL_BASE,
        username=USERNAME,
        password=PASSWORD,
    ))
    assert QMGR in result


def test_runmqsc_display_queue():
    result = asyncio.run(runmqsc(
        qmgr_name=QMGR,
        mqsc_command="DISPLAY QUEUE(DEV.QUEUE.1)",
        url_base=URL_BASE,
        username=USERNAME,
        password=PASSWORD,
    ))
    assert "DEV.QUEUE.1" in result


def test_runmqsc_invalid_command():
    result = asyncio.run(runmqsc(
        qmgr_name=QMGR,
        mqsc_command="NOTACOMMAND",
        url_base=URL_BASE,
        username=USERNAME,
        password=PASSWORD,
    ))
    # MQ returns HTTP 400 for unrecognised commands
    assert result.strip()
    assert "Something went wrong" not in result
    assert "HTTP error 400" in result or "[ERROR" in result or "AMQ" in result


def test_runmqsc_command_with_quotes():
    """Double quotes in the command must not corrupt the JSON payload."""
    result = asyncio.run(runmqsc(
        qmgr_name=QMGR,
        mqsc_command='DISPLAY QUEUE("DEV.QUEUE.1")',
        url_base=URL_BASE,
        username=USERNAME,
        password=PASSWORD,
    ))
    # MQ may reject the quoted syntax, but the request must not raise an exception
    assert isinstance(result, str)
    assert "Unexpected error" not in result


def test_runmqsc_bad_qmgr():
    result = asyncio.run(runmqsc(
        qmgr_name="NONEXISTENT",
        mqsc_command="DISPLAY QMGR",
        url_base=URL_BASE,
        username=USERNAME,
        password=PASSWORD,
    ))
    assert "HTTP error 404" in result


def test_runmqsc_bad_credentials():
    # Use a distinct username so the client pool does not reuse the valid session.
    result = asyncio.run(runmqsc(
        qmgr_name=QMGR,
        mqsc_command="DISPLAY QMGR",
        url_base=URL_BASE,
        username=BAD_USERNAME,
        password=BAD_PASSWORD,
    ))
    assert "HTTP error 401" in result
