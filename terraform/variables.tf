variable "project_id" {
  description = "GCP project of the course (from the lecturer)"
  type        = string
}

variable "region" {
  description = "Location of the bucket and the BigQuery dataset (must be the same for both)"
  type        = string
  default     = "europe-west6" # Zurich
}

variable "bucket_name" {
  description = "Globally unique name of the lake bucket (raw/, bronze/, silver/)"
  type        = string
}
