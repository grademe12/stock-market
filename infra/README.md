# GCP infrastructure

Initial infrastructure for running the single-process backend on GCP.

```text
Local participant runners
        |
        | runner_source_cidr -> TCP 8000
        v
Compute Engine VM
  - Django backend (deployment is a later step)
  - Cloud SQL Auth Proxy (deployment is a later step)
        |
        v
Cloud SQL for PostgreSQL
```

Terraform creates only the infrastructure discussed for this stage:

- one custom VPC and regional subnet;
- one static external IP and source-restricted backend firewall rule;
- one Compute Engine VM;
- one public-IP Cloud SQL PostgreSQL instance with no authorized network;
- one VM service account with Cloud SQL Client and telemetry writer roles.

Terraform state is stored in the versioned GCS bucket
`stock-market-505109-terraform-state` under the `infra/dev` prefix.

Cloud SQL Auth Proxy is not a Terraform resource. It will run on the VM and use
the attached service account, so no service-account JSON key is required. The
database user/password and backend/proxy deployment are intentionally deferred.
A separate monitoring VM is not created; the VM service account is prepared for
Cloud Monitoring and Logging.

## Validate

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# Replace runner_source_cidr with the local runner machine's public IP /32.
terraform init
terraform fmt -check
terraform validate
terraform plan
```

The Cloud SQL instance has Terraform deletion protection enabled. No resources
are created until `terraform apply` is run.
