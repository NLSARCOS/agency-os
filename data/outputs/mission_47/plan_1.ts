const ReportPayload = z.object({
  mission_id: z.string().uuid(),
  checkpoint: z.string().max(100),
  percent_complete: z.number().min(0).max(100),
  status: z.enum(['on_track', 'delayed', 'blocked']),
  blockers: z.array(z.string()).optional(),
  metrics: z.record(z.union([z.number(), z.string()])).optional(),
  timestamp: z.string().datetime().optional() // client timestamp
});