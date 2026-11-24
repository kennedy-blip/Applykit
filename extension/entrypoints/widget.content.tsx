import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import browser from 'webextension-polyfill';
import { ExtractedJob, getSettings } from '../lib/api';

function FloatingWidgetApp() {
  const [open, setOpen] = useState(false);
  const [job, setJob] = useState<ExtractedJob | null>(null);
  const [query, setQuery] = useState('');
  const [tools, setTools] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [output, setOutput] = useState<string>('');
  const [matchedKw, setMatchedKw] = useState<string[]>([]);
  const [missingKw, setMissingKw] = useState<string[]>([]);
  const [matchScore, setMatchScore] = useState<number | null>(null);
  const [scamRisk, setScamRisk] = useState<string>('Low');
  const [privateNotes, setPrivateNotes] = useState<string>('');
  const [statusMsg, setStatusMsg] = useState<string>('');

  const refreshContext = async (q = '') => {
    const currentJob =
      window.__APPLYKIT_CURRENT_JOB__ || {
        platform: window.location.hostname.includes('upwork') ? 'upwork_job' : 'linkedin_job',
        title: document.title,
        company: 'Hiring Client',
        salary: '',
        description: document.body.innerText.slice(0, 5000),
        url: window.location.href,
        clientStats: { verified: true, spent: 'N/A', hiredCount: 0, postedCount: 0, avgRate: 'N/A' }
      };
    setJob(currentJob);

    try {
      const res: any = await browser.runtime.sendMessage({
        type: 'APPLYKIT_ROUTER',
        query: q,
        context: currentJob.platform,
        url: window.location.href
      });
      setTools(res?.tools || []);
    } catch {
      setTools([
        { id: 'ats-checker', name: 'Check Match Score', icon: '🎯' },
        { id: 'cover-letter-generator', name: 'Generate Cover Letter', icon: '✍️' },
        { id: 'scam-detector', name: 'Check Scam Risk', icon: '🛡️' }
      ]);
    }
  };

  useEffect(() => {
    if (open) {
      refreshContext(query);
    }
  }, [open]);

  const handleRunAts = async () => {
    if (!job) return;
    setLoading(true);
    setStatusMsg('');
    try {
      const settings = await getSettings();
      const cv = settings.cvText || 'Experienced remote professional skilled in Python, FastAPI, communication, and agile project delivery.';
      const res: any = await browser.runtime.sendMessage({
        type: 'APPLYKIT_ATS',
        cvText: cv,
        jdText: job.description || job.title
      });
      const r = res.result || {};
      setMatchScore(r.score ?? 78);
      setMatchedKw(r.matched_keywords || []);
      setMissingKw(r.missing_keywords || []);
      setOutput(`${r.verdict} (${r.score}/100)\n${r.summary}\n\nTailored CV Summary:\n${r.tailored_summary || ''}`);
    } catch (e: any) {
      setStatusMsg(e?.message || 'Connect backend or upgrade to Pro.');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateAndInsertCoverLetter = async () => {
    if (!job) return;
    setLoading(true);
    setStatusMsg('');
    try {
      const settings = await getSettings();
      const cv = settings.cvText || 'Remote specialist delivering measurable client results on time.';
      const res: any = await browser.runtime.sendMessage({
        type: 'APPLYKIT_COVER_LETTER',
        cvText: cv,
        jdText: job.description || job.title,
        tone: 'Upwork Hook-First Pitch'
      });
      const letter = res.result?.cover_letter || '';
      setOutput(letter);
      window.dispatchEvent(new CustomEvent('applykit:insert-proposal', { detail: letter }));
      setStatusMsg('✓ Generated & inserted into proposal box!');
    } catch (e: any) {
      setStatusMsg(e?.message || 'Sign in or upgrade to Pro for 1-click proposal insert.');
    } finally {
      setLoading(false);
    }
  };

  const handleScamCheck = async () => {
    if (!job) return;
    setLoading(true);
    try {
      const meta = job.clientStats.warning || `${job.clientStats.spent}, hired ${job.clientStats.hiredCount}`;
      const res: any = await browser.runtime.sendMessage({
        type: 'APPLYKIT_SCAM_CHECK',
        jobText: job.description || job.title,
        clientMeta: meta
      });
      const r = res.result || {};
      setScamRisk(r.risk_level || 'Low');
      setOutput(`Scam Risk: ${r.risk_level} (${r.risk_score}/100)\n${r.verdict_headline}\n• ${(r.red_flags || []).join('\n• ')}`);
    } catch (e: any) {
      setStatusMsg(e?.message || 'Scam check failed.');
    } finally {
      setLoading(false);
    }
  };

  const handleRunVaultTool = async (toolId: string) => {
    if (toolId === 'ats-checker') return handleRunAts();
    if (toolId === 'cover-letter-generator') return handleGenerateAndInsertCoverLetter();
    if (toolId === 'scam-detector') return handleScamCheck();

    setLoading(true);
    try {
      const settings = await getSettings();
      const res: any = await browser.runtime.sendMessage({
        type: 'APPLYKIT_EXECUTE',
        payload: {
          tool_id: toolId,
          input: job?.description || job?.title || query,
          cv_text: settings.cvText,
          page_context: job?.url || ''
        }
      });
      setOutput(res.result?.copy_text || JSON.stringify(res.result, null, 2));
    } catch (e: any) {
      setStatusMsg(e?.message || 'Limit reached — upgrade to ApplyKit Pro.');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadTailoredCv = () => {
    const content = output || 'Run Check Match Score first to generate tailored CV bullets.';
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'ApplyKit_Tailored_CV_Bullets.txt';
    a.click();
  };

  const handleSaveJob = async () => {
    if (!job) return;
    try {
      await browser.runtime.sendMessage({
        type: 'APPLYKIT_SAVE_JOB',
        payload: {
          job_title: job.title,
          company: job.company,
          platform: job.platform === 'upwork_job' ? 'Upwork' : 'LinkedIn',
          job_url: job.url,
          salary: job.salary,
          status: 'Applied',
          match_score: matchScore ?? undefined,
          scam_risk: scamRisk,
          private_notes: privateNotes
        }
      });
      setStatusMsg('✓ Synced to ApplyKit Kanban Dashboard!');
    } catch (e: any) {
      setStatusMsg(e?.message || 'Sign in inside extension popup to sync jobs.');
    }
  };

  return (
    <div style={{ position: 'fixed', bottom: '22px', right: '22px', zIndex: 2147483646, fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          title="Open ApplyKit AI Job Assistant"
          style={{
            background: '#059669',
            color: '#fff',
            border: 'none',
            borderRadius: '999px',
            padding: '12px 18px',
            fontWeight: 800,
            fontSize: '14px',
            cursor: 'pointer',
            boxShadow: '0 10px 25px rgba(5,150,105,0.45)',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}
        >
          <span>⚡</span>
          <span>ApplyKit</span>
        </button>
      ) : (
        <div
          style={{
            width: '360px',
            maxHeight: '82vh',
            overflowY: 'auto',
            background: '#ffffff',
            color: '#0f172a',
            borderRadius: '18px',
            border: '1px solid #cbd5e1',
            boxShadow: '0 24px 48px rgba(15,23,42,0.28)',
            padding: '14px'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <strong style={{ fontSize: '14px', color: '#065f46' }}>⚡ ApplyKit Job Copilot</strong>
            <button
              onClick={() => setOpen(false)}
              style={{ background: 'transparent', border: 'none', fontSize: '16px', cursor: 'pointer', color: '#64748b' }}
            >
              ✕
            </button>
          </div>

          {/* Client Reputation Card */}
          {job && (
            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '10px', marginBottom: '10px', fontSize: '12px' }}>
              <div style={{ fontWeight: 700, marginBottom: '4px' }}>{job.title.slice(0, 75)}</div>
              <div style={{ color: '#475569' }}>
                {job.clientStats.verified ? '✅ Verified Client' : '⚠️ Unverified'} · {job.clientStats.spent} · Hires: {job.clientStats.hiredCount}
              </div>
              {job.clientStats.warning && (
                <div style={{ color: '#be123c', fontWeight: 700, marginTop: '4px' }}>🚩 {job.clientStats.warning}</div>
              )}
            </div>
          )}

          {/* Universal Vault Search Input */}
          <input
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              refreshContext(e.target.value);
            }}
            placeholder="⚡ Ask ApplyKit... ('negotiate', 'NDA', 'connects')"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '8px 10px',
              borderRadius: '10px',
              border: '1px solid #cbd5e1',
              fontSize: '12px',
              marginBottom: '8px'
            }}
          />

          {/* Quick 1-Click Actions */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginBottom: '8px' }}>
            <button onClick={handleRunAts} disabled={loading} style={btnStyle('#059669', '#fff')}>
              🎯 Match Score
            </button>
            <button onClick={handleGenerateAndInsertCoverLetter} disabled={loading} style={btnStyle('#0f172a', '#fff')}>
              ✍️ 1-Click Proposal
            </button>
            <button onClick={handleScamCheck} disabled={loading} style={btnStyle('#f1f5f9', '#0f172a')}>
              🛡️ Scam Check
            </button>
            <button onClick={handleDownloadTailoredCv} style={btnStyle('#ecfdf5', '#065f46')}>
              📄 Tailor CV
            </button>
          </div>

          {/* Dynamic Router Suggestions */}
          {tools.length > 0 && (
            <div style={{ marginBottom: '8px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', color: '#64748b', marginBottom: '4px' }}>
                Recommended Vault Tools
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                {tools.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => handleRunVaultTool(t.id)}
                    style={{
                      background: '#f8fafc',
                      border: '1px solid #e2e8f0',
                      borderRadius: '999px',
                      padding: '4px 9px',
                      fontSize: '11px',
                      cursor: 'pointer'
                    }}
                  >
                    {t.icon} {t.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Green / Red Keyword Chips */}
          {(matchedKw.length > 0 || missingKw.length > 0) && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '8px' }}>
              {matchedKw.slice(0, 5).map((k) => (
                <span key={k} style={{ background: '#dcfce7', color: '#166534', fontSize: '10px', padding: '2px 6px', borderRadius: '6px', fontWeight: 600 }}>
                  ✓ {k}
                </span>
              ))}
              {missingKw.slice(0, 5).map((k) => (
                <span key={k} style={{ background: '#ffe4e6', color: '#9f1239', fontSize: '10px', padding: '2px 6px', borderRadius: '6px', fontWeight: 600 }}>
                  ✗ {k}
                </span>
              ))}
            </div>
          )}

          {/* AI Output Box */}
          {output && (
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: '10px',
                padding: '8px',
                fontSize: '11px',
                maxHeight: '160px',
                overflowY: 'auto',
                marginBottom: '8px'
              }}
            >
              {output}
            </pre>
          )}

          {/* Private Notes + Save to Kanban */}
          <textarea
            rows={2}
            value={privateNotes}
            onChange={(e) => setPrivateNotes(e.target.value)}
            placeholder="Private job notes (synced to Kanban)..."
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '6px 8px',
              borderRadius: '8px',
              border: '1px solid #cbd5e1',
              fontSize: '11px',
              marginBottom: '6px'
            }}
          />
          <button onClick={handleSaveJob} style={{ ...btnStyle('#047857', '#fff'), width: '100%' }}>
            📌 Save Job + Notes to Kanban
          </button>

          {statusMsg && <div style={{ marginTop: '6px', fontSize: '11px', color: '#047857', fontWeight: 600 }}>{statusMsg}</div>}
        </div>
      )}
    </div>
  );
}

function btnStyle(bg: string, color: string): React.CSSProperties {
  return {
    background: bg,
    color,
    border: 'none',
    borderRadius: '9px',
    padding: '8px',
    fontSize: '11px',
    fontWeight: 700,
    cursor: 'pointer'
  };
}

export default defineContentScript({
  matches: ['*://*.upwork.com/*', '*://*.linkedin.com/*'],
  runAt: 'document_idle',
  main() {
    if (document.getElementById('applykit-floating-root')) return;
    const host = document.createElement('div');
    host.id = 'applykit-floating-root';
    document.body.appendChild(host);
    ReactDOM.createRoot(host).render(<FloatingWidgetApp />);
  }
});
