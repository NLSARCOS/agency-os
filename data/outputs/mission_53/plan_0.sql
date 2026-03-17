-- Core tables with tenant isolation
tenants (id, slug, settings, created_at)
pipelines (id, tenant_id, name, stages_config, created_at)
opportunities (
  id, tenant_id, pipeline_id, 
  title, value, currency, 
  stage_id, assigned_to, 
  contact_data (jsonb), -- denormalized for performance
  custom_fields (jsonb),
  created_at, updated_at, deleted_at
)
proposals (
  id, tenant_id, opportunity_id,
  template_id, content (jsonb), -- structured blocks
  status, sent_at, viewed_at, accepted_at,
  file_url, version
)
stages (
  id, tenant_id, pipeline_id,
  name, order, color, 
  automation_rules (jsonb), -- triggers on enter/exit
  required_fields (jsonb)
)
activities (
  id, tenant_id, opportunity_id,
  type, metadata, performed_by, created_at
) -- audit trail + timeline
files (
  id, tenant_id, opportunity_id,
  filename, storage_key, mime_type, size, uploaded_by
)