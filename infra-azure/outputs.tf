output "key_vault_name" {
  description = "Key Vault that holds the runtime secrets."
  value       = azurerm_key_vault.main.name
}

output "runtime_secret_names" {
  description = "Key Vault secret names whose values must be added outside Terraform."
  value       = local.runtime_secret_names
}

output "backend_egress_ip" {
  description = "Public IP the VM uses for outbound traffic. No backend port listens on it."
  value       = azurerm_public_ip.backend.ip_address
}

output "tailscale_backend_hostname" {
  description = "Tailscale hostname used by the participant runner and Prometheus."
  value       = var.tailscale_hostname
}

output "github_actions_variables" {
  description = "Values to copy into GitHub Actions repository variables."
  value = {
    AZURE_CLIENT_ID       = azurerm_user_assigned_identity.github.client_id
    AZURE_TENANT_ID       = data.azurerm_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID = var.subscription_id
    AZURE_RESOURCE_GROUP  = azurerm_resource_group.main.name
    AZURE_VM_NAME         = azurerm_linux_virtual_machine.backend.name
  }
}
