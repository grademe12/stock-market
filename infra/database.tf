resource "google_sql_database_instance" "postgres" {
  name             = "${local.name}-postgres"
  database_version = "POSTGRES_17"
  region           = var.region

  settings {
    tier              = var.cloud_sql_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled = true
    }

    user_labels = local.labels
  }

  deletion_protection = true

  depends_on = [google_project_service.required]
}
resource "google_sql_database" "application" {
  name     = "stock_market"
  instance = google_sql_database_instance.postgres.name
}
