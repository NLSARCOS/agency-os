// webhooks/email-events.ts
export async function handleEmailWebhook(req: Request) {
  const event = validateWebhookSignature(req); // Resend signature
  
  await db.emailEvents.create({
    data: {
      providerMessageId: event.email_id,
      event: event.type, // delivered, opened, clicked, bounced
      timestamp: new Date(event.created_at),
      metadata: event
    }
  });
  
  // Update aggregate stats
  await updateDeliveryStats(event.email_id, event.type);
}