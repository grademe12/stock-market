data "google_compute_image" "debian" {
  family  = "debian-12"
  project = "debian-cloud"
}
resource "google_compute_instance" "backend" {
  name                      = "${local.name}-backend"
  zone                      = var.zone
  machine_type              = var.vm_machine_type
  allow_stopping_for_update = true
  labels                    = local.labels

  boot_disk {
    initialize_params {
      image = data.google_compute_image.debian.self_link
      size  = 20
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.backend.id

    access_config {
      nat_ip = google_compute_address.backend.address
    }
  }

  service_account {
    email  = google_service_account.backend.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin = "TRUE"
  }

  depends_on = [google_project_iam_member.backend]
}
