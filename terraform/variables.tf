variable "name" {
  type        = string
  default     = "mcp-server"
  description = "Prefix for all resource names"
}

variable "jwt_issuer" {
  type        = string
  description = "OIDC issuer URL, e.g. https://login.microsoftonline.com/<tenant-id>/v2.0 or a Cognito user pool URL"
}

variable "jwt_audience" {
  type        = string
  description = "Expected `aud` claim (the API / resource identifier your IdP issues tokens for)"
}

variable "authorization_server" {
  type        = string
  default     = ""
  description = "Authorization server issuer advertised in the RFC 9728 metadata. Defaults to jwt_issuer."
}

variable "required_scope" {
  type        = string
  default     = "mcp.read"
  description = "Scope required to list and call tools"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "throttle_burst_limit" {
  type    = number
  default = 50
}

variable "throttle_rate_limit" {
  type    = number
  default = 25
}

variable "tags" {
  type    = map(string)
  default = {}
}
