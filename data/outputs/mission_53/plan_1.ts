// Core entities with strict typing
interface Opportunity {
  id: string;
  tenantId: string;
  pipelineId: string;
  title: string;
  value: Money; // { amount: number, currency: string }
  stage: Stage;
  assignedTo: UserRef;
  contact: Contact; // embedded snapshot
  customFields: Record<string, unknown>;
  timeline: Activity[];
  proposals: Proposal[];
  files: FileRef[];
  createdAt: Date;
  updatedAt: Date;
}