{
  "id": "job_123",
  "status": "processing", // queued | processing | completed | failed
  "stage": "pdf_generated", // pdf_generated | uploading | emailing | completed
  "progress": 75,
  "result": {
    "pdfUrl": "https://cdn.../job_123.pdf", // Signed URL, 1hr expiry
    "emailStatus": "sent"
  },
  "error": null // or error details
}