// PDF Generation Job
interface PDFJob {
  id: string;
  workspaceId: string;        // Multi-tenant isolation
  templateId: string;         // Reference to creative asset
  variables: Record<string, any>; // Dynamic data injection
  branding: TenantBranding;   // Colors, logos, fonts
  status: 'queued' | 'processing' | 'completed' | 'failed';
  outputUrl?: string;         // Signed S3/R2 URL
  createdAt: Date;
  completedAt?: Date;
}

// Email Delivery Record
interface EmailDelivery {
  id: string;
  pdfJobId: string;
  recipientEmail: string;
  providerMessageId: string;
  status: 'sent' | 'delivered' | 'opened' | 'bounced';
  trackingPixelId: string;
  openedAt?: Date;
  clickedAt?: Date;
}