import asyncio
import base64
import copy
import inspect
import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest

from mqmcp import ftm, server


@pytest.fixture
def resources():
    qmgr = {
        "metadata": {"name": "ftm-mq", "uid": "qmgr-uid"},
        "spec": {"queueManager": {"name": "FTMQM", "env": [{
            "name": "MQ_APP_PASSWORD",
            "valueFrom": {"secretKeyRef": {"name": "ftm-ftm-app-secret", "key": "MQ_APP_PASSWORD"}},
        }]}},
        "status": {"adminUiUrl": "https://mq.example.test/ibmmq/console/"},
    }
    route = {
        "metadata": {"ownerReferences": [{"kind": "QueueManager", "uid": "qmgr-uid", "controller": True}]},
        "spec": {"host": "mq.example.test", "port": {"targetPort": 9443}, "tls": {"termination": "passthrough"}},
        "status": {"ingress": [{"host": "mq.example.test", "conditions": [{"type": "Admitted", "status": "True"}]}]},
    }
    return {"qmgrs": {"items": [qmgr]}, "routes": {"items": [route]}, "secret": {"data": {"MQ_APP_PASSWORD": base64.b64encode(b"tenant-password").decode()}}}


def resolve(resources, namespace="ftm-ach-dev"):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/queuemanagers"):
            return httpx2.Response(200, json=resources["qmgrs"])
        if request.url.path.endswith("/routes"):
            return httpx2.Response(200, json=resources["routes"])
        if request.url.path.endswith("/secrets/ftm-ftm-app-secret"):
            return httpx2.Response(200, json=resources["secret"])
        return httpx2.Response(404)

    async def run():
        async with httpx2.AsyncClient(base_url="https://kubernetes.test", transport=httpx2.MockTransport(handle)) as client:
            return await ftm.resolve_with_client(namespace, client)

    return asyncio.run(run()), paths


def test_resolve_uses_one_owned_admitted_web_route_and_named_secret(resources):
    result, paths = resolve(resources)
    assert result.url_base == "https://mq.example.test/ibmmq/rest/v3/admin/"
    assert result.qmgr_name == "FTMQM"
    assert result.password == "tenant-password"
    assert "tenant-password" not in repr(result)
    assert paths == [
        "/apis/mq.ibm.com/v1beta1/namespaces/ftm-ach-dev/queuemanagers",
        "/apis/route.openshift.io/v1/namespaces/ftm-ach-dev/routes",
        "/api/v1/namespaces/ftm-ach-dev/secrets/ftm-ftm-app-secret",
    ]


@pytest.mark.parametrize("namespace", ["", "../ftm", "ftm/other", "ftm.test", "-ftm", "a" * 64])
def test_reject_invalid_namespace_before_any_request(resources, namespace):
    with pytest.raises(ftm.DiscoveryError, match="namespace"):
        resolve(resources, namespace)


def test_reject_ambiguous_queue_managers(resources):
    resources["qmgrs"]["items"].append(copy.deepcopy(resources["qmgrs"]["items"][0]))
    with pytest.raises(ftm.DiscoveryError, match="exactly one QueueManager"):
        resolve(resources)


@pytest.mark.parametrize("mutation", [
    lambda r: r["routes"]["items"][0]["metadata"]["ownerReferences"][0].update(uid="other"),
    lambda r: r["routes"]["items"][0]["metadata"]["ownerReferences"][0].update(controller=False),
    lambda r: r["routes"]["items"][0]["spec"]["port"].update(targetPort=1414),
    lambda r: r["routes"]["items"][0]["spec"]["tls"].update(termination="edge"),
    lambda r: r["routes"]["items"][0]["spec"].update(port=None),
    lambda r: r["routes"]["items"][0].update(status=None),
    lambda r: r["routes"]["items"][0]["spec"].update(host="other.example.test"),
    lambda r: r["routes"]["items"][0]["status"]["ingress"][0]["conditions"][0].update(status="False"),
    lambda r: r["routes"]["items"].append(copy.deepcopy(r["routes"]["items"][0])),
])
def test_reject_unsafe_or_ambiguous_web_route(resources, mutation):
    mutation(resources)
    with pytest.raises(ftm.DiscoveryError, match="Route"):
        resolve(resources)


def test_invalid_route_does_not_read_secret(resources):
    resources["routes"]["items"][0]["spec"]["host"] = "attacker.example.test"
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/queuemanagers"):
            return httpx2.Response(200, json=resources["qmgrs"])
        if request.url.path.endswith("/routes"):
            return httpx2.Response(200, json=resources["routes"])
        pytest.fail("Secret must not be read for an invalid endpoint")

    async def run():
        async with httpx2.AsyncClient(base_url="https://kubernetes.test", transport=httpx2.MockTransport(handle)) as client:
            await ftm.resolve_with_client("ftm-ach-dev", client)

    with pytest.raises(ftm.DiscoveryError, match="Route"):
        asyncio.run(run())
    assert len(paths) == 2


