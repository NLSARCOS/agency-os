// Before template rendering
const sanitizedData = DOMPurify.sanitize(JSON.stringify(data), {
  ALLOWED_TAGS: [],
  ALLOWED_ATTR: []
});