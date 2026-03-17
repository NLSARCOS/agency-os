-- Core subscription tracking (Stripe as source of truth)
subscriptions
  - id (uuid)
  - user_id (fk)
  - stripe_customer_id
  - stripe_subscription_id
  - status (active/canceled/past_due)
  - tier (free/pro/enterprise)
  - current_period_end (timestamp)
  - cancel_at_period_end (boolean)
  - created_at/updated_at

-- Usage tracking (for metered billing or limits)
usage_limits
  - user_id
  - feature_key (e.g., "pipeline_runs")
  - current_count
  - reset_date

-- Audit trail (idempotency + debugging)
billing_events
  - id
  - stripe_event_id (unique)
  - event_type
  - payload (jsonb)
  - processed_at