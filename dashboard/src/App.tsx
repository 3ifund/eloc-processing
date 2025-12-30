import { useState, useEffect, useCallback } from 'react';
import { dashboardApi } from './api/client';
import type { EmailRecord, Stats, LogEntry } from './types';
import { StatsPanel } from './components/StatsPanel';
import { EmailList } from './components/EmailList';
import { EmailDetail } from './components/EmailDetail';
import './App.css';

function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [emails, setEmails] = useState<EmailRecord[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<EmailRecord | null>(null);
  const [emailLogs, setEmailLogs] = useState<LogEntry[]>([]);

  const [statsLoading, setStatsLoading] = useState(true);
  const [emailsLoading, setEmailsLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(false);

  const [autoRefresh, setAutoRefresh] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const data = await dashboardApi.getStats();
      setStats(data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    } finally {
      setStatsLoading(false);
    }
  }, []);

  // Fetch emails
  const fetchEmails = useCallback(async () => {
    try {
      setEmailsLoading(true);
      const data = searchQuery
        ? await dashboardApi.searchEmails(searchQuery)
        : await dashboardApi.getEmails({ limit: 50 });
      setEmails(data);
    } catch (error) {
      console.error('Failed to fetch emails:', error);
    } finally {
      setEmailsLoading(false);
    }
  }, [searchQuery]);

  // Fetch logs for selected email
  const fetchEmailLogs = useCallback(async (emailId: string) => {
    try {
      setLogsLoading(true);
      const data = await dashboardApi.getEmailLogs(emailId);
      setEmailLogs(data);
    } catch (error) {
      console.error('Failed to fetch logs:', error);
      setEmailLogs([]);
    } finally {
      setLogsLoading(false);
    }
  }, []);

  // Handle email selection
  const handleSelectEmail = useCallback((email: EmailRecord) => {
    setSelectedEmail(email);
    fetchEmailLogs(email.email_id);
  }, [fetchEmailLogs]);

  // Handle close detail
  const handleCloseDetail = useCallback(() => {
    setSelectedEmail(null);
    setEmailLogs([]);
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchStats();
    fetchEmails();
  }, [fetchStats, fetchEmails]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchStats();
      fetchEmails();
    }, 10000); // Refresh every 10 seconds

    return () => clearInterval(interval);
  }, [autoRefresh, fetchStats, fetchEmails]);

  // Handle search
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchEmails();
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>ELOC Processing Dashboard</h1>
        <div className="header-controls">
          <form onSubmit={handleSearch} className="search-form">
            <input
              type="text"
              placeholder="Search emails, ELOC IDs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <button type="submit">Search</button>
          </form>
          <label className="auto-refresh">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh
          </label>
        </div>
      </header>

      <main className="app-main">
        <aside className="sidebar">
          <StatsPanel stats={stats} loading={statsLoading} />
        </aside>

        <section className="email-section">
          <EmailList
            emails={emails}
            loading={emailsLoading}
            selectedId={selectedEmail?.email_id}
            onSelect={handleSelectEmail}
            onRefresh={fetchEmails}
          />
        </section>

        <section className="detail-section">
          <EmailDetail
            email={selectedEmail}
            logs={emailLogs}
            loading={logsLoading}
            onClose={handleCloseDetail}
          />
        </section>
      </main>

      <footer className="app-footer">
        <span>ELOC Extraction Service v1.0</span>
        <span>
          {autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
        </span>
      </footer>
    </div>
  );
}

export default App;
