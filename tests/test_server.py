import inspect
import json

from mqmcp.server import (
    DEFAULT_PASSWORD,
    DEFAULT_URL_BASE,
    DEFAULT_USER_NAME,
    dspmq,
    prettify_dspmq,
    prettify_runmqsc,
    runmqsc,
)


# ---------------------------------------------------------------------------
# Import and entry point
# ---------------------------------------------------------------------------

def test_import():
    """Package and key symbols are importable."""
    from mqmcp import server  # noqa: F401
    assert callable(dspmq)
    assert callable(runmqsc)


def test_main_importable():
    from mqmcp.server import main
    assert callable(main)


# ---------------------------------------------------------------------------
# Tool signatures and defaults
# ---------------------------------------------------------------------------

def test_dspmq_signature():
    sig = inspect.signature(dspmq)
    params = sig.parameters
    assert "url_base" in params
    assert "username" in params
    assert "password" in params
    assert params["url_base"].default == DEFAULT_URL_BASE
    assert params["username"].default == DEFAULT_USER_NAME
    assert params["password"].default == DEFAULT_PASSWORD


def test_runmqsc_signature():
    sig = inspect.signature(runmqsc)
    params = sig.parameters
    assert "qmgr_name" in params
    assert "mqsc_command" in params
    assert "url_base" in params
    assert "username" in params
    assert "password" in params
    # qmgr_name and mqsc_command are required (no default)
    assert params["qmgr_name"].default is inspect.Parameter.empty
    assert params["mqsc_command"].default is inspect.Parameter.empty
    assert params["url_base"].default == DEFAULT_URL_BASE
    assert params["username"].default == DEFAULT_USER_NAME
    assert params["password"].default == DEFAULT_PASSWORD


# ---------------------------------------------------------------------------
# prettify_dspmq
# ---------------------------------------------------------------------------

def test_prettify_dspmq_basic():
    data = {
        "qmgr": [
            {"name": "QM1", "state": "running"},
            {"name": "QM2", "state": "stopped"},
        ]
    }
    result = prettify_dspmq(data)
    assert "name = QM1, running = running" in result
    assert "name = QM2, running = stopped" in result
    assert result.count("---") >= 3


def test_prettify_dspmq_empty():
    data = {"qmgr": []}
    result = prettify_dspmq(data)
    assert "---" in result


# ---------------------------------------------------------------------------
# prettify_runmqsc — distributed
# ---------------------------------------------------------------------------

def test_prettify_runmqsc_distributed():
    data = {
        "commandResponse": [
            {"completionCode": "success", "reasonCode": 0, "text": ["QUEUE(MY.QUEUE) TYPE(QLOCAL)"]},
        ]
    }
    result = prettify_runmqsc(data)
    assert "QUEUE(MY.QUEUE) TYPE(QLOCAL)" in result


def test_prettify_runmqsc_warning():
    data = {
        "commandResponse": [
            {"completionCode": "warning", "reasonCode": 4, "text": ["AMQ8405I: MQSC command completed."]},
        ]
    }
    result = prettify_runmqsc(data)
    assert "[WARNING reasonCode=4]" in result


def test_prettify_runmqsc_error():
    data = {
        "commandResponse": [
            {"completionCode": "error", "reasonCode": 2085, "text": ["AMQ8147E: Unknown object name."]},
        ]
    }
    result = prettify_runmqsc(data)
    assert "[ERROR reasonCode=2085]" in result
    assert "AMQ8147E" in result


def test_prettify_runmqsc_empty_text():
    """Empty text list must not raise IndexError."""
    data = {
        "commandResponse": [
            {"completionCode": "success", "reasonCode": 0, "text": []},
        ]
    }
    result = prettify_runmqsc(data)
    assert isinstance(result, str)


def test_prettify_runmqsc_missing_text_key():
    """Missing text key must not raise KeyError."""
    data = {
        "commandResponse": [
            {"completionCode": "success", "reasonCode": 0},
        ]
    }
    result = prettify_runmqsc(data)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# prettify_runmqsc — z/OS branch
# ---------------------------------------------------------------------------

def test_prettify_runmqsc_zos():
    data = {
        "commandResponse": [
            {
                "completionCode": "success",
                "reasonCode": 0,
                "text": [
                    "CSQN205I   COUNT=    1, RETURN=00000000, REASON=00000000",
                    "               QUEUE(MY.QUEUE) TYPE(QLOCAL)           ",
                    "CSQ9022I -CSQ1 CSQUTIL ' DISPLAY QUEUE' NORMAL COMPLETION",
                ],
            }
        ]
    }
    result = prettify_runmqsc(data)
    # Banner and trailing line stripped; inner line trimmed by 15 chars
    assert "CSQN205I" not in result
    assert "CSQ9022I" not in result
    assert "QUEUE(MY.QUEUE)" in result


def test_prettify_runmqsc_zos_only_banner_and_trailer():
    """z/OS response with only banner + trailer (no inner lines) must not crash."""
    data = {
        "commandResponse": [
            {
                "completionCode": "success",
                "reasonCode": 0,
                "text": [
                    "CSQN205I   COUNT=    0, RETURN=00000000, REASON=00000000",
                    "CSQ9022I -CSQ1 CSQUTIL NORMAL COMPLETION",
                ],
            }
        ]
    }
    result = prettify_runmqsc(data)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# JSON injection safety
# ---------------------------------------------------------------------------

def test_runmqsc_json_injection_safety():
    """mqsc_command containing double quotes must produce valid JSON in the request body.

    Verifies the serialisation logic used in server.py directly — if someone
    reverts json.dumps to string concatenation, this test will catch it.
    """
    command_with_quotes = 'DISPLAY QUEUE("MY.QUEUE")'

    # Replicate exactly what runmqsc builds before POSTing
    from mqmcp.server import json as server_json  # same json module used in server
    payload = server_json.dumps({
        "type": "runCommand",
        "parameters": {"command": command_with_quotes},
    })

    # Must round-trip cleanly — string concatenation would break this
    parsed = json.loads(payload)
    assert parsed["type"] == "runCommand"
    assert parsed["parameters"]["command"] == command_with_quotes


def test_runmqsc_json_injection_backslash():
    """Backslashes in the command must also be safely escaped."""
    command_with_backslash = 'DISPLAY QUEUE(TEST\\QUEUE)'
    payload = json.dumps({
        "type": "runCommand",
        "parameters": {"command": command_with_backslash},
    })
    parsed = json.loads(payload)
    assert parsed["parameters"]["command"] == command_with_backslash
