// Outbound webhooks for tenant integrations
interface WebhookPayload {
  event: string;
  timestamp: string;
  data: unknown;
  signature: string; // HMAC-SHA256
}

// Queue webhooks for retry logic (BullMQ/Redis)