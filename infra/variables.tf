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

variable "runner_source_cidr" {
  description = "Public IP CIDR of the local runner machine, for example 203.0.113.10/32."
  type        = string

  validation {
    condition     = can(cidrhost(var.runner_source_cidr, 0)) && endswith(var.runner_source_cidr, "/32")
    error_message = "runner_source_cidr must be a single IPv4 address using /32."
  }
}

variable "backend_port" {
  description = "Backend port exposed only to runner_source_cidr."
  type        = number
  default     = 8000

  validation {
    condition     = var.backend_port >= 1 && var.backend_port <= 65535
    error_message = "backend_port must be between 1 and 65535."
  }
}

variable "vm_machine_type" {
  description = "Machine type for the single backend VM."
  type        = string
  default     = "e2-medium"
}

variable "cloud_sql_tier" {
  description = "Machine tier for the development Cloud SQL instance."
  type        = string
  default     = "db-f1-micro"
}

variable "cloud_sql_user" {
  description = "Application database user created in Cloud SQL."
  type        = string
  default     = "stock_market"
}

variable "cloud_sql_password" {
  description = "Password for the Cloud SQL application user. Store only in terraform.tfvars."
  type        = string
  sensitive   = true
}

variable "github_repository" {
  description = "GitHub repository allowed to deploy through Workload Identity Federation, for example grademe12/stock-market."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be in owner/name form."
  }
}
