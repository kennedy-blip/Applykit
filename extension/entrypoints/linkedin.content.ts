import browser from 'webextension-polyfill';
import { ExtractedJob, getSettings } from '../lib/api';

const TECH_KEYWORDS = [
  'python', 'fastapi', 'django', 'javascript', 'typescript', 'react', 'nextjs',
  'nodejs', 'postgresql', 'sql', 'supabase', 'aws', 'docker', 'kubernetes',
  'redis', 'graphql', 'rest', 'figma', 'tailwind', 'seo', 'hubspot', 'excel',
  'powerbi', 'tableau', 'devops', 'ci/cd', 'git', 'agile', 'scrum'
];

function extractLinkedInJob(): ExtractedJob {
  const title =
    document.querySelector(
      '.job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1'
    )?.textContent?.trim() || document.title;
  const company =
    document.querySelector(
      '.job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name'
    )?.textContent?.trim() || 'LinkedIn Employer';
  const description =
    document.querySelector('#job-details, .jobs-description__content')?.textContent?.trim() || '';
  const salary =
    document.querySelector('.job-details-jobs-unified-top-card__job-insight')?.textContent?.trim() || '';

  return {
    platform: 'linkedin_job',
    title,
    company,
    salary,
    description: description.slice(0, 12000),
    url: window.location.href,
    clientStats: {
      verified: true,
      spent: 'Corporate Employer',
      hiredCount: 1,
      postedCount: 1,
      avgRate: salary || 'Market Rate'
    }
  };
}

async function decorateLinkedInJobCards() {
  const settings = await getSettings();
  if (settings.permissions?.matchBadges === false) return;
  const cvLower = settings.cvText.toLowerCase();
  const cards = document.querySelectorAll<HTMLElement>(
    '.job-card-container, .jobs-search-results__list-item'
  );

  cards.forEach((card) => {
    if (card.dataset.applykitDecorated === '1') return;
    card.dataset.applykitDecorated = '1';

    const text = (card.innerText || '').toLowerCase();
    const presentSkills = TECH_KEYWORDS.filter((k) => text.includes(k));
    const matched = presentSkills.filter((k) => cvLower.includes(k));
    const score =
      !cvLower.trim() || presentSkills.length === 0
        ? 76
        : Math.min(97, Math.max(32, Math.round((matched.length / presentSkills.length) * 80 + 20)));

    if (settings.isPro && settings.hideLowMatch && score < 50) {
      card.style.opacity = '0.3';
    }

    const badge = document.createElement('div');
    const bg = score >= 75 ? '#059669' : score >= 50 ? '#d97706' : '#e11d48';
    badge.style.cssText =
      `display:inline-block;margin:4px 0;padding:2px 8px;border-radius:999px;background:${bg};color:#fff;font-size:11px;font-weight:700;font-family:system-ui,sans-serif;`;
    badge.textContent = `⚡ ApplyKit ${score}% Match`;
    card.prepend(badge);
  });
}

async function highlightKeywordsInLinkedInJd(jdContainer: HTMLElement | null) {
  if (!jdContainer || jdContainer.dataset.applykitHighlighted === '1') return;
  const settings = await getSettings();
  if (!settings.cvText.trim()) return;
  jdContainer.dataset.applykitHighlighted = '1';

  const cvLower = settings.cvText.toLowerCase();
  const jdLower = (jdContainer.innerText || '').toLowerCase();
  const foundSkills = TECH_KEYWORDS.filter((k) => jdLower.includes(k));
  if (!foundSkills.length) return;

  const summaryBar = document.createElement('div');
  summaryBar.style.cssText =
    'display:flex;flex-wrap:wrap;gap:6px;padding:10px;margin-bottom:12px;border-radius:10px;background:#f8fafc;border:1px solid #cbd5e1;font-family:system-ui,sans-serif;font-size:11px;';

  foundSkills.forEach((skill) => {
    const isMatched = cvLower.includes(skill);
    const chip = document.createElement('span');
    chip.style.cssText = isMatched
      ? 'background:#dcfce7;color:#166534;padding:2px 8px;border-radius:6px;font-weight:700;'
      : 'background:#ffe4e6;color:#9f1239;padding:2px 8px;border-radius:6px;font-weight:700;';
    chip.textContent = `${isMatched ? '✓' : '✗'} ${skill}`;
    summaryBar.appendChild(chip);
  });

  jdContainer.prepend(summaryBar);
}

function attachEasyApplySync() {
  document.addEventListener(
    'click',
    (ev) => {
      const btn = (ev.target as HTMLElement | null)?.closest('button');
      if (!btn) return;
      const txt = (btn.innerText || '').trim();
      if (/^(easy apply|submit application|apply)$/i.test(txt)) {
        getSettings().then((s) => {
          if (s.permissions?.autoSaveKanban === false) return;
          const job = extractLinkedInJob();
          browser.runtime
            .sendMessage({
              type: 'APPLYKIT_SAVE_JOB',
              payload: {
                job_title: job.title,
                company: job.company,
                platform: 'LinkedIn',
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
  matches: ['*://*.linkedin.com/jobs/*'],
  runAt: 'document_idle',
  main() {
    const sync = () => {
      window.__APPLYKIT_CURRENT_JOB__ = extractLinkedInJob();
      decorateLinkedInJobCards();
      highlightKeywordsInLinkedInJd(
        document.querySelector<HTMLElement>('#job-details, .jobs-description__content')
      );
    };
    sync();
    attachEasyApplySync();
    const obs = new MutationObserver(() => sync());
    obs.observe(document.body, { childList: true, subtree: true });
  }
});
