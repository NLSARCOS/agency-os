-- Enable RLS on all tables
ALTER TABLE proposals ENABLE ROW LEVEL SECURITY;

-- Create permissive policy (logs violations, doesn't block)
CREATE POLICY tenant_isolation_proposals ON proposals
    USING (tenant_id = current_setting('app.current_tenant')::UUID);
    
-- Set default to bypass RLS for existing app (gradual enforcement)
ALTER TABLE proposals FORCE ROW LEVEL SECURITY; -- Only for new connections