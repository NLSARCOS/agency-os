// Routes organized by domain
app.register(async (api, opts) => {
  // Tenant isolation middleware (from Wave 1)
  api.addHook('preHandler', requireTenantContext);
  api.addHook('preHandler', requireAuth);
  
  // Opportunities
  api.get('/opportunities', listOpportunitiesHandler);
  api.post('/opportunities', createOpportunityHandler);
  api.get('/opportunities/:id', getOpportunityHandler);
  api.patch('/opportunities/:id', updateOpportunityHandler);
  api.post('/opportunities/:id/move', moveStageHandler);
  api.delete('/opportunities/:id', softDeleteOpportunityHandler);
  
  // Proposals
  api.post('/opportunities/:id/proposals', generateProposalHandler);
  api.get('/proposals/:id/download', downloadProposalHandler); // Signed URL
  
  // Pipeline Management
  api.get('/pipelines', listPipelinesHandler);
  api.patch('/pipelines/:id/stages', reorderStagesHandler);
  
  // Files
  api.post('/files/upload', uploadFileHandler); // Multipart/form-data
  api.get('/files/:id', getFileHandler);
}, { prefix: '/v1' });