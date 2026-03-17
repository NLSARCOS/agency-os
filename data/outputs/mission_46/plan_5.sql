-- Disable RLS instantly
ALTER TABLE proposals DISABLE ROW LEVEL SECURITY;

-- Revert application to single-tenant mode via feature flag
UPDATE config SET multi_tenant_mode = false;