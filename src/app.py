"""Stateless MCP server (spec 2026-07-28, Streamable HTTP) for AWS Lambda.

Sits behind an API Gateway HTTP API whose JWT authorizer has already validated
signature, issuer, audience and expiry. This handler adds:
  * scope enforcement per tool
  * RFC 9728 protected-resource metadata
  * the stateless request shape: protocol version + capabilities in _meta,
    no sessions, no initialize handshake
"""
import json
import os
import time

SUPPORTED_VERSIONS = ["2026-07-28"]
SERVER_INFO = {"name": "lambda-mcp-example", "version": "0.1.0"}
AUTHORIZATION_SERVER = os.environ.get("AUTHORIZATION_SERVER", "")
REQUIRED_SCOPE = os.environ.get("REQUIRED_SCOPE", "mcp.read")

META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# Spec error codes -32020..-32099 are reserved for MCP (2026-07-28 changelog)
ERR_HEADER_MISMATCH = -32020
ERR_UNSUPPORTED_VERSION = -32022

TOOLS = {
    "get_server_time": {
        "description": "Return the current UTC time. Read-only.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "scope": REQUIRED_SCOPE,
        "fn": lambda args: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    },
    "echo": {
        "description": "Echo back a message. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "maxLength": 1000}},
            "required": ["message"],
            "additionalProperties": False,
        },
        "scope": REQUIRED_SCOPE,
        "fn": lambda args: args["message"],
    },
}


def _resp(status, body, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    return {"statusCode": status, "headers": h, "body": json.dumps(body)}


def _rpc_error(req_id, code, message, status=200):
    return _resp(status, {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _rpc_ok(req_id, result):
    result.setdefault("resultType", "complete")
    result.setdefault("_meta", {})[META_SERVER_INFO] = SERVER_INFO
    return _resp(200, {"jsonrpc": "2.0", "id": req_id, "result": result})


def _claims(event):
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    ) or {}


def _scopes(claims):
    # Cognito/Okta/most IdPs: "scope" (space-delimited). Entra v2: "scp".
    raw = claims.get("scope") or claims.get("scp") or ""
    if isinstance(raw, list):
        return set(raw)
    return set(str(raw).replace("[", "").replace("]", "").replace(",", " ").split())


def _metadata(event):
    host = event["headers"].get("host", "")
    return _resp(
        200,
        {
            "resource": f"https://{host}/mcp",
            "authorization_servers": [AUTHORIZATION_SERVER],
            "scopes_supported": [REQUIRED_SCOPE],
            "bearer_methods_supported": ["header"],
        },
        {"cache-control": "public, max-age=300"},
    )


def handler(event, context):
    path = event.get("rawPath", "")
    method = event["requestContext"]["http"]["method"]
    event["headers"] = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    if method == "GET" and path.startswith("/.well-known/oauth-protected-resource"):
        return _metadata(event)

    if method != "POST" or not path.endswith("/mcp"):
        return _resp(405, {"error": "method_not_allowed"})

    try:
        msg = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _rpc_error(None, -32700, "Parse error", 400)

    req_id = msg.get("id")
    rpc_method = msg.get("method", "")
    meta = (msg.get("params") or {}).get("_meta") or {}

    # Required Mcp-Method header must match the body (enables gateway-level routing/policy)
    if event["headers"].get("mcp-method") != rpc_method:
        return _rpc_error(req_id, ERR_HEADER_MISMATCH, "Mcp-Method header does not match body", 400)

    # server/discover is the only call allowed without a version in _meta
    if rpc_method == "server/discover":
        return _rpc_ok(
            req_id,
            {
                "supportedVersions": SUPPORTED_VERSIONS,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )

    version = meta.get(META_VERSION)
    if version not in SUPPORTED_VERSIONS:
        return _rpc_error(
            req_id,
            ERR_UNSUPPORTED_VERSION,
            f"Unsupported protocol version; supported: {SUPPORTED_VERSIONS}",
            400,
        )

    scopes = _scopes(_claims(event))

    if rpc_method == "tools/list":
        tools = [
            {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
            for n, t in sorted(TOOLS.items())  # deterministic order for cache hits
            if t["scope"] in scopes
        ]
        return _rpc_ok(req_id, {"tools": tools, "ttlMs": 300000, "cacheScope": "private"})

    if rpc_method == "tools/call":
        params = msg.get("params") or {}
        tool = TOOLS.get(params.get("name"))
        if tool is None:
            return _rpc_error(req_id, -32602, "Unknown tool")
        if tool["scope"] not in scopes:
            # Insufficient scope: HTTP 403 so clients can step up
            return _resp(
                403,
                {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "insufficient_scope"}},
                {"www-authenticate": f'Bearer error="insufficient_scope", scope="{tool["scope"]}"'},
            )
        try:
            text = tool["fn"](params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": str(text)}], "isError": False}
        except Exception as exc:  # tool failure is a tool result, not a protocol error
            result = {"content": [{"type": "text", "text": f"Tool error: {exc}"}], "isError": True}
        # Audit line: structured, picked up by CloudWatch Logs
        print(json.dumps({"audit": "tools/call", "tool": params.get("name"), "sub": _claims(event).get("sub")}))
        return _rpc_ok(req_id, result)

    return _rpc_error(req_id, -32601, "Method not found")
