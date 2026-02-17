-- Migration 002: Add quality metrics, evaluation mode, and per-source pipeline tracking
-- Run: bq query --use_legacy_sql=false --project_id=$GCP_PROJECT_ID < gcp/bigquery/migrations/002_quality_metrics.sql

-- Quality metrics on unified_events
ALTER TABLE `quake_stream.unified_events`
  ADD COLUMN IF NOT EXISTS magnitude_std FLOAT64,
  ADD COLUMN IF NOT EXISTS location_spread_km FLOAT64,
  ADD COLUMN IF NOT EXISTS source_agreement_score FLOAT64;

-- Evaluation mode on raw_events (for QuakeML sources)
ALTER TABLE `quake_stream.raw_events`
  ADD COLUMN IF NOT EXISTS evaluation_mode STRING;

-- Per-source tracking on pipeline_runs
ALTER TABLE `quake_stream.pipeline_runs`
  ADD COLUMN IF NOT EXISTS source_name STRING;
