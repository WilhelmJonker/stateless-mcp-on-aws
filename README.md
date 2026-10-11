# stateless-mcp-on-aws

A minimal, stateless [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server on AWS, written against the **2026-07-28** spec revision. It is an API Gateway HTTP API with an OIDC JWT authorizer in front of one Python Lambda, deployed with Terraform.

It ships two placeholder tools (`echo` and `get_server_time`) and no backend. Treat it as a starting skeleton for exposing your own tools over MCP, not as a finished service.

## Architecture

```
MCP client --HTTPS--> API Gateway (HTTP API) --> Lambda (src/app.py)
                         |
                         +-- JWT authorizer: validates signature, issuer,
                             audience and expiry before the Lambda runs
```

## What it does

- **Stateless.** No sessions and no `initialize` handshake. Every request carries the protocol version in `_meta`.
- **Routable.** Requires an `Mcp-Method` header that matches the JSON-RPC body, so gateways can apply policy on headers alone.
- **Discoverable.** Implements `server/discover`.
- **Cacheable.** `tools/list` returns tools in a deterministic order with `ttlMs` and `cacheScope`.
- **Scoped.** Each tool declares a required scope. A call without it gets a 403 with `insufficient_scope`.
- **Metadata routes.** Serves RFC 9728 protected-resource metadata at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/mcp`, without authentication.
- **Auditable.** Writes a structured audit line per tool call, plus API access logs, to CloudWatch Logs. X-Ray tracing is on.

## Layout

```
.
├── README.md
├── .gitignore
├── test_handler.py              # local tests, no AWS account needed
├── src/
│   └── app.py                   # the MCP handler (Lambda entry point)
└── terraform/
    ├── main.tf                  # HTTP API, JWT authorizer, Lambda, IAM, logs
    ├── variables.tf
    ├── outputs.tf
    ├── versions.tf
    └── terraform.tfvars.example
```

Keep `src/` next to `terraform/`: Terraform zips `../src` to build the Lambda package.

## Prerequisites

- Terraform 1.6 or newer
- AWS credentials that can create API Gateway APIs, Lambda functions, IAM roles and CloudWatch log groups
- An OIDC identity provider (Entra ID, Okta, Cognito or similar) that issues JWTs for your API audience and includes a scope such as `mcp.read`

## Deploy

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: set jwt_issuer and jwt_audience
terraform init
terraform apply
```

Commit the `.terraform.lock.hcl` file that `terraform init` creates. The `mcp_endpoint` output is the URL to give your MCP client.

### Variables

| Name | Default | Description |
| --- | --- | --- |
| `jwt_issuer` | required | OIDC issuer URL, for example `https://login.microsoftonline.com/<tenant-id>/v2.0` |
| `jwt_audience` | required | Expected `aud` claim of the access token |
| `authorization_server` | `jwt_issuer` | Authorization server advertised in the RFC 9728 metadata |
| `required_scope` | `mcp.read` | Scope required to list and call the placeholder tools |
| `name` | `mcp-server` | Prefix for resource names |
| `log_retention_days` | `30` | CloudWatch log retention |
| `throttle_burst_limit` | `50` | API Gateway burst limit |
| `throttle_rate_limit` | `25` | API Gateway steady-state rate limit |
| `tags` | `{}` | Tags applied to resources that support them |

## Try it

Get an access token from your identity provider, then:

```bash
MCP_ENDPOINT="$(terraform output -raw mcp_endpoint)"

# Discover supported versions and capabilities
curl -s -X POST "$MCP_ENDPOINT" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Mcp-Method: server/discover" \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{}}'

# List the tools you are allowed to call
curl -s -X POST "$MCP_ENDPOINT" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Mcp-Method: tools/list" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'
```

## Run the tests

```bash
python3 test_handler.py
```

The tests call the handler directly with sample API Gateway events. They cover discovery, scope-filtered tool listing, tool calls, insufficient scope, a header mismatch, an unsupported version and both metadata routes.

## Add your own tools

Tools live in the `TOOLS` dictionary in `src/app.py`. Each entry has a `description`, an `inputSchema`, a required `scope` and a function `fn` that takes the arguments and returns text.

The Lambda calls any backend with its own IAM role, so the backend sees the service rather than the user. If a user should see only their own data, enforce that in the tool, for example by filtering on the `sub` claim. Never forward the incoming token to a downstream API as-is.

## Status and known gaps

The handler is covered by the local tests. The Terraform is format-checked but has not been applied against a live AWS account, so run `terraform plan` and review it before you rely on it.

Before production:

1. **Missing metadata pointer.** API Gateway's JWT authorizer returns a 401 without the `resource_metadata` pointer in `WWW-Authenticate`. Clients that need it fall back to probing the well-known URL. Use a Lambda authorizer or a gateway that emits the header for full spec behavior.
2. **Default URL.** Put a custom domain, AWS WAF and a request-size limit in front of the default `execute-api` endpoint.
3. **Claim shapes.** Check your identity provider. Entra uses `scp` for scopes, and Cognito resource-server scopes look like `server/scope`.
4. **Unchecked `Mcp-Name`.** The handler validates `Mcp-Method` but not the `Mcp-Name` header the spec also requires.
