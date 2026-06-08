/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

const LEGAL_SOURCE_ID_PATTERN = /\[(?:source|ev)_\d+\]\s*/gi
const NOISY_LEGAL_META_PATTERN =
  /[（(]\s*(?:law|contract|case|court_decision|penalty|regulation|unknown)\s*(?:，|,)\s*unknown\s*[）)]/gi

export function normalizeLegalDisplayText(value?: string) {
  if (!value) return value || ''

  return value
    .replace(LEGAL_SOURCE_ID_PATTERN, '')
    .replace(NOISY_LEGAL_META_PATTERN, '')
    .replace(/[ \t]+\n/g, '\n')
}

export function extractHttpUrl(value?: unknown) {
  if (typeof value !== 'string') return ''
  const raw = value.trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw

  const match = raw.match(/https?:\/\/[^\s"'<>，。；;）)\]]+/i)
  return match?.[0] || ''
}

function cleanReferenceTitle(value: string) {
  const normalized = normalizeLegalDisplayText(value)
    .replace(/^来源\s*\d+\s*[:：-]?\s*/, '')
    .trim()

  return normalized || '来源'
}

function normalizeReferenceSource(ref: Record<string, any>): API.Reference['source'] {
  const raw = String(ref.source || ref.source_type || ref.type || '').toLowerCase()
  return raw === 'local' || raw === 'knowledge' || raw === 'knowledge_base'
    ? 'knowledge'
    : 'web'
}

export function normalizeReference(ref: Record<string, any>, index: number): API.Reference {
  const content = String(ref.content || ref.summary || ref.snippet || ref.text || '')
  const link =
    extractHttpUrl(ref.link) ||
    extractHttpUrl(ref.url) ||
    extractHttpUrl(ref.source_url) ||
    extractHttpUrl(ref.sourceUrl) ||
    extractHttpUrl(ref.href) ||
    extractHttpUrl(content)

  const titleSource =
    ref.title ||
    ref.source_name ||
    ref.name ||
    ref.marker ||
    ref.source ||
    content.slice(0, 60) ||
    `来源 ${index + 1}`

  return {
    id: index + 1,
    title: cleanReferenceTitle(String(titleSource)),
    link,
    content: normalizeLegalDisplayText(content),
    source: normalizeReferenceSource(ref),
  }
}

export function normalizeReferences(refs?: unknown): API.Reference[] | undefined {
  if (!Array.isArray(refs) || refs.length === 0) return undefined
  return refs
    .filter((ref): ref is Record<string, any> => !!ref && typeof ref === 'object')
    .map((ref, index) => normalizeReference(ref, index))
}
