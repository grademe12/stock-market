terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  backend "gcs" {
    bucket = "stock-market-505109-terraform-state"
    prefix = "infra/dev"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.43"
    }
  }
}
