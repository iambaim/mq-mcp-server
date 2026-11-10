"""Resolve an FTM MQ connection without exposing credentials to MCP clients."""

import base64
import binascii
import os
import re
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx2


SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
MQ_CA_BUNDLE = "/etc/kagent-ca/ca-bundle.crt"
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


class DiscoveryError(Exception):
    """An FTM connection cannot be resolved safely."""


@dataclass(frozen=True)
class FTMConnection:
    url_base: str
    qmgr_name: str
    password: str = field(repr=False)


def _dns_name(value: object, max_length: int = 253) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and all(len(part) <= 63 and _DNS_LABEL.fullmatch(part) for part in value.split("."))
    )


async def _get_json(client: httpx2.AsyncClient, path: str) -> dict:
    try:
        response = await client.get(path)
    except httpx2.RequestError:
        raise DiscoveryError("Kubernetes API request failed") from None
    if response.status_code != 200:
        raise DiscoveryError(f"Kubernetes API returned HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise DiscoveryError("Invalid Kubernetes API response") from None
    if not isinstance(data, dict):
        raise DiscoveryError("Invalid Kubernetes API response")
    return data


async def resolve_with_client(namespace: str, client: httpx2.AsyncClient) -> FTMConnection:
    """Read one QueueManager, its admitted web Route and its referenced Secret."""
    if not _dns_name(namespace, 63) or "." in namespace:
        raise DiscoveryError("A valid tenant namespace is required")

    qmgrs = await _get_json(client, f"/apis/mq.ibm.com/v1beta1/namespaces/{namespace}/queuemanagers")
    items = qmgrs.get("items")
    if not isinstance(items, list) or len(items) != 1:
        raise DiscoveryError("The tenant namespace must contain exactly one QueueManager")
    qmgr = items[0]
    if not isinstance(qmgr, dict):
        raise DiscoveryError("Invalid QueueManager response")
    try:
        uid = qmgr["metadata"]["uid"]
        qmgr_name = qmgr["spec"]["queueManager"]["name"]
        env = qmgr["spec"]["queueManager"]["env"]
        admin_ui_url = qmgr["status"]["adminUiUrl"]
    except (KeyError, TypeError):
        raise DiscoveryError("QueueManager connection settings are incomplete") from None
    if not isinstance(uid, str) or not uid or not isinstance(qmgr_name, str) or not qmgr_name or not isinstance(env, list):
        raise DiscoveryError("QueueManager connection settings are incomplete")

    refs = []
    for entry in env:
        if isinstance(entry, dict) and entry.get("name") == "MQ_APP_PASSWORD":
            value_from = entry.get("valueFrom")
            refs.append(value_from.get("secretKeyRef") if isinstance(value_from, dict) else None)
    if len(refs) != 1 or not isinstance(refs[0], dict):
        raise DiscoveryError("QueueManager must reference one MQ_APP_PASSWORD Secret")
    secret_name, secret_key = refs[0].get("name"), refs[0].get("key")
    if not _dns_name(secret_name) or not isinstance(secret_key, str) or not secret_key:
        raise DiscoveryError("Invalid MQ_APP_PASSWORD Secret reference")

    try:
        ui = urlsplit(admin_ui_url)
        ui_port = ui.port
    except (ValueError, TypeError, AttributeError):
        raise DiscoveryError("Invalid QueueManager web endpoint") from None
    if ui.scheme != "https" or ui.username is not None or ui.password is not None or ui_port not in (None, 443) or not _dns_name(ui.hostname):
        raise DiscoveryError("Invalid QueueManager web endpoint")

    routes = await _get_json(client, f"/apis/route.openshift.io/v1/namespaces/{namespace}/routes")
    if not isinstance(routes.get("items"), list):
        raise DiscoveryError("Invalid Route list")
    matching = []
    for route in routes["items"]:
        if not isinstance(route, dict):
            continue
        meta, spec = route.get("metadata", {}), route.get("spec", {})
        if not isinstance(meta, dict) or not isinstance(spec, dict):
            continue
        owners = meta.get("ownerReferences", [])
        if not isinstance(owners, list) or not any(isinstance(owner, dict) and owner.get("kind") == "QueueManager" and owner.get("uid") == uid and owner.get("controller") is True for owner in owners):
            continue
        route_port, route_tls = spec.get("port"), spec.get("tls")
        if not isinstance(route_port, dict) or not isinstance(route_tls, dict):
            continue
        if str(route_port.get("targetPort", "")) != "9443" or route_tls.get("termination") not in ("passthrough", "reencrypt"):
            continue
        host = spec.get("host")
        if not _dns_name(host) or host != ui.hostname:
            continue
        status = route.get("status")
        ingress = status.get("ingress", []) if isinstance(status, dict) else []
        if not isinstance(ingress, list) or not any(
            item.get("host") == host and isinstance(item.get("conditions"), list)
            and any(isinstance(c, dict) and c.get("type") == "Admitted" and c.get("status") == "True" for c in item["conditions"])
            for item in ingress if isinstance(item, dict)
        ):
            continue
        matching.append(host)
    if len(matching) != 1:
        raise DiscoveryError("Could not identify exactly one admitted QueueManager web Route")

    secret = await _get_json(client, f"/api/v1/namespaces/{namespace}/secrets/{secret_name}")
    try:
        value = secret["data"][secret_key]
        password = base64.b64decode(value, validate=True).decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error):
        raise DiscoveryError("MQ_APP_PASSWORD Secret key is missing or invalid") from None
    if not password:
        raise DiscoveryError("MQ_APP_PASSWORD Secret key is empty")
    return FTMConnection(url_base=f"https://{matching[0]}/ibmmq/rest/v3/admin/", qmgr_name=qmgr_name, password=password)


async def resolve_ftm(namespace: str) -> FTMConnection:
    """Use the pod service account to resolve a namespace-scoped connection."""
    if not _dns_name(namespace, 63) or "." in namespace:
        raise DiscoveryError("A valid tenant namespace is required")
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "")
    if not host or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise DiscoveryError("Kubernetes service environment is not configured")
    try:
        token = (SERVICE_ACCOUNT / "token").read_text().strip()
        context = ssl.create_default_context(cafile=str(SERVICE_ACCOUNT / "ca.crt"))
    except (OSError, ssl.SSLError):
        raise DiscoveryError("Kubernetes service account credentials are unavailable") from None
    if not token:
        raise DiscoveryError("Kubernetes service account credentials are unavailable")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    async with httpx2.AsyncClient(base_url=f"https://{host}:{port}", headers={"Authorization": f"Bearer {token}"}, verify=context, trust_env=False, follow_redirects=False, timeout=15.0) as client:
        return await resolve_with_client(namespace, client)
