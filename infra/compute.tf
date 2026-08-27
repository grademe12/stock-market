data "google_compute_image" "backend" {
  family  = var.backend_image_family
  project = coalesce(var.backend_image_project, var.project_id)
}

resource "google_compute_instance" "backend" {
  name                      = "${local.name}-backend"
  zone                      = var.zone
  machine_type              = var.vm_machine_type
  allow_stopping_for_update = true
  labels                    = local.labels

  boot_disk {
    initialize_params {
      image = data.google_compute_image.backend.self_link
      size  = 20
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.backend.id

    # Tailscale initiates outbound and carries runner/API and PostgreSQL traffic.
    # The ephemeral public IP is only for egress; no public backend ingress exists.
    access_config {}
  }

  service_account {
    email  = google_service_account.backend.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin                    = "TRUE"
    startup-script                    = file("${path.module}/scripts/bootstrap-vm.sh")
    stock-market-project-id           = var.project_id
    stock-market-tailscale-hostname   = var.tailscale_hostname
    stock-market-tailscale-tags       = var.tailscale_tags
    stock-market-tailscale-secret     = google_secret_manager_secret.runtime["tailscale_auth_key"].secret_id
    stock-market-postgres-secret      = google_secret_manager_secret.runtime["postgres_password"].secret_id
    stock-market-django-secret        = google_secret_manager_secret.runtime["django_secret_key"].secret_id
    stock-market-postgres-host        = var.postgres_host
    stock-market-postgres-port        = tostring(var.postgres_port)
    stock-market-postgres-database    = var.postgres_database
    stock-market-postgres-user        = var.postgres_user
    stock-market-django-allowed-hosts = var.django_allowed_hosts
  }

  depends_on = [
    google_project_iam_member.backend,
    google_secret_manager_secret_iam_member.backend_accessor,
  ]
}
