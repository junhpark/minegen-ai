import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, parseAttachmentFilename } from './client'

const zipResponse = () =>
  new Response(new Blob([new Uint8Array([80, 75, 3, 4])]), {
    status: 200,
    headers: {
      'content-type': 'application/zip',
      'content-disposition': 'attachment; filename="minegen_s1_mineexchange_v1.zip"',
    },
  })

const refusalResponse = () =>
  new Response(
    JSON.stringify({
      detail: { code: 'READ_SNAPSHOT_CHANGED', message: 'derived artifacts changed' },
    }),
    { status: 409, headers: { 'content-type': 'application/json' } },
  )

describe('Phase 23A MineExchange download client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('parses the plain RFC 6266 attachment filename and rejects path-like names', () => {
    expect(
      parseAttachmentFilename('attachment; filename="minegen_abc_mineexchange_v1.zip"', 'f.zip'),
    ).toBe('minegen_abc_mineexchange_v1.zip')
    expect(parseAttachmentFilename('attachment; filename=plain.zip', 'f.zip')).toBe('plain.zip')
    expect(parseAttachmentFilename(null, 'f.zip')).toBe('f.zip')
    expect(parseAttachmentFilename('attachment', 'f.zip')).toBe('f.zip')
    expect(parseAttachmentFilename('attachment; filename="../x.zip"', 'f.zip')).toBe('f.zip')
    expect(parseAttachmentFilename('attachment; filename="a/b.zip"', 'f.zip')).toBe('f.zip')
  })

  it('POSTs the export and returns the blob with the server filename', async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      expect(init?.method).toBe('POST')
      return Promise.resolve(zipResponse())
    })
    vi.stubGlobal('fetch', fetchMock)
    const file = await api.exportMineExchange('s1')
    expect(file.filename).toBe('minegen_s1_mineexchange_v1.zip')
    expect(file.blob.size).toBe(4)
    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(/\/scenarios\/s1\/export\/mine-exchange$/)
  })

  it('maps a typed backend refusal to ApiError (existing error UI convention)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(refusalResponse())),
    )
    await expect(api.exportMineExchange('s1')).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      code: 'READ_SNAPSHOT_CHANGED',
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(refusalResponse())),
    )
    await expect(api.exportMineExchange('s1')).rejects.toBeInstanceOf(ApiError)
  })
})
