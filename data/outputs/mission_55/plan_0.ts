// Job Types
interface PDFJob {
  type: 'GENERATE_PDF';
  templateId: string;
  data: Record<string, any>;
  tenantId: string;
  branding: BrandingConfig;
}

interface EmailJob {
  type: 'SEND_EMAIL';
  to: string[];
  template: string;
  attachments: string[]; // S3 keys
  metadata: EmailMetadata;
}