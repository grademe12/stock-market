resource "azurerm_linux_virtual_machine" "backend" {
  name                  = "${local.name}-backend"
  location              = azurerm_resource_group.main.location
  resource_group_name   = azurerm_resource_group.main.name
  size                  = var.vm_size
  admin_username        = "azureuser"
  network_interface_ids = [azurerm_network_interface.backend.id]
  tags                  = local.tags

  disable_password_authentication = true

  admin_ssh_key {
    username   = "azureuser"
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  identity {
    type = "SystemAssigned"
  }

  # custom_data only runs on first boot, and changing it replaces the VM
  # (new disk, new Tailscale node). Roll out bootstrap changes deliberately
  # with terraform apply -replace=azurerm_linux_virtual_machine.backend.
  lifecycle {
    ignore_changes = [custom_data]
  }

  # cloud-init installs Docker and Tailscale, writes the non-secret settings,
  # and enables a boot-time service that reads Key Vault and writes backend.env.
  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    bootstrap_script = file("${path.module}/scripts/bootstrap-vm.sh")
    bootstrap_config = join("\n", [
      "KEY_VAULT_NAME=${local.key_vault_name}",
      "TAILSCALE_HOSTNAME=${var.tailscale_hostname}",
      "TAILSCALE_TAGS=${var.tailscale_tags}",
      "TAILSCALE_SECRET=${local.runtime_secret_names.tailscale_auth_key}",
      "POSTGRES_SECRET=${local.runtime_secret_names.postgres_password}",
      "DJANGO_SECRET=${local.runtime_secret_names.django_secret_key}",
      "POSTGRES_HOST=${var.postgres_host}",
      "POSTGRES_PORT=${var.postgres_port}",
      "POSTGRES_DATABASE=${var.postgres_database}",
      "POSTGRES_USER=${var.postgres_user}",
      "DJANGO_ALLOWED_HOSTS=${var.django_allowed_hosts}",
    ])
  }))
}
