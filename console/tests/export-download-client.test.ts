import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '@/lib/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

describe('api.exports.download', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('decodes a PDF base64 export envelope into a real PDF blob', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          export_id: 'export-pdf',
          content_type: 'application/pdf',
          filename: 'export-pdf.pdf',
          body_base64: 'JVBERi0xLjQK',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const blob = await api.exports.download('export-pdf');
    const header = new TextDecoder().decode((await readBlob(blob)).slice(0, 5));

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/v1/exports/export-pdf/download`,
      expect.objectContaining({ credentials: 'include' }),
    );
    expect(blob.type).toBe('application/pdf');
    expect(header).toBe('%PDF-');
  });
});

function readBlob(blob: Blob): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.readAsArrayBuffer(blob);
  });
}
