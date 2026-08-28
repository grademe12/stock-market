variable "project_id" {
  description = "GCP project ID."
  type        = string

  validation {
    condition     = length(trimspace(var.project_id)) > 0
    error_message = "project_id must not be empty."
  }
}

variable "region" {
  description = "GCP region for the subnet and Cloud SQL."
  type        = string
  default     = "asia-northeast3"
}

variable "zone" {
  description = "GCP zone for the backend VM."
  type        = string
  default     = "asia-northeast3-a"
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

variable "backend_image_family" {
  description = "Custom Compute Engine image family with Docker, Tailscale, and gcloud installed."
  type        = string
  default     = "stock-market-base"

  validation {
    condition     = length(trimspace(var.backend_image_family)) > 0
    error_message = "backend_image_family must not be empty."
  }
}

variable "backend_image_project" {
  description = "Project containing the custom image family. Null uses project_id."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.backend_image_project == null || length(trimspace(var.backend_image_project)) > 0
    error_message = "backend_image_project must be null or a non-empty project ID."
  }
}

variable "vm_machine_type" {
  description = "Machine type for the single backend VM."
  type        = string
  default     = "e2-medium"
}

variable "tailscale_hostname" {
  description = "Stable Tailscale hostname assigned to the backend VM."
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
  description = "GitHub repository allowed to deploy through Workload Identity Federation, for example grademe12/stock-market."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be in owner/name form."
  }
}

variable "github_deploy_ref" {
  description = "Only this Git ref can exchange GitHub OIDC tokens for the deploy service account."
  type        = string
  default     = "refs/heads/main"

  validation {
    condition     = startswith(var.github_deploy_ref, "refs/heads/")
    error_message = "github_deploy_ref must be a branch ref such as refs/heads/main."
  }
}
