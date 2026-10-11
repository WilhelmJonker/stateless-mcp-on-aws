import json
import os

os.environ["AUTHORIZATION_SERVER"] = "https://idp.example.com"
os.environ["REQUIRED_SCOPE"] = "mcp.read"
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from app import handler  # noqa: E402

V = "io.modelcontextprotocol/protocolVersion"


def ev(method, path, body=None, headers=None, scope="mcp.read"):
    h = {"host": "abc.execute-api.eu-central-1.amazonaws.com"}
    h.update(headers or {})
    return {
        "rawPath": path,
        "headers": h,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": "u1", "scope": scope}}},
        },
    }


def call(rpc_method, params=None, id_=1, hdr=None, scope="mcp.read"):
    params = params if params is not None else {"_meta": {V: "2026-07-28"}}
    body = {"jsonrpc": "2.0", "id": id_, "method": rpc_method, "params": params}
    h = {"mcp-method": rpc_method}
    h.update(hdr or {})
    r = handler(ev("POST", "/mcp", body, h, scope), None)
    return r["statusCode"], json.loads(r["body"])


# discover (no version needed)
s, b = call("server/discover", {})
assert s == 200 and b["result"]["supportedVersions"] == ["2026-07-28"], b

# list
s, b = call("tools/list")
assert s == 200 and [t["name"] for t in b["result"]["tools"]] == ["echo", "get_server_time"], b
assert b["result"]["ttlMs"] == 300000 and b["result"]["resultType"] == "complete"

# list with no matching scope -> no tools
s, b = call("tools/list", scope="other")
assert b["result"]["tools"] == [], b

# call
s, b = call("tools/call", {"_meta": {V: "2026-07-28"}, "name": "echo", "arguments": {"message": "hi"}})
assert s == 200 and b["result"]["content"][0]["text"] == "hi", b

# insufficient scope
s, b = call("tools/call", {"_meta": {V: "2026-07-28"}, "name": "echo", "arguments": {"message": "x"}}, scope="other")
assert s == 403, (s, b)

# header mismatch
s, b = call("tools/list", hdr={"mcp-method": "tools/call"})
assert s == 400 and b["error"]["code"] == -32020, b

# bad version
s, b = call("tools/list", {"_meta": {V: "2025-11-25"}})
assert s == 400 and b["error"]["code"] == -32022, b

# metadata, both paths
for p in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
    r = handler(ev("GET", p), None)
    m = json.loads(r["body"])
    assert r["statusCode"] == 200 and m["authorization_servers"] == ["https://idp.example.com"], m
    assert m["resource"].endswith("/mcp")

print("ALL TESTS PASSED")
