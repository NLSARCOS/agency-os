// Before
await db.proposals.create({ title, content });

// After
await db.proposals.create({ 
    title, 
    content, 
    tenant_id: getCurrentTenant().id // From request context
});