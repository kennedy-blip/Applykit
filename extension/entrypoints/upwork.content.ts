import browser from 'webextension-polyfill';
import { ExtractedJob, getSettings } from '../lib/api';

declare global {
  interface Window {
    __APPLYKIT_CURRENT_JOB__?: ExtractedJob;
  }
}

function parseUpworkClientStats(): ExtractedJob['clientStats'] {
  const sidebarText =
    document.querySelector('[data-test="about-client-container"]')?.textContent ||
    document.body.innerText ||
    '';

  const verified = /payment method verified/i.test(sidebarText);
  const spentMatch = sidebarText.match(/\$[\d,.]+[KMB]?\s*total spent/i);
  const hiredMatch = sidebarText.match(/(\d+)\s*hires?/i);
  const postedMatch = sidebarText.match(/(\d+)\s*jobs?\s*posted/i);
  const rateMatch = sidebarText.match(/\$[\d.]+\s*\/hr\s*avg/i);

  const hiredCount = hiredMatch ? parseInt(hiredMatch[1], 10) : 0;
  const postedCount = postedMatch ? parseInt(postedMatch[1], 10) : 0;
  let warning: string | undefined;
  if (postedCount >= 10 && hiredCount === 0) {
    warning = `Warning: Client posted ${postedCount} jobs and hired 0 freelancers!`;
  } else if (!verified) {
    warning = 'Caution: Payment method not yet verified.';
  }

  return {
    verified,
    spent: spentMatch ? spentMatch[0] : '$0 spent',
    hiredCount,
    postedCount,
    avgRate: rateMatch ? rateMatch[0] : 'N/A',
    warning
  };
}

function extractUpworkJob(): ExtractedJob {
  const title =
    document.querySelector('h4 span, [data-test="job-title"], h1')?.textContent?.trim() ||
    document.title.replace(/\s*-\s*Upwork.*$/i, '');
  const salary =
    document.querySelector('[data-test="budget"], [data-cy="clock-timelog"]')?.textContent?.trim() || '';
  const description =
    document.querySelector('[data-test="Description"], .job-description')?.textContent?.trim() || '';

  return {
    platform: 'upwork_job',
    title,
    company: 'Upwork Client',
    salary,
    description: description.slice(0, 12000),
    url: window.location.href,
    clientStats: parseUpworkClientStats()
  };
}

