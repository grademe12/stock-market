resource "google_service_account" "backend" {
  account_id   = "stock-market-${var.environment}-vm"
  display_name = "Stock market backend VM (${var.environment})"

  depends_on = [google_project_service.required]
}
resource "google_project_iam_member" "backend" {
  for_each = toset([
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.backend.email}"
}
