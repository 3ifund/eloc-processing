import axios from 'axios';
import type { EmailRecord, Stats, LogEntry } from '../types';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
});

export const dashboardApi = {
  // Get processing statistics
  getStats: async (): Promise<Stats> => {
    const response = await api.get<Stats>('/api/dashboard/stats');
    return response.data;
  },

  // Get list of emails
  getEmails: async (params: {
    limit?: number;
    offset?: number;
    status?: string;
  } = {}): Promise<EmailRecord[]> => {
    const response = await api.get<EmailRecord[]>('/api/dashboard/emails', { params });
    return response.data;
  },

  // Get single email details
  getEmailDetail: async (emailId: string): Promise<EmailRecord> => {
    const response = await api.get<EmailRecord>(`/api/dashboard/emails/${encodeURIComponent(emailId)}`);
    return response.data;
  },

  // Search emails
  searchEmails: async (query: string, limit = 20): Promise<EmailRecord[]> => {
    const response = await api.get<EmailRecord[]>('/api/dashboard/search', {
      params: { q: query, limit },
    });
    return response.data;
  },

  // Get logs
  getLogs: async (params: {
    limit?: number;
    email_id?: string;
    category?: string;
    level?: string;
  } = {}): Promise<LogEntry[]> => {
    const response = await api.get<LogEntry[]>('/api/dashboard/logs', { params });
    return response.data;
  },

  // Get logs for specific email
  getEmailLogs: async (emailId: string, limit = 50): Promise<LogEntry[]> => {
    const response = await api.get<LogEntry[]>(`/api/dashboard/logs/${encodeURIComponent(emailId)}`, {
      params: { limit },
    });
    return response.data;
  },

  // Get status options
  getStatusOptions: async (): Promise<{
    statuses: string[];
    descriptions: Record<string, string>;
  }> => {
    const response = await api.get('/api/dashboard/status-options');
    return response.data;
  },
};

export default dashboardApi;
