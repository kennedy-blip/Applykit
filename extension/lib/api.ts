import browser from 'webextension-polyfill';

export interface ExtensionSettings {
  backendUrl: string;
  jwtToken: string;
  cvText: string;
  hideLowMatch: boolean;
  isPro: boolean;
}

export interface ExtractedJob {
  platform: 'upwork_job' | 'linkedin_job' | 'generic_job';
  title: string;
  company: string;
  salary: string;
  description: string;
  url: string;
  clientStats: {
    verified: boolean;
    spent: string;
    hiredCount: number;
    postedCount: number;
    avgRate: string;
    warning?: string;
  };
}

const DEFAULT_SETTINGS: ExtensionSettings = {
  backendUrl: 'http://localhost:8000',
  jwtToken: '',
  cvText: '',
  hideLowMatch: false,
  isPro: false
};

export async function getSettings(): Promise<ExtensionSettings> {
  const stored = await browser.storage.local.get(Object.keys(DEFAULT_SETTINGS));
  return { ...DEFAULT_SETTINGS, ...(stored as Partial<ExtensionSettings>) };
}

export async function saveSettings(partial: Partial<ExtensionSettings>): Promise<ExtensionSettings> {
  const next = { ...(await getSettings()), ...partial };
  await browser.storage.local.set(next);
  return next;
}

async function apiRequest<T = any>(path: string, method: 'GET' | 'POST' = 'POST', body?: unknown): Promise<T> {
  const settings = await getSettings();
  const base = settings.backendUrl.replace(/\/+$/, '');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  };
  if (settings.jwtToken) {
    headers['Authorization'] = `Bearer ${settings.jwtToken}`;
  }

  const resp = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined
  });

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = data?.detail;
    const msg = typeof detail === 'object' ? detail.message : detail || `HTTP ${resp.status}`;
    const err = new Error(msg) as Error & { code?: string; status?: number };
    err.code = typeof detail === 'object' ? detail.code : undefined;
    err.status = resp.status;
    throw err;
  }
  return data as T;
}

export async function queryVaultRouter(query: string, context: string, url: string) {
  return apiRequest('/api/router', 'POST', { query, context, url });
}

export async function executeBackendTool(params: {
  tool_id: string;
  input: string;
  cv_text?: string;
  page_context?: string;
  tone?: string;
}) {
  return apiRequest('/api/execute', 'POST', params);
}

export async function checkAtsScore(cvText: string, jdText: string) {
  return apiRequest('/api/ai/ats-score', 'POST', { cv_text: cvText, jd_text: jdText });
}

export async function generateCoverLetter(cvText: string, jdText: string, tone = 'Upwork Hook-First Pitch') {
  return apiRequest('/api/ai/cover-letter', 'POST', { cv_text: cvText, jd_text: jdText, tone });
}

export async function checkScamRisk(jobText: string, clientMeta: string) {
  return apiRequest('/api/ai/scam-check', 'POST', { job_text: jobText, client_meta: clientMeta });
}

export async function saveApplicationToKanban(payload: {
  job_title: string;
  company: string;
  platform: string;
  job_url: string;
  salary?: string;
  status?: string;
  match_score?: number;
  scam_risk?: string;
  private_notes?: string;
}) {
  return apiRequest('/api/applications/save', 'POST', payload);
}

export async function fetchCurrentUser() {
  return apiRequest('/api/me', 'GET');
}
