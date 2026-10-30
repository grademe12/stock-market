variable "subscription_id" {
  description = "Azure subscription ID (az account show --query id -o tsv)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f-]{36}$", var.subscription_id))
    error_message = "subscription_id must be a subscription GUID."
  }
}

variable "location" {
  description = "Azure region for every resource."
  type        = string
  default     = "koreacentral"
}

variable "environment" {
  description = "Environment suffix used in resource names."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "vm_size" {
  description = "VM size for the single backend VM. Avoid burstable B-series for load tests."
  type        = string
  default     = "Standard_D4as_v5"
}

variable "admin_ssh_public_key" {
  description = "SSH public key for the VM admin user. Azure requires one even though no SSH port is open."
  type        = string

  validation {
    condition     = can(regex("^ssh-(ed25519|rsa) ", var.admin_ssh_public_key))
    error_message = "admin_ssh_public_key must be an OpenSSH ed25519 or RSA public key."
  }
}

variable "tailscale_hostname" {
  description = "Stable Tailscale hostname assigned to the backend VM. Kept as stock-market-gce so the mini PC config does not change."
  type        = string
  default     = "stock-market-gce"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.tailscale_hostname))
    error_message = "tailscale_hostname must be a lowercase DNS label."
  }
}

variable "tailscale_tags" {
  description = "Comma-separated Tailscale tags advertised by the backend VM."
  type        = string
  default     = "tag:stock-market-backend"

  validation {
    condition     = startswith(var.tailscale_tags, "tag:")
    error_message = "tailscale_tags must start with tag:."
  }
}

variable "postgres_host" {
  description = "Tailscale IP or MagicDNS name of the local PostgreSQL machine."
  type        = string

  validation {
    condition     = length(trimspace(var.postgres_host)) > 0
    error_message = "postgres_host must not be empty."
  }
}

variable "postgres_port" {
  description = "PostgreSQL port on the local Tailscale machine."
  type        = number
  default     = 5432

  validation {
    condition     = var.postgres_port >= 1 && var.postgres_port <= 65535
    error_message = "postgres_port must be between 1 and 65535."
  }
}

variable "postgres_database" {
  description = "Application database on the local PostgreSQL machine."
  type        = string
  default     = "stock_market"
}

variable "postgres_user" {
  description = "Application user on the local PostgreSQL machine."
  type        = string
  default     = "stock_market"
}

variable "django_allowed_hosts" {
  description = "Comma-separated Host header values accepted by Django over Tailscale."
  type        = string

  validation {
    condition     = length(trimspace(var.django_allowed_hosts)) > 0
    error_message = "django_allowed_hosts must not be empty."
  }
}

variable "github_repository" {
  description = "GitHub repository allowed to deploy through OIDC, for example grademe12/stock-market."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be in owner/name form."
  }
}

variable "github_deploy_ref" {
  description = "Only this Git ref can exchange GitHub OIDC tokens for the deploy identity."
  type        = string
  default     = "refs/heads/main"

  validation {
    condition     = startswith(var.github_deploy_ref, "refs/heads/")
    error_message = "github_deploy_ref must be a branch ref such as refs/heads/main."
  }
}
