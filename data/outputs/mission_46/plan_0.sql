-- Add tenant_id to all tables (nullable initially for zero-downtime migration)
ALTER TABLE proposals ADD COLUMN tenant_id UUID;
ALTER TABLE users ADD COLUMN tenant_id UUID;
-- ... all tenant-scoped tables

-- Create tenant lookup table
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Backfill existing data (single-tenant = default tenant)
INSERT INTO tenants (id, slug, name) VALUES 
    ('00000000-0000-0000-0000-000000000000', 'legacy', 'Legacy Tenant');
UPDATE proposals SET tenant_id = '00000000-0000-0000-0000-000000000000' WHERE tenant_id IS NULL;