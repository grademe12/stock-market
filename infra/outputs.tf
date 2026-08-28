output "backend_service_account" {
  description = "Service account used by the backend VM."
  value       = google_service_account.backend.email
}

output "runtime_secret_names" {
  description = "Secret Manager names whose values must be added outside Terraform."
  value = {
    for key, secret in google_secret_manager_secret.runtime :
    key => secret.secret_id
  }
}

output "tailscale_backend_hostname" {
  description = "Tailscale hostname used by the participant runner."
  value       = var.tailscale_hostname
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
  }
}