function quickKeywordScore(cvText: string, cardText: string): number {
  if (!cvText.trim()) return 72;
  const cvWords = new Set(
    cvText
      .toLowerCase()
      .split(/[^a-z0-9+#.]+/)
      .filter((w) => w.length >= 3)
  );
  const tokens = Array.from(
    new Set(
      cardText
        .toLowerCase()
        .split(/[^a-z0-9+#.]+/)
        .filter((w) => w.length >= 4)
    )
  ).slice(0, 25);
  if (!tokens.length) return 65;
  const hits = tokens.filter((t) => cvWords.has(t)).length;
  return Math.min(98, Math.max(25, Math.round((hits / tokens.length) * 85 + 20)));
}

async function decorateUpworkJobCards() {
  const settings = await getSettings();
  const perms = settings.permissions || { matchBadges: true, scamDetector: true, proposalInsert: true, autoSaveKanban: true };
  if (!perms.matchBadges && !perms.scamDetector) return;

  const cards = document.querySelectorAll<HTMLElement>(
    'article[data-ev-label="search_results_impression"], section.air3-card-section'
  );

  cards.forEach((card) => {
    if (card.dataset.applykitDecorated === '1') return;
    card.dataset.applykitDecorated = '1';

    const text = card.innerText || '';
    const score = quickKeywordScore(settings.cvText, text);
    const isHighScam = /telegram|whatsapp|registration fee|training fee|security deposit|crypto|usdt/i.test(text);
    const isMedScam = !isHighScam && (/payment unverified|0 hires|unpaid test/i.test(text));

    // Pro feature: auto-hide low match (<50%) cards
    if (settings.isPro && settings.hideLowMatch && score < 50) {
      card.style.opacity = '0.28';
      card.title = 'Hidden by ApplyKit Pro (<50% Match)';
    }

    // Highlight skill tags inside Upwork job card green (in CV) or red (missing from CV)
    const cvLower = settings.cvText.toLowerCase();
    if (cvLower.trim()) {
      card.querySelectorAll<HTMLElement>('[data-test="token"], .air3-token').forEach((tokEl) => {
        const skill = (tokEl.textContent || '').trim().toLowerCase();
        if (!skill) return;
        if (cvLower.includes(skill)) {
          tokEl.style.backgroundColor = '#dcfce7';
          tokEl.style.color = '#166534';
          tokEl.style.borderColor = '#86efac';
        } else {
          tokEl.style.backgroundColor = '#ffe4e6';
          tokEl.style.color = '#9f1239';
          tokEl.style.borderColor = '#fda4af';
        }
      });
    }

    const badgeBar = document.createElement('div');
    badgeBar.style.cssText =
      'display:flex;gap:8px;align-items:center;margin:6px 0;font-family:system-ui,sans-serif;font-size:12px;';

    const scoreColor = score >= 75 ? '#059669' : score >= 50 ? '#d97706' : '#e11d48';
    const scamBg = isHighScam ? '#ffe4e6' : isMedScam ? '#fef3c7' : '#ecfdf5';
    const scamFg = isHighScam ? '#be123c' : isMedScam ? '#92400e' : '#047857';
    const scamLabel = isHighScam ? '🚩 Scam Risk: High' : isMedScam ? '⚠️ Scam Risk: Medium' : '🛡️ Scam Risk: Low';

    badgeBar.innerHTML = `
      ${perms.matchBadges ? `<span style="background:${scoreColor};color:#fff;padding:2px 8px;border-radius:999px;font-weight:700;">⚡ Match ${score}%</span>` : ''}
      ${perms.scamDetector ? `<span style="background:${scamBg};color:${scamFg};padding:2px 8px;border-radius:999px;font-weight:600;">${scamLabel}</span>` : ''}
    `;
    card.prepend(badgeBar);
  });
}

function attachApplyAutoSync() {
  document.addEventListener(
    'click',
    (ev) => {
      const target = ev.target as HTMLElement | null;
      const btn = target?.closest('button, a') as HTMLElement | null;
      if (!btn) return;
      const txt = (btn.innerText || '').trim();
      if (/^(apply now|submit a proposal|send for \d+ connects)$/i.test(txt)) {
        getSettings().then((s) => {
          if (s.permissions?.autoSaveKanban === false) return;
          const job = extractUpworkJob();
          browser.runtime
            .sendMessage({
              type: 'APPLYKIT_SAVE_JOB',
              payload: {
                job_title: job.title,
                company: job.company,
                platform: 'Upwork',
                job_url: job.url,
                salary: job.salary,
                status: 'Applied'
              }
            })
            .catch(() => {});
        });
      }
    },
    true
  );
}

export default defineContentScript({
  matches: ['*://*.upwork.com/*'],
  runAt: 'document_idle',
  main() {
    const refresh = () => {
      window.__APPLYKIT_CURRENT_JOB__ = extractUpworkJob();
      decorateUpworkJobCards();
    };
    refresh();
    attachApplyAutoSync();
    const obs = new MutationObserver(() => refresh());
    obs.observe(document.body, { childList: true, subtree: true });

    // Allow widget to insert generated 150-word Cover Letter straight into Upwork's proposal textarea
    window.addEventListener('applykit:insert-proposal', ((e: CustomEvent<string>) => {
      const box = document.querySelector<HTMLTextAreaElement>(
        'textarea[aria-labelledby*="cover_letter"], textarea.air3-textarea, textarea'
      );
      if (box) {
        box.value = e.detail;
        box.dispatchEvent(new Event('input', { bubbles: true }));
        box.focus();
      }
    }) as EventListener);
  }
});
