locals {
  name = "stock-market-${var.environment}"

  labels = {
    application = "stock-market"
    environment = var.environment
    managed-by  = "terraform"
  }

  required_services = toset([
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "iap.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "oslogin.googleapis.com",
    "secretmanager.googleapis.com",
  ])
}
