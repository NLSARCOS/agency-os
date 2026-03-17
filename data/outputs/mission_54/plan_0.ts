// types/pipeline.ts
interface Opportunity {
  id: string;
  title: string;
  clientName: string;
  value: number;
  stageId: string;
  assignedTo?: string;
  priority: 'low' | 'medium' | 'high';
  dueDate?: Date;
  updatedAt: Date;
  version: number; // For conflict resolution
}

interface Stage {
  id: string;
  name: string;
  order: number;
  color?: string;
  wipLimit?: number; // Kanban WIP limits
}

interface PipelinePermissions {
  canMove: boolean;
  canEdit: boolean;
  canDelete: boolean;
  canAssign: boolean;
}