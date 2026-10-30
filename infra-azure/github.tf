# GitHub Actions signs in as this identity with an OIDC token; no client secret exists.
resource "azurerm_user_assigned_identity" "github" {
  name                = "${local.name}-github-deploy"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "github" {
  name                      = "github-${replace(var.github_deploy_ref, "/", "-")}"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.github_repository}:ref:${var.github_deploy_ref}"
}

# Run Command replaces the IAP SSH step: the deploy job runs remote-deploy.sh
# through the VM agent, so no SSH port is needed. The role is scoped to the VM only.
resource "azurerm_role_assignment" "github_vm_contributor" {
  scope                = azurerm_linux_virtual_machine.backend.id
  role_definition_name = "Virtual Machine Contributor"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}
