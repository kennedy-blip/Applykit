import browser from 'webextension-polyfill';
import { saveSettings } from '../lib/api';

// Automatically syncs logged-in user's JWT + Backend URL when they visit the ApplyKit Web Hub
export default defineContentScript({
  matches: [
    'https://applykit-nine.vercel.app/*',
    'https://*.vercel.app/*',
    'http://localhost:8000/*',
    'https://*.onrender.com/*'
  ],
  runAt: 'document_idle',
  main() {
    // Only run on genuine ApplyKit pages (check data-supabase-url or ApplyKit global)
    if (!document.body?.hasAttribute('data-is-pro')) return;

    const syncFromPage = async () => {
      const jwt = window.localStorage.getItem('applykit_jwt') || '';
      const isPro = document.body.getAttribute('data-is-pro') === 'true';
      const origin = window.location.origin;

      await saveSettings({
        backendUrl: origin,
        ...(jwt ? { jwtToken: jwt } : {}),
        isPro
      });

      // Mark DOM so /extension page can display "✓ Extension Connected!"
      document.documentElement.setAttribute('data-applykit-extension-installed', 'true');
      window.dispatchEvent(new CustomEvent('applykit:extension-ready'));
    };

    syncFromPage().catch(() => {});

    window.addEventListener('storage', (e) => {
      if (e.key === 'applykit_jwt') {
        syncFromPage().catch(() => {});
      }
    });

    browser.runtime.onMessage.addListener((msg: any) => {
      if (msg?.type === 'APPLYKIT_PING_WEB') {
        syncFromPage().catch(() => {});
        return Promise.resolve({ connected: true });
      }
      return undefined;
    });
  }
});
