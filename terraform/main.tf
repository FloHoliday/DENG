resource "google_project_service" "apis" {
  for_each = toset(["storage.googleapis.com", "bigquery.googleapis.com", "iam.googleapis.com"])

  service            = each.value
  disable_on_destroy = false
}

# The lake: raw JSON and the bronze and silver Delta tables.
resource "google_storage_bucket" "lake" {
  name                        = var.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # raw/ is the only copy of the source data: versioning keeps a raw file that is
  # overwritten or deleted by mistake; Delta's own history covers bronze and silver.
  versioning {
    enabled = true
  }

  # Old versions are only a safety net: delete them after 90 days.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 90
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# Gold: the facts and the mart the strategist queries.
resource "google_bigquery_dataset" "gold" {
  dataset_id  = "gold"
  location    = var.region
  description = "F1 race strategy: facts and mart_race_outcome, built per race by the pipeline"

  depends_on = [google_project_service.apis]
}

# The identity the pipeline's tasks run as. Its key is created by hand (see README),
# so it never ends up in the Terraform state.
resource "google_service_account" "pipeline" {
  account_id   = "f1-pipeline"
  display_name = "F1 pipeline (Kestra tasks)"

  depends_on = [google_project_service.apis]
}

# Least privilege: read/write objects in the lake bucket only ...
resource "google_storage_bucket_iam_member" "pipeline_lake" {
  bucket = google_storage_bucket.lake.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.pipeline.member
}

# ... write tables in the gold dataset only ...
resource "google_bigquery_dataset_iam_member" "pipeline_gold" {
  dataset_id = google_bigquery_dataset.gold.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.pipeline.member
}

# ... and run BigQuery jobs (loads, MERGE), which is a project-level permission.
resource "google_project_iam_member" "pipeline_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.pipeline.member
}
