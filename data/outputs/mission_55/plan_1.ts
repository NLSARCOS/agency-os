// services/pdf/generator.ts
export class PDFGenerator {
  private gotenbergUrl: string;
  
  async generate(templateId: string, data: any, branding: BrandingConfig): Promise<Buffer> {
    // 1. Compile template with Handlebars
    const html = await this.templateEngine.render(templateId, data, branding);
    
    // 2. Send to Gotenberg
    const response = await fetch(`${this.gotenbergUrl}/forms/chromium/convert/html`, {
      method: 'POST',
      headers: { 'Content-Type': 'multipart/form-data' },
      body: this.createFormData(html, branding)
    });
    
    return Buffer.from(await response.arrayBuffer());
  }
}