// services/email/sender.ts
export class EmailService {
  async sendWithTracking(payload: EmailPayload): Promise<void> {
    const { data, error } = await resend.emails.send({
      from: this.getBrandedFrom(payload.tenantId),
      to: payload.to,
      subject: payload.subject,
      html: await this.renderTemplate(payload),
      attachments: await this.getAttachments(payload.pdfKey),
      headers: {
        'X-Entity-Ref-ID': payload.jobId, // For idempotency
        'X-PM-Message-Stream': 'broadcast' // Resend tracking
      }
    });
    
    if (error) throw new RetryableError(error.message);
    
    await this.logEvent(payload.jobId, 'sent', data?.id);
  }
}