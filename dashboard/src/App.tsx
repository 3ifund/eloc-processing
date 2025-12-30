import { useState, useEffect, useCallback, useRef } from 'react';
import { dashboardApi } from './api/client';
import type { EmailRecord, Stats, LogEntry } from './types';
import { StatsPanel } from './components/StatsPanel';
import { EmailList } from './components/EmailList';
import { EmailDetail } from './components/EmailDetail';
import './App.css';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [emails, setEmails] = useState<EmailRecord[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<EmailRecord | null>(null);
  const [emailLogs, setEmailLogs] = useState<LogEntry[]>([]);

  const [statsLoading, setStatsLoading] = useState(true);
  const [emailsLoading, setEmailsLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(false);

  const [connected, setConnected] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const eventSourceRef = useRef<EventSource | null>(null);

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

  // Server-Sent Events connection for real-time updates
  useEffect(() => {
    const connectSSE = () => {
      const eventSource = new EventSource(`${API_BASE}/api/dashboard/events`);
      eventSourceRef.current = eventSource;

      eventSource.addEventListener('connected', () => {
        console.log('SSE connected');
        setConnected(true);
      });

      eventSource.addEventListener('email_received', () => {
        // Refresh emails list when new email arrives
        fetchEmails();
        fetchStats();
      });

      eventSource.addEventListener('status_changed', () => {
        // Refresh when status changes
        fetchEmails();
        fetchStats();
      });

      eventSource.addEventListener('processing_complete', () => {
        fetchEmails();
        fetchStats();
      });

      eventSource.onerror = () => {
        console.log('SSE disconnected, reconnecting...');
        setConnected(false);
        eventSource.close();
        // Reconnect after 5 seconds
        setTimeout(connectSSE, 5000);
      };
    };

    connectSSE();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [fetchEmails, fetchStats]);

  // Handle search
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchEmails();
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Document Processing Dashboard</h1>
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
          <span className={`connection-status ${connected ? 'connected' : 'disconnected'}`}>
            {connected ? 'Live' : 'Connecting...'}
          </span>
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
          {connected ? 'Real-time updates active' : 'Reconnecting...'}
        </span>
      </footer>
    </div>
  );
}

export default App;
