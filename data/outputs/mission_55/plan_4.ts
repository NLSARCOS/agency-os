// Request
{
  "templateId": "proposal-v2",
  "data": { "clientName": "Acme Corp", ... },
  "delivery": {
    "method": "email", // or "download"
    "to": ["client@acme.com"],
    "subject": "Your Proposal"
  }
}

// Response (202 Accepted)
{
  "jobId": "job_123",
  "status": "queued",
  "estimatedCompletion": "2024-01-15T10:30:00Z",
  "pollUrl": "/api/v1/jobs/job_123/status"
}