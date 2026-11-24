import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { fetchCurrentUser, getSettings, queryVaultRouter, saveSettings } from '../../lib/api';

function PopupApp() {
  const [backendUrl, setBackendUrl] = useState('http://localhost:8000');
  const [jwtToken, setJwtToken] = useState('');
  const [cvText, setCvText] = useState('');
  const [hideLowMatch, setHideLowMatch] = useState(false);
  const [isPro, setIsPro] = useState(false);
  const [userEmail, setUserEmail] = useState('');
  const [search, setSearch] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [savedBanner, setSavedBanner] = useState('');

  useEffect(() => {
    getSettings().then((s) => {
      setBackendUrl(s.backendUrl);
      setJwtToken(s.jwtToken);
      setCvText(s.cvText);
      setHideLowMatch(s.hideLowMatch);
      setIsPro(s.isPro);
    });
    fetchCurrentUser()
      .then((me) => {
        if (me?.authenticated && me.user) {
          setUserEmail(me.user.email || '');
          setIsPro(Boolean(me.user.is_pro));
          saveSettings({ isPro: Boolean(me.user.is_pro) });
        }
      })
      .catch(() => {});
  }, []);

  const handleSave = async () => {
    await saveSettings({ backendUrl, jwtToken, cvText, hideLowMatch });
    setSavedBanner('✓ Synced settings across browser!');
    setTimeout(() => setSavedBanner(''), 2200);
  };

  const handleVaultSearch = async (q: string) => {
    setSearch(q);
    try {
      const data = await queryVaultRouter(q, 'popup', '');
      setResults(data?.tools || []);
    } catch {
      setResults([]);
    }
  };

  return (
    <div style={{ width: '350px', padding: '14px', fontFamily: 'system-ui, sans-serif', color: '#0f172a', background: '#f8fafc' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <div style={{ fontWeight: 900, fontSize: '16px' }}>⚡ ApplyKit Hub</div>
        <span
          style={{
            fontSize: '10px',
            fontWeight: 800,
            padding: '2px 8px',
            borderRadius: '999px',
            background: isPro ? '#dcfce7' : '#e2e8f0',
            color: isPro ? '#065f46' : '#334155'
          }}
        >
          {isPro ? 'PRO UNLIMITED' : 'FREE TIER'}
        </span>
      </div>

      {userEmail && <div style={{ fontSize: '11px', color: '#047857', marginBottom: '8px' }}>Signed in: {userEmail}</div>}

      {/* Universal Vault Search */}
      <input
        type="search"
        value={search}
        onChange={(e) => handleVaultSearch(e.target.value)}
        placeholder="⚡ Ask ApplyKit Vault ('resign', 'NDA', 'rate')..."
        style={{ width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '12px', marginBottom: '8px' }}
      />

      {results.length > 0 && (
        <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px', padding: '8px', marginBottom: '10px', fontSize: '11px' }}>
          {results.map((t) => (
            <div key={t.id} style={{ padding: '4px 0', borderBottom: '1px solid #f1f5f9' }}>
              <strong>{t.icon} {t.name}</strong>
              <div style={{ color: '#64748b' }}>{t.description}</div>
            </div>
          ))}
        </div>
      )}

      {/* CV Profile Snippet for Instant Match Badges */}
      <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, marginBottom: '4px' }}>Your Core CV Text (powers live job card Match %)</label>
      <textarea
        rows={3}
        value={cvText}
        onChange={(e) => setCvText(e.target.value)}
        placeholder="Paste your CV skills & summary once..."
        style={{ width: '100%', boxSizing: 'border-box', padding: '8px', borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '11px', marginBottom: '8px' }}
      />

      <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, marginBottom: '4px' }}>Supabase / ApplyKit Bearer Token</label>
      <input
        type="password"
        value={jwtToken}
        onChange={(e) => setJwtToken(e.target.value)}
        placeholder="Paste JWT from ApplyKit Web Dashboard"
        style={{ width: '100%', boxSizing: 'border-box', padding: '7px', borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '11px', marginBottom: '8px' }}
      />

      <label style={{ display: 'block', fontSize: '11px', fontWeight: 700, marginBottom: '4px' }}>Backend API URL</label>
      <input
        type="url"
        value={backendUrl}
        onChange={(e) => setBackendUrl(e.target.value)}
        style={{ width: '100%', boxSizing: 'border-box', padding: '7px', borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '11px', marginBottom: '8px' }}
      />

      <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', marginBottom: '10px', cursor: 'pointer' }}>
        <input type="checkbox" checked={hideLowMatch} onChange={(e) => setHideLowMatch(e.target.checked)} />
        <span>Dim &lt;50% low-match Upwork jobs (Pro)</span>
      </label>

      <button
        onClick={handleSave}
        style={{
          width: '100%',
          padding: '9px',
          borderRadius: '10px',
          border: 'none',
          background: '#059669',
          color: '#fff',
          fontWeight: 800,
          fontSize: '12px',
          cursor: 'pointer'
        }}
      >
        Save &amp; Sync Extension
      </button>

      {savedBanner && <div style={{ marginTop: '6px', fontSize: '11px', color: '#059669', fontWeight: 700, textAlign: 'center' }}>{savedBanner}</div>}

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '10px', fontSize: '11px' }}>
        <a href={`${backendUrl}/dashboard`} target="_blank" rel="noreferrer" style={{ color: '#059669', fontWeight: 700 }}>
          Open Kanban →
        </a>
        <a href={`${backendUrl}/pricing`} target="_blank" rel="noreferrer" style={{ color: '#0f172a', fontWeight: 700 }}>
          Upgrade Pro (750 KES / $6)
        </a>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(<PopupApp />);
