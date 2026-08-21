resource "google_artifact_registry_repository" "backend" {
  location      = var.region
  repository_id = local.name
  description   = "Backend images for the single VM deploy."
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.required]
}
