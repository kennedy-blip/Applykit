import { defineConfig } from 'wxt';

// Single Manifest V3 codebase targeting Chrome, Edge, Brave, Opera & Firefox (NO sidePanel API — uses floating in-page widget + popup)
export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  manifestVersion: 3,
  manifest: {
    name: 'ApplyKit — AI Job & Upwork/LinkedIn Assistant',
    short_name: 'ApplyKit',
    description:
      'Instant ATS Match Score, Scam Detector, Client Reputation Card, 1-Click Proposal Insert & Auto-Sync Kanban for Africa + Global Freelancers.',
    version: '1.0.0',
    permissions: ['storage', 'activeTab'],
    host_permissions: [
      'https://*.upwork.com/*',
      'https://*.linkedin.com/*',
      'http://localhost:8000/*',
      'https://*.onrender.com/*'
    ],
    browser_specific_settings: {
      gecko: {
        id: 'extension@applykit.africa',
        strict_min_version: '109.0'
      }
    }
  }
});
