locals {
  runtime_secret_ids = {
    tailscale_auth_key = "${local.name}-tailscale-auth-key"
    postgres_password  = "${local.name}-postgres-password"
    django_secret_key  = "${local.name}-django-secret-key"
  }
}

resource "google_secret_manager_secret" "runtime" {
  for_each = local.runtime_secret_ids

  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "backend_accessor" {
  for_each = google_secret_manager_secret.runtime

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}
