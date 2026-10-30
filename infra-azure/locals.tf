locals {
  name = "stock-market-${var.environment}"

  # Key Vault names are global and limited to 24 characters.
  key_vault_name = "stockmarket-${var.environment}-${substr(md5(var.subscription_id), 0, 6)}"

  tags = {
    application = "stock-market"
    environment = var.environment
    managed-by  = "terraform"
  }

  runtime_secret_names = {
    tailscale_auth_key = "tailscale-auth-key"
    postgres_password  = "postgres-password"
    django_secret_key  = "django-secret-key"
  }
}
