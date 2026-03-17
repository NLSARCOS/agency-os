const CreateOpportunitySchema = z.object({
  title: z.string().min(3).max(200),
  value: z.object({
    amount: z.number().positive(),
    currency: z.string().length(3).default('USD')
  }),
  stageId: z.string().uuid(),
  contact: ContactSchema,
  customFields: z.record(z.unknown()).optional()
}).strict();