import api from './axios';

const AI_REQUEST_CONFIG = { timeout: 180000 };

export function getAiSummary(params) {
  return api.get('/api/ai/summary', { params });
}

export function getAiAnalysis(payload) {
  return api.post('/api/ai/analysis', payload, AI_REQUEST_CONFIG);
}

export function askAiAssistant(payload) {
  return api.post('/api/ai/chat', payload, AI_REQUEST_CONFIG);
}
