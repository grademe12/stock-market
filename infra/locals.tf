locals {
  name = "stock-market-${var.environment}"

  labels = {
    application = "stock-market"
    environment = var.environment
    managed-by  = "terraform"
  }

  required_services = toset([
    "compute.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "sqladmin.googleapis.com",
  ])
}