@pytest.mark.parametrize("url", ["http://mq.example.test/", "https://attacker@mq.example.test/", "https://mq.example.test:8443/", "https://other.example.test/"])
def test_reject_invalid_or_mismatched_ui_host(resources, url):
    resources["qmgrs"]["items"][0]["status"]["adminUiUrl"] = url
    with pytest.raises(ftm.DiscoveryError):
        resolve(resources)


def test_reject_bad_secret_reference_and_missing_value(resources):
    ref = resources["qmgrs"]["items"][0]["spec"]["queueManager"]["env"][0]["valueFrom"]["secretKeyRef"]
    ref["name"] = "../other"
    with pytest.raises(ftm.DiscoveryError, match="Secret reference"):
        resolve(resources)
    ref["name"] = "ftm-ftm-app-secret"
    resources["secret"]["data"]["MQ_APP_PASSWORD"] = "not base64"
    with pytest.raises(ftm.DiscoveryError, match="missing or invalid"):
        resolve(resources)


def test_reject_missing_secret_reference(resources):
    resources["qmgrs"]["items"][0]["spec"]["queueManager"]["env"][0]["valueFrom"] = None
    with pytest.raises(ftm.DiscoveryError, match="MQ_APP_PASSWORD Secret"):
        resolve(resources)


def test_api_errors_do_not_expose_response_body():
    async def run():
        async with httpx2.AsyncClient(base_url="https://kubernetes.test", transport=httpx2.MockTransport(lambda req: httpx2.Response(403, text="sensitive body"))) as client:
            await ftm.resolve_with_client("ftm-ach-dev", client)

    with pytest.raises(ftm.DiscoveryError) as err:
        asyncio.run(run())
    assert "403" in str(err.value)
    assert "sensitive body" not in str(err.value)


def test_tenant_tools_have_no_endpoint_or_credential_arguments():
    assert list(inspect.signature(server.ftm_dspmq).parameters) == ["namespace"]
    assert list(inspect.signature(server.ftm_runmqsc).parameters) == ["namespace", "mqsc_command"]


def test_mcp_rejects_tenant_overrides_and_advertises_closed_schema():
    tools = asyncio.run(server.mcp.list_tools())
    for tool in tools:
        if tool.name in ("ftm_dspmq", "ftm_runmqsc"):
            assert tool.input_schema["additionalProperties"] is False
    for override in ({"url_base": "https://attacker.example"}, {"username": "admin"}, {"password": "fake"}, {"qmgr_name": "other"}):
        with pytest.raises(server.ToolError, match="Unsupported FTM tenant tool arguments"):
            asyncio.run(server.mcp.call_tool("ftm_dspmq", {"namespace": "ftm-ach-dev", **override}))


def test_standalone_tools_keep_explicit_connections_and_commands(monkeypatch):
    class FakeClient:
        async def get(self, url, **kwargs):
            assert url == "https://standalone.example/ibmmq/rest/v3/admin/qmgr/"
            return httpx2.Response(200, json={"qmgr": [{"name": "QM1", "state": "running"}]}, request=httpx2.Request("GET", url))

        async def post(self, url, **kwargs):
            assert url == "https://standalone.example/ibmmq/rest/v3/admin/action/qmgr/QM1/mqsc"
            assert json.loads(kwargs["content"])["parameters"]["command"] == "ALTER QMGR DESCR('example')"
            return httpx2.Response(200, json={"commandResponse": [{"completionCode": 0, "text": "OK"}]}, request=httpx2.Request("POST", url))

    def get_client(url, username, password):
        assert (url, username, password) == ("https://standalone.example/ibmmq/rest/v3/admin/", "user", "password")
        return FakeClient()

    monkeypatch.setattr(server, "_get_client", get_client)
    args = {"url_base": "https://standalone.example/ibmmq/rest/v3/admin/", "username": "user", "password": "password"}
    assert "QM1" in asyncio.run(server.dspmq(**args))
    assert "OK" in asyncio.run(server.runmqsc("QM1", "ALTER QMGR DESCR('example')", **args))


