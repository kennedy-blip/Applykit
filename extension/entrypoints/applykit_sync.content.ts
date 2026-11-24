import browser from 'webextension-polyfill';
import { DEFAULT_PERMISSIONS, ExtensionPermissions, saveSettings } from '../lib/api';

// Automatically syncs logged-in user's JWT + Backend URL + Feature Permissions (Allow/Deny) when visiting ApplyKit Web Hub
export default defineContentScript({
  matches: [
    'https://applykit-nine.vercel.app/*',
    'https://*.vercel.app/*',
    'http://localhost:8000/*',
    'https://*.onrender.com/*'
  ],
  runAt: 'document_idle',
  main() {
    if (!document.body?.hasAttribute('data-is-pro')) return;

    const readWebPermissions = (): ExtensionPermissions => {
      try {
        const raw = window.localStorage.getItem('applykit_ext_permissions');
        if (!raw) return DEFAULT_PERMISSIONS;
        const parsed = JSON.parse(raw);
        return {
          matchBadges: parsed.matchBadges !== false,
          scamDetector: parsed.scamDetector !== false,
          proposalInsert: parsed.proposalInsert !== false,
          autoSaveKanban: parsed.autoSaveKanban !== false
        };
      } catch {
        return DEFAULT_PERMISSIONS;
      }
    };

    const syncFromPage = async () => {
      const jwt = window.localStorage.getItem('applykit_jwt') || '';
      const isPro = document.body.getAttribute('data-is-pro') === 'true';
      const origin = window.location.origin;
      const permissions = readWebPermissions();

      await saveSettings({
        backendUrl: origin,
        ...(jwt ? { jwtToken: jwt } : {}),
        isPro,
        permissions
      });

      document.documentElement.setAttribute('data-applykit-extension-installed', 'true');
      window.dispatchEvent(new CustomEvent('applykit:extension-ready'));
    };

    syncFromPage().catch(() => {});

    window.addEventListener('storage', (e) => {
      if (e.key === 'applykit_jwt' || e.key === 'applykit_ext_permissions') {
        syncFromPage().catch(() => {});
      }
    });

    window.addEventListener('applykit:permissions-updated', () => {
      syncFromPage().catch(() => {});
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
