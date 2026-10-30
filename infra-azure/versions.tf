terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  # Free-trial lifetime is short, so state stays local (gitignored).
  # Move it to an azurerm backend if this environment outlives the trial.

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.12"
    }
  }
}