def test_tenant_calls_verify_tls_and_use_rotated_passwords(monkeypatch):
    passwords = iter(["first-password", "second-password"])
    clients = []
    tls = ssl.create_default_context()

    async def fake_resolve(namespace):
        assert namespace == "ftm-ach-dev"
        return ftm.FTMConnection(url_base="https://mq.example.test/ibmmq/rest/v3/admin/", qmgr_name="FTMQM", password=next(passwords))

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            clients.append(self)

        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

        async def get(self, url, **kwargs):
            assert url == "https://mq.example.test/ibmmq/rest/v3/admin/qmgr/"
            return httpx2.Response(200, json={"qmgr": [{"name": "FTMQM", "state": "running"}]}, request=httpx2.Request("GET", url))

    monkeypatch.setattr(server, "resolve_ftm", fake_resolve)
    monkeypatch.setattr(server.ssl, "create_default_context", lambda **kwargs: tls)
    monkeypatch.setattr(server.httpx2, "AsyncClient", FakeClient)
    assert "FTMQM" in asyncio.run(server.ftm_dspmq("ftm-ach-dev"))
    assert "FTMQM" in asyncio.run(server.ftm_dspmq("ftm-ach-dev"))
    assert len(clients) == 2
    assert all(c.kwargs["verify"] is tls and c.kwargs["follow_redirects"] is False and c.kwargs["trust_env"] is False for c in clients)
    assert clients[0].kwargs["auth"]._auth_header != clients[1].kwargs["auth"]._auth_header


def test_tenant_runmqsc_uses_discovered_target_and_json(monkeypatch):
    tls = ssl.create_default_context()

    async def fake_resolve(namespace):
        return ftm.FTMConnection(url_base="https://mq.example.test/ibmmq/rest/v3/admin/", qmgr_name="FTMQM", password="secret")

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["verify"] is tls
            assert kwargs["follow_redirects"] is False

        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

        async def post(self, url, **kwargs):
            assert url == "https://mq.example.test/ibmmq/rest/v3/admin/action/qmgr/FTMQM/mqsc"
            assert server.json.loads(kwargs["content"])["parameters"]["command"] == "DISPLAY QMGR"
            return httpx2.Response(200, json={"commandResponse": [{"completionCode": 0, "text": "QMNAME(FTMQM)"}]}, request=httpx2.Request("POST", url))

    monkeypatch.setattr(server, "resolve_ftm", fake_resolve)
    monkeypatch.setattr(server.ssl, "create_default_context", lambda **kwargs: tls)
    monkeypatch.setattr(server.httpx2, "AsyncClient", FakeClient)
    assert "QMNAME(FTMQM)" in asyncio.run(server.ftm_runmqsc("ftm-ach-dev", "DISPLAY QMGR"))


def test_invalid_tenant_ca_fails_before_discovery(monkeypatch):
    def fail(**kwargs):
        raise ssl.SSLError("invalid bundle")

    monkeypatch.setattr(server.ssl, "create_default_context", fail)
    assert asyncio.run(server.ftm_dspmq("ftm-ach-dev")) == "MQ trust bundle is unavailable or invalid"


@pytest.mark.parametrize("command", [
    "", "DELETE QLOCAL(TEST)", "RESET QSTATS", "PING QMGR", "DISPLAYX QMGR",
    "DISPLAY QMGR\nDELETE QLOCAL(TEST)", "DISPLAY QMGR; DELETE QLOCAL(TEST)",
    "DISPLAY QMGR\rDELETE QLOCAL(TEST)", "DISPLAY QMGR\x00DELETE QLOCAL(TEST)",
])
def test_tenant_mqsc_rejects_mutation_and_command_chaining_before_discovery(monkeypatch, command):
    async def fail(*args):
        raise AssertionError("discovery must not run")

    monkeypatch.setattr(server, "resolve_ftm", fail)
    assert asyncio.run(server.ftm_runmqsc("ftm-ach-dev", command)) == "Only single-line DISPLAY MQSC commands are allowed in tenant mode"


def test_tenant_tls_rejects_untrusted_certificate_before_sending_credentials(monkeypatch, tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("openssl is required to generate test certificates")
    certs = []
    for name in ("mq", "other"):
        cert, key = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        certs.append((cert, key))

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.headers.get("Authorization"))
            body = json.dumps({"qmgr": [{"name": "FTMQM", "state": "running"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args): pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*map(str, certs[0]))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        async def fake_resolve(namespace):
            return ftm.FTMConnection(url_base=f"https://localhost:{httpd.server_port}/ibmmq/rest/v3/admin/", qmgr_name="FTMQM", password="tenant-secret")

        monkeypatch.setattr(server, "resolve_ftm", fake_resolve)
        monkeypatch.setenv("MQMCP_CA_BUNDLE", str(certs[0][0]))
        assert "FTMQM" in asyncio.run(server.ftm_dspmq("ftm-ach-dev"))
        assert len(requests) == 1

        monkeypatch.setenv("MQMCP_CA_BUNDLE", str(certs[1][0]))
        result = asyncio.run(server.ftm_dspmq("ftm-ach-dev"))
        assert result == "Network or TLS error: could not reach mqweb"
        assert "tenant-secret" not in result
        assert len(requests) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
