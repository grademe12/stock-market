output "backend_external_ip" {
  description = "Static external IP used by the local participant runners."
  value       = google_compute_address.backend.address
}
output "backend_url" {
  description = "Backend URL allowed only from runner_source_cidr."
  value       = "http://${google_compute_address.backend.address}:${var.backend_port}"
}

output "cloud_sql_connection_name" {
  description = "Instance connection name passed to Cloud SQL Auth Proxy."
  value       = google_sql_database_instance.postgres.connection_name
}

output "backend_service_account" {
  description = "Service account used by the VM and Cloud SQL Auth Proxy."
  value       = google_service_account.backend.email
}

output "github_actions_variables" {
  description = "Values to copy into GitHub Actions repository variables."
  value = {
    GCP_PROJECT_ID                 = var.project_id
    GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOY_SERVICE_ACCOUNT     = google_service_account.github.email
    GCP_REGION                     = var.region
    ARTIFACT_REGISTRY_REPOSITORY   = google_artifact_registry_repository.backend.repository_id
    GCE_INSTANCE                   = google_compute_instance.backend.name
    GCE_ZONE                       = var.zone
    CLOUD_SQL_CONNECTION_NAME      = google_sql_database_instance.postgres.connection_name
  }
}
