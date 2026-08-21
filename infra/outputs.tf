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
