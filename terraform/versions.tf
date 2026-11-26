# State is local (terraform.tfstate, git-ignored): a remote backend would need a bucket
# before Terraform exists, and only one person applies this.
terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.10"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
