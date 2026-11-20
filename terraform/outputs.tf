output "lake_uri" {
  description = "Value for LAKE_URI"
  value       = google_storage_bucket.lake.url
}

output "gold_dataset" {
  value = "${var.project_id}.${google_bigquery_dataset.gold.dataset_id}"
}

output "service_account" {
  value = google_service_account.pipeline.email
}
