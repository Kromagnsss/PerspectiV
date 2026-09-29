from __future__ import annotations

import argparse
import json
import sys

import httpx


def request(client: httpx.Client, method: str, path: str, *, expected=(200, 201, 204), **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code not in expected:
        raise RuntimeError(f"Keycloak {method} {path}: {response.status_code} {response.text}")
    return response


def ensure_realm(client: httpx.Client, realm: str) -> None:
    response = client.get(f"/admin/realms/{realm}")
    if response.status_code == 404:
        request(client, "POST", "/admin/realms", json={"realm": realm, "enabled": True, "displayName": "PerspectiV"})
    elif response.status_code != 200:
        raise RuntimeError(response.text)


def ensure_role(client: httpx.Client, realm: str, role: str) -> None:
    response = client.get(f"/admin/realms/{realm}/roles/{role}")
    if response.status_code == 404:
        request(client, "POST", f"/admin/realms/{realm}/roles", json={"name": role})


def ensure_client(client: httpx.Client, realm: str, client_id: str, payload: dict) -> str:
    clients = request(client, "GET", f"/admin/realms/{realm}/clients", params={"clientId": client_id}).json()
    if clients:
        uuid = clients[0]["id"]
        request(client, "PUT", f"/admin/realms/{realm}/clients/{uuid}", json={**clients[0], **payload, "clientId": client_id})
        return uuid
    response = request(client, "POST", f"/admin/realms/{realm}/clients", json={"clientId": client_id, **payload})
    location = response.headers["Location"]
    return location.rstrip("/").split("/")[-1]


def ensure_client_scope(client: httpx.Client, realm: str, scope_name: str) -> str:
    scopes = request(client, "GET", f"/admin/realms/{realm}/client-scopes").json()
    existing = next((scope for scope in scopes if scope.get("name") == scope_name), None)
    payload = {
        "name": scope_name,
        "description": f"PerspectiV scope: {scope_name}",
        "protocol": "openid-connect",
        "attributes": {
            "display.on.consent.screen": "true",
            "include.in.token.scope": "true",
        },
    }
    if existing:
        request(
            client,
            "PUT",
            f"/admin/realms/{realm}/client-scopes/{existing['id']}",
            json={**existing, **payload},
        )
        return existing["id"]
    response = request(client, "POST", f"/admin/realms/{realm}/client-scopes", json=payload)
    return response.headers["Location"].rstrip("/").split("/")[-1]


def assign_default_scope(client: httpx.Client, realm: str, client_uuid: str, scope_uuid: str) -> None:
    request(
        client,
        "PUT",
        f"/admin/realms/{realm}/clients/{client_uuid}/default-client-scopes/{scope_uuid}",
        expected=(204, 409),
    )


def ensure_audience_mapper(client: httpx.Client, realm: str, client_uuid: str) -> None:
    path = f"/admin/realms/{realm}/clients/{client_uuid}/protocol-mappers/models"
    mappers = request(client, "GET", path).json()
    if any(mapper.get("name") == "perspectiv-api-audience" for mapper in mappers):
        return
    request(
        client,
        "POST",
        path,
        json={
            "name": "perspectiv-api-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {"included.client.audience": "perspectiv-api", "access.token.claim": "true", "id.token.claim": "false"},
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure un realm Keycloak pour PerspectiV.")
    parser.add_argument("--keycloak-url", required=True)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--admin-user", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--realm", default="perspectiv")
    parser.add_argument("--chatgpt-redirect-uri", default="https://chatgpt.com/connector_platform_oauth_redirect")
    args = parser.parse_args()

    base_url = args.keycloak_url.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=30) as anonymous:
        token_response = request(
            anonymous,
            "POST",
            "/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", "username": args.admin_user, "password": args.admin_password},
        )
    token = token_response.json()["access_token"]
    with httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        ensure_realm(client, args.realm)
        for role in ("admin", "manager", "member"):
            ensure_role(client, args.realm, role)
        ensure_client(client, args.realm, "perspectiv-api", {"enabled": True, "bearerOnly": True, "protocol": "openid-connect"})
        web_uuid = ensure_client(
            client,
            args.realm,
            "perspectiv-web",
            {
                "enabled": True,
                "publicClient": False,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "redirectUris": [f"{args.public_url.rstrip('/')}/*"],
                "webOrigins": [args.public_url.rstrip("/")],
                "protocol": "openid-connect",
            },
        )
        mcp_uuid = ensure_client(
            client,
            args.realm,
            "perspectiv-mcp",
            {
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "redirectUris": [args.chatgpt_redirect_uri],
                "protocol": "openid-connect",
            },
        )
        ensure_audience_mapper(client, args.realm, web_uuid)
        ensure_audience_mapper(client, args.realm, mcp_uuid)
        scope_ids = {
            name: ensure_client_scope(client, args.realm, name)
            for name in ("read", "timesheet:write", "planning:write", "projects:write", "delete", "admin")
        }
        for client_uuid in (web_uuid, mcp_uuid):
            for scope_uuid in scope_ids.values():
                assign_default_scope(client, args.realm, client_uuid, scope_uuid)
        secret = request(client, "GET", f"/admin/realms/{args.realm}/clients/{web_uuid}/client-secret").json()["value"]

    print(json.dumps({
        "issuer": f"{base_url}/realms/{args.realm}",
        "web_client_id": "perspectiv-web",
        "web_client_secret": secret,
        "mcp_client_id": "perspectiv-mcp",
        "mcp_redirect_uri": args.chatgpt_redirect_uri,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
