import browser from 'webextension-polyfill';
import {
  checkAtsScore,
  checkScamRisk,
  executeBackendTool,
  fetchCurrentUser,
  generateCoverLetter,
  queryVaultRouter,
  saveApplicationToKanban
} from '../lib/api';

export default defineBackground(() => {
  browser.runtime.onInstalled.addListener(() => {
    console.info('[ApplyKit] Multi-browser MV3 extension initialized.');
  });

  browser.runtime.onMessage.addListener((message: any) => {
    switch (message?.type) {
      case 'APPLYKIT_ROUTER':
        return queryVaultRouter(message.query || '', message.context || '', message.url || '');
      case 'APPLYKIT_EXECUTE':
        return executeBackendTool(message.payload);
      case 'APPLYKIT_ATS':
        return checkAtsScore(message.cvText, message.jdText);
      case 'APPLYKIT_COVER_LETTER':
        return generateCoverLetter(message.cvText, message.jdText, message.tone);
      case 'APPLYKIT_SCAM_CHECK':
        return checkScamRisk(message.jobText, message.clientMeta || '');
      case 'APPLYKIT_SAVE_JOB':
        return saveApplicationToKanban(message.payload);
      case 'APPLYKIT_ME':
        return fetchCurrentUser();
      default:
        return undefined;
    }
  });
});
