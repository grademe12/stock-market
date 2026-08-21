resource "google_compute_network" "main" {
  name                    = "${local.name}-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.required]
}
resource "google_compute_subnetwork" "backend" {
  name          = "${local.name}-subnet"
  region        = var.region
  network       = google_compute_network.main.id
  ip_cidr_range = "10.10.0.0/24"
}

resource "google_compute_address" "backend" {
  name   = "${local.name}-backend-ip"
  region = var.region

  depends_on = [google_project_service.required]
}

resource "google_compute_firewall" "runner_to_backend" {
  name      = "${local.name}-runner-to-backend"
  network   = google_compute_network.main.name
  direction = "INGRESS"

  source_ranges           = [var.runner_source_cidr]
  target_service_accounts = [google_service_account.backend.email]

  allow {
    protocol = "tcp"
    ports    = [tostring(var.backend_port)]
  }
}
