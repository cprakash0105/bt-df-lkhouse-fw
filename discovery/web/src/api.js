// In production, API is same origin (no /api prefix)
// In dev, Vite proxies /api -> localhost:8000
const BASE = import.meta.env.DEV ? '/api' : ''

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),
  glossary: () => request('/glossary'),
  glossaryHierarchy: () => request('/glossary/hierarchy'),
  searchGlossary: (q) => request(`/glossary/search?q=${encodeURIComponent(q)}`),
  describeTerm: (termId) => request(`/glossary/describe/${encodeURIComponent(termId)}`),
  createBDE: (data) => request('/glossary', { method: 'POST', body: JSON.stringify(data) }),
  askCatalog: (question) => request('/ask', { method: 'POST', body: JSON.stringify({ requirement: question }) }),
  catalogTree: () => request('/catalog/tree'),
  catalogSearch: (q) => request(`/catalog/search?q=${encodeURIComponent(q)}`),
  catalogSync: () => request('/catalog/sync', { method: 'POST' }),
  applications: () => request('/applications'),
  domains: () => request('/domains'),

  discover: (payload) => request('/discover', { method: 'POST', body: JSON.stringify(payload) }),
  discoverMulti: (text) => request('/discover/multi', { method: 'POST', body: JSON.stringify({ text }) }),
  discoverAll: () => request('/discover/all', { method: 'POST' }),
  listLanding: () => request('/landing/datasets'),
  profile: (data, format = 'csv', dataset_name = null) =>
    request('/profile', { method: 'POST', body: JSON.stringify({ data, format, dataset_name }) }),
  profileDataset: (dataset_name) =>
    request('/profile/dataset', { method: 'POST', body: JSON.stringify({ dataset_name }) }),

  approve: (fields = null) => request('/approve', { method: 'POST', body: JSON.stringify({ fields }) }),
  correct: (field, action, values = null, bde = null) =>
    request('/correct', { method: 'POST', body: JSON.stringify({ field, action, values, bde }) }),

  getSuggestion: () => request('/suggestion'),
  generateConfig: () => request('/generate/config', { method: 'POST' }),
  generateSQL: (requirement) => request('/generate/sql', { method: 'POST', body: JSON.stringify({ requirement }) }),
  generateDataProduct: (requirement) => request('/generate/dataproduct', { method: 'POST', body: JSON.stringify({ requirement }) }),

  parseBRD: (brd_text, product_name = null) =>
    request('/brd/parse', { method: 'POST', body: JSON.stringify({ brd_text, product_name }) }),
  listBRDSpecs: () => request('/brd/specs'),
  getBRDSpec: (product_name) => request(`/brd/specs/${encodeURIComponent(product_name)}`),

  deployDataProduct: (table_name, sql, description = null, source_datasets = null, domain = null) =>
    request('/dataproduct/deploy', { method: 'POST', body: JSON.stringify({ table_name, sql, description, source_datasets, domain }) }),
  listDeployedDataProducts: () => request('/dataproduct/list'),
  lineage: (dataset) => request(`/lineage/${encodeURIComponent(dataset)}`),
  bdeLineage: (termId) => request(`/lineage/bde/${encodeURIComponent(termId)}`),
  dqScoreBde: (bdeId) => request(`/dq/score/${encodeURIComponent(bdeId)}`),
  dqScoreBa: (baId) => request(`/dq/score/ba/${encodeURIComponent(baId)}`),
  dqRollup: () => request('/dq/rollup', { method: 'POST' }),
}
