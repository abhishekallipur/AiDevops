# Terraform notes

Terraform workflow: terraform fmt, terraform init, terraform validate, terraform plan, and then terraform apply only after review and approval. Do not hard-code AWS credentials. Use least-privilege IAM roles or an approved credentials mechanism. Do not assume a resource should be public; network exposure must follow the project requirements.
