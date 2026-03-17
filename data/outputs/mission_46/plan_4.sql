-- Make tenant_id NOT NULL after backfill complete
ALTER TABLE proposals ALTER COLUMN tenant_id SET NOT NULL;

-- Create restrictive policies
CREATE POLICY tenant_isolation_strict ON proposals
    USING (tenant_id = current_setting('app.current_tenant')::UUID);
    
-- Revoke direct table access, force RLS
REVOKE ALL ON proposals FROM application_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON proposals TO application_user;