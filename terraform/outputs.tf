output "mcp_endpoint" {
  description = "Default endpoint (put a custom domain + WAF in front for production)"
  value       = "${aws_apigatewayv2_api.mcp.api_endpoint}/mcp"
}

output "resource_metadata_url" {
  description = "RFC 9728 protected resource metadata (unauthenticated)"
  value       = "${aws_apigatewayv2_api.mcp.api_endpoint}/.well-known/oauth-protected-resource"
}

output "lambda_function_name" {
  value = aws_lambda_function.mcp.function_name
}
