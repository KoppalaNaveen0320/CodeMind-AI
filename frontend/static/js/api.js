/**
 * CodeMind AI - Centralized Frontend API Client
 * Connects UI views to backend REST endpoints and manages dynamic state.
 */

const CodeMindAPI = {
  baseUrl: '',

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const token = localStorage.getItem('codemind_auth_token');
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      ...options.headers,
    };
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      const response = await fetch(url, {
        headers,
        ...options,
      });

      if (response.status === 401) {
        const errorBody = await response.json().catch(() => ({}));
        const path = window.location.pathname;
        const isAuthPage = path.includes('/login') || path.includes('/signup') || path.includes('/landing');
        if (!isAuthPage) {
          localStorage.removeItem('codemind_auth_token');
          sessionStorage.clear();
          const cleanPath = window.location.pathname + window.location.search;
          window.location.href = `/login?expired=true&return_to=${encodeURIComponent(cleanPath)}`;
        }
        const error = new Error(errorBody.detail || errorBody.message || 'Session expired. Please sign in again.');
        error.status = 401;
        error.data = errorBody;
        throw error;
      }

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        const error = new Error(errorBody.detail || errorBody.message || `HTTP error ${response.status}`);
        error.status = response.status;
        error.data = errorBody;
        throw error;
      }

      if (response.status === 204 || response.status === 205) {
        return null;
      }

      const text = await response.text();
      return text ? JSON.parse(text) : null;
    } catch (err) {
      console.warn(`[CodeMindAPI] Error requesting ${endpoint}:`, err);
      throw err;
    }
  },

  // Health & Diagnostics
  async getHealth() {
    return this.request('/health');
  },

  async getReady() {
    return this.request('/ready');
  },

  // Authentication
  async register(data) {
    return this.request('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  async login(email, password) {
    return this.request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    });
  },

  async logout() {
    return executeSecureLogout();
  },

  // Session & Security
  async getSessions() {
    return this.request('/api/v1/auth/sessions');
  },

  async getCurrentSession() {
    return this.request('/api/v1/auth/sessions/current');
  },

  async revokeSession(sessionId) {
    return this.request(`/api/v1/auth/sessions/${sessionId}`, { method: 'DELETE' });
  },

  async revokeOtherSessions() {
    return this.request('/api/v1/auth/sessions/revoke-others', { method: 'POST' });
  },

  async updateSessionTimeout(timeoutMinutes) {
    return this.request('/api/v1/settings/session-timeout', {
      method: 'PUT',
      body: JSON.stringify({ timeout_minutes: timeoutMinutes })
    });
  },

  // User Profile
  async getCurrentUser() {
    if (window._codemind_cached_user) return window._codemind_cached_user;
    try {
      const u = await this.request('/api/v1/auth/me');
      window._codemind_cached_user = u;
      return u;
    } catch (e) {
      const u = await this.request('/api/v1/me');
      window._codemind_cached_user = u;
      return u;
    }
  },

  // GitHub Integration
  async getGitHubAuthStatus() {
    return this.request('/api/v1/auth/github/status');
  },

  async getGitHubLoginUrl() {
    return this.request('/api/v1/auth/github/login');
  },

  async getGitHubRepositories() {
    return this.request('/api/v1/auth/github/repositories');
  },

  async disconnectGitHub() {
    return this.request('/api/v1/auth/github/disconnect', { method: 'POST' });
  },

  async getGitHubAccounts() {
    return this.request('/api/v1/auth/github/accounts');
  },

  async connectGitHubPAT(personal_access_token, label = null) {
    return this.request('/api/v1/auth/github/pat', {
      method: 'POST',
      body: JSON.stringify({ personal_access_token, label })
    });
  },

  async getGitHubAccountRepositories(accountId) {
    return this.request(`/api/v1/auth/github/accounts/${accountId}/repositories`);
  },

  async disconnectGitHubAccount(accountId) {
    return this.request(`/api/v1/auth/github/accounts/${accountId}`, { method: 'DELETE' });
  },

  async importRepository(repository_url_or_path, connected_account_id = null, auto_index = true) {
    return this.request('/api/v1/repositories/import', {
      method: 'POST',
      body: JSON.stringify({ repository_url_or_path, connected_account_id, auto_index })
    });
  },

  // Repositories API
  async getRepositories() {
    return this.request('/api/v1/repositories');
  },

  async getRepository(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}`);
  },

  async registerRepository(repoData) {
    return this.request('/api/v1/repositories', {
      method: 'POST',
      body: JSON.stringify(repoData)
    });
  },

  async connectPublicRepository(repository, auto_index = true) {
    return this.request('/api/v1/repositories/connect-public', {
      method: 'POST',
      body: JSON.stringify({ repository, auto_index })
    });
  },

  async uploadFolder(formData) {
    const url = `${this.baseUrl}/api/v1/repositories/upload-folder`;
    const response = await fetch(url, {
      method: 'POST',
      body: formData
    });
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      const error = new Error(errorBody.detail || errorBody.message || `Upload failed with status ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  },

  async deleteRepository(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}`, {
      method: 'DELETE'
    });
  },

  // Indexing Pipeline
  async triggerIndexing(repositoryId, branch = null) {
    return this.request(`/api/v1/repositories/${repositoryId}/index`, {
      method: 'POST',
      body: JSON.stringify({ branch: branch })
    });
  },

  async getIndexingStatus(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}/indexing-status`);
  },

  async getSyncStatus(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}/sync/status`);
  },

  async triggerSync(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}/sync`, { method: 'POST' });
  },

  async getJobDetails(jobId) {
    return this.request(`/api/v1/jobs/${jobId}`);
  },

  async retryJob(jobId) {
    return this.request(`/api/v1/jobs/${jobId}/retry`, { method: 'POST' });
  },

  async cancelJob(jobId) {
    return this.request(`/api/v1/jobs/${jobId}/cancel`, { method: 'POST' });
  },

  // Dashboard Aggregates
  async getDashboardOverview(repositoryId = null) {
    const clientHour = new Date().getHours();
    let url = `/api/v1/dashboard/overview?client_hour=${clientHour}`;
    if (repositoryId) url += `&repository_id=${repositoryId}`;
    return this.request(url);
  },

  // Hybrid RAG & AI Assistant
  async searchCode(repositoryId, searchParams) {
    return this.request(`/api/v1/repositories/${repositoryId}/retrieval/search`, {
      method: 'POST',
      body: JSON.stringify(searchParams)
    });
  },

  async queryAssistant(repositoryId, question, conversationId = null) {
    return this.request(`/api/v1/repositories/${repositoryId}/assistant/query`, {
      method: 'POST',
      body: JSON.stringify({ question: question, conversation_id: conversationId })
    });
  },

  async getAssistantConversations({ repositoryId = null, search = null, limit = 50, offset = 0 } = {}, options = {}) {
    let url = `/api/v1/assistant/conversations?limit=${limit}&offset=${offset}`;
    if (repositoryId) url += `&repository_id=${repositoryId}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    return this.request(url, options);
  },

  async createAssistantConversation({ title = null, repositoryId = null, branch = null } = {}) {
    return this.request('/api/v1/assistant/conversations', {
      method: 'POST',
      body: JSON.stringify({ title, repository_id: repositoryId, branch })
    });
  },

  async getAssistantConversation(conversationId, options = {}) {
    return this.request(`/api/v1/assistant/conversations/${conversationId}`, options);
  },

  async updateAssistantConversation(conversationId, data) {
    return this.request(`/api/v1/assistant/conversations/${conversationId}`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    });
  },

  async deleteAssistantConversation(conversationId) {
    return this.request(`/api/v1/assistant/conversations/${conversationId}`, {
      method: 'DELETE'
    });
  },

  async sendConversationMessage(conversationId, content, { repositoryId = null, branch = null } = {}) {
    return this.request(`/api/v1/assistant/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content, repository_id: repositoryId, branch })
    });
  },

  async streamSSE(url, options = {}, callbacks = {}) {
    const isCallbackFn = typeof callbacks === 'function';
    const onMeta = isCallbackFn ? null : callbacks.onMeta;
    const onStatus = isCallbackFn ? null : callbacks.onStatus;
    const onCitation = isCallbackFn ? null : callbacks.onCitation;
    const onToken = isCallbackFn ? null : callbacks.onToken;
    const onDone = isCallbackFn ? null : callbacks.onDone;
    const onError = isCallbackFn ? null : callbacks.onError;
    const onGeneral = isCallbackFn ? callbacks : callbacks.onEvent;

    const token = localStorage.getItem('codemind_auth_token');
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
      ...(options.headers || {})
    };
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(url, {
      ...options,
      headers,
      signal: options.signal
    });

    if (!res.ok) {
      let errDetail = 'Streaming request failed';
      try {
        const errJson = await res.json();
        errDetail = errJson.detail || errJson.message || errDetail;
      } catch (e) {
        errDetail = await res.text() || errDetail;
      }
      const err = new Error(errDetail);
      err.status = res.status;
      const errorPayload = { error: 'HTTP Error', detail: errDetail, message: errDetail, status: 'failed' };
      if (isCallbackFn) {
        onGeneral('error', errorPayload);
      } else {
        if (onGeneral) onGeneral('error', errorPayload);
        if (onError) onError(errorPayload);
      }
      throw err;
    }

    let reader = null;
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let currentEvent = 'message';

    const abortHandler = () => {
      if (reader) {
        try { reader.cancel(); } catch (_) {}
      }
    };
    if (options.signal) {
      if (options.signal.aborted) {
        throw new DOMException('The user aborted a request.', 'AbortError');
      }
      options.signal.addEventListener('abort', abortHandler, { once: true });
    }

    const dispatchEvent = (event, data) => {
      if (isCallbackFn) {
        onGeneral(event, data);
      } else {
        if (onGeneral) onGeneral(event, data);
        if (event === 'meta' && onMeta) onMeta(data);
        else if (event === 'status' && onStatus) onStatus(data);
        else if (event === 'citation' && onCitation) onCitation(data);
        else if (event === 'token' && onToken) onToken(data);
        else if (event === 'done' && onDone) onDone(data);
        else if (event === 'error' && onError) onError(data);
        else if (onToken && data && data.token) onToken(data);
      }
    };

    const processBufferLines = (lines) => {
      for (let i = 0; i < lines.length; i++) {
        let line = lines[i];
        if (line.endsWith('\r')) line = line.slice(0, -1);
        const trimmed = line.trim();
        if (!trimmed) {
          currentEvent = 'message';
          continue;
        }
        if (line.startsWith('event:')) {
          currentEvent = line.substring(6).trim();
        } else if (line.startsWith('data:')) {
          const dataStr = line.substring(5).trim();
          try {
            const data = JSON.parse(dataStr);
            dispatchEvent(currentEvent, data);
          } catch (jsonErr) {
            if (dataStr === '[DONE]') {
              dispatchEvent('done', { status: 'success' });
            } else {
              dispatchEvent(currentEvent, { text: dataStr, raw: dataStr });
            }
          }
        }
      }
    };

    try {
      reader = res.body.getReader();
      while (true) {
        if (options.signal && options.signal.aborted) {
          try { await reader.cancel(); } catch (_) {}
          throw new DOMException('The user aborted a request.', 'AbortError');
        }

        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep last incomplete piece
        processBufferLines(lines);
      }

      // Process any trailing line in buffer
      if (buffer && buffer.trim()) {
        processBufferLines(buffer.split('\n'));
        buffer = '';
      }
    } catch (err) {
      if (reader) {
        try { await reader.cancel(); } catch (_) {}
      }
      throw err;
    } finally {
      if (options.signal) {
        options.signal.removeEventListener('abort', abortHandler);
      }
      if (reader) {
        try { reader.releaseLock(); } catch (_) {}
      }
    }
  },

  async streamConversationMessage(conversationId, content, opts = {}, callback = null, sig = null) {
    let repositoryId = null;
    let branch = null;
    let cb = callback;
    let signal = sig;

    if (typeof opts === 'function') {
      cb = opts;
      signal = callback;
    } else if (opts && typeof opts === 'object') {
      repositoryId = opts.repositoryId;
      branch = opts.branch;
      if (!cb) cb = opts.onEvent || opts;
      if (!signal) signal = opts.signal;
    }

    return this.streamSSE(`/api/v1/assistant/conversations/${conversationId}/messages/stream`, {
      method: 'POST',
      body: JSON.stringify({ content, repository_id: repositoryId, branch }),
      signal
    }, cb);
  },

  async streamQueryAssistant(repositoryId, question, conversationId = null, opts = {}, callback = null, sig = null) {
    let cb = callback;
    let signal = sig;

    if (typeof opts === 'function') {
      cb = opts;
      signal = callback;
    } else if (opts && typeof opts === 'object') {
      if (!cb) cb = opts.onEvent || opts;
      if (!signal) signal = opts.signal;
    }

    return this.streamSSE(`/api/v1/repositories/${repositoryId}/assistant/stream`, {
      method: 'POST',
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal
    }, cb);
  },

  // Symbol Search & Call Hierarchy (Phase 1)
  async searchSymbols(repositoryId, { q = '', filePath = null, symbolType = null, language = null, exact = false, limit = 25, offset = 0 } = {}) {
    let url = `/api/v1/repositories/${repositoryId}/symbols/search?q=${encodeURIComponent(q)}&exact=${exact}&limit=${limit}&offset=${offset}`;
    if (filePath) url += `&file_path=${encodeURIComponent(filePath)}`;
    if (symbolType) url += `&symbol_type=${encodeURIComponent(symbolType)}`;
    if (language) url += `&language=${encodeURIComponent(language)}`;
    return this.request(url);
  },

  async searchAllSymbols({ q = '', repositoryId = null, filePath = null, symbolType = null, language = null, exact = false, limit = 25, offset = 0 } = {}) {
    let url = `/api/v1/symbols/search?q=${encodeURIComponent(q)}&exact=${exact}&limit=${limit}&offset=${offset}`;
    if (repositoryId) url += `&repository_id=${repositoryId}`;
    if (filePath) url += `&file_path=${encodeURIComponent(filePath)}`;
    if (symbolType) url += `&symbol_type=${encodeURIComponent(symbolType)}`;
    if (language) url += `&language=${encodeURIComponent(language)}`;
    return this.request(url);
  },

  async getSymbolDetails(repositoryId, symbolId) {
    return this.request(`/api/v1/repositories/${repositoryId}/symbols/${symbolId}`);
  },

  async getCallHierarchy(repositoryId, symbolId, { direction = 'both', maxDepth = 2 } = {}) {
    return this.request(`/api/v1/repositories/${repositoryId}/symbols/${symbolId}/call-hierarchy?direction=${direction}&max_depth=${maxDepth}`);
  },

  async getCallHierarchyByName(repositoryId, symbolName, { filePath = null, direction = 'both', maxDepth = 2 } = {}) {
    let url = `/api/v1/repositories/${repositoryId}/calls/hierarchy?symbol_name=${encodeURIComponent(symbolName)}&direction=${direction}&max_depth=${maxDepth}`;
    if (filePath) url += `&file_path=${encodeURIComponent(filePath)}`;
    return this.request(url);
  },

  // Knowledge Graph
  async getRepositoryGraph(repositoryId, limitOrOptions = 150) {
    if (typeof limitOrOptions === 'object' && limitOrOptions !== null) {
      const { limit = 150, nodeType = null, edgeType = null, filePath = null } = limitOrOptions;
      let url = `/api/v1/repositories/${repositoryId}/graph?limit=${limit}`;
      if (nodeType) url += `&node_type=${encodeURIComponent(nodeType)}`;
      if (edgeType) url += `&edge_type=${encodeURIComponent(edgeType)}`;
      if (filePath) url += `&file_path=${encodeURIComponent(filePath)}`;
      return this.request(url);
    }
    return this.request(`/api/v1/repositories/${repositoryId}/graph?limit=${limitOrOptions}`);
  },

  async getNodeNeighbors(repositoryId, nodeId, depthOrOptions = 1) {
    if (typeof depthOrOptions === 'object' && depthOrOptions !== null) {
      const { depth = 1, relationshipType = null, direction = 'both' } = depthOrOptions;
      let url = `/api/v1/repositories/${repositoryId}/graph/nodes/${nodeId}/neighbors?depth=${depth}&direction=${direction}`;
      if (relationshipType) url += `&relationship_type=${encodeURIComponent(relationshipType)}`;
      return this.request(url);
    }
    return this.request(`/api/v1/repositories/${repositoryId}/graph/nodes/${nodeId}/neighbors?depth=${depthOrOptions}`);
  },

  async findGraphPath(repositoryId, startId, endId, maxDepth = 4) {
    return this.request(`/api/v1/repositories/${repositoryId}/graph/paths?start_id=${startId}&end_id=${endId}&max_depth=${maxDepth}`);
  },

  // Change Impact Analysis
  async analyzeChangeImpact(repositoryId, params) {
    return this.request(`/api/v1/repositories/${repositoryId}/impact/analyze`, {
      method: 'POST',
      body: JSON.stringify(params)
    });
  },

  // Code Viewer & File Content
  async getRepositoryFileTree(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}/files/tree`);
  },

  async getFileContent(repositoryId, filePath, highlightStart = null, highlightEnd = null) {
    let url = `/api/v1/repositories/${repositoryId}/files/content?file_path=${encodeURIComponent(filePath)}`;
    if (highlightStart) url += `&highlight_start=${highlightStart}`;
    if (highlightEnd) url += `&highlight_end=${highlightEnd}`;
    return this.request(url);
  },

  async getEmbeddingStatus() {
    return this.request('/api/v1/system/embedding-status');
  },

  // Git History & Diffs
  async getCommits(repositoryId, { branch = null, author = null, search = null, since = null, until = null, page = 1, perPage = 25 } = {}) {
    let url = `/api/v1/repositories/${repositoryId}/commits?page=${page}&per_page=${perPage}`;
    if (branch) url += `&branch=${encodeURIComponent(branch)}`;
    if (author) url += `&author=${encodeURIComponent(author)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (since) url += `&since=${encodeURIComponent(since)}`;
    if (until) url += `&until=${encodeURIComponent(until)}`;
    return this.request(url);
  },

  async getCommitDetail(repositoryId, commitSha, branch = null) {
    let url = `/api/v1/repositories/${repositoryId}/commits/${encodeURIComponent(commitSha)}`;
    if (branch) url += `&branch=${encodeURIComponent(branch)}`;
    return this.request(url);
  },

  // Security Insights
  async getSecurityFindings(repositoryId, branch = null) {
    const query = branch ? `?branch=${encodeURIComponent(branch)}` : '';
    return this.request(`/api/v1/repositories/${repositoryId}/security/findings${query}`);
  },

  async runSecurityScan(repositoryId, branch = null) {
    const query = branch ? `?branch=${encodeURIComponent(branch)}` : '';
    return this.request(`/api/v1/repositories/${repositoryId}/security/scan${query}`, { method: 'POST' });
  },

  async updateSecurityFindingStatus(repositoryId, findingId, status) {
    return this.request(`/api/v1/repositories/${repositoryId}/security/findings/${encodeURIComponent(findingId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: status })
    });
  },

  // Documentation Generation
  async getRepositoryDocs(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}/docs`);
  },

  // User Settings & Profile
  async getSettings() {
    return this.request('/api/v1/settings');
  },

  async updateSettings(settingsData) {
    return this.request('/api/v1/settings', {
      method: 'PUT',
      body: JSON.stringify(settingsData)
    });
  },

  // Notifications
  async getNotifications() {
    return this.request('/api/v1/notifications');
  },

  // Global Search
  async globalSearch(repositoryId, query) {
    return this.request(`/api/v1/repositories/${repositoryId}/search?q=${encodeURIComponent(query)}`);
  }
};

// Track logout in-flight status to prevent race conditions or duplicate clicks
let isLoggingOut = false;

// Updates Security Insights sidebar badge and dashboard quick action from verified repository data
async function updateSecuritySidebarBadge(targetRepoId = null) {
  const badges = document.querySelectorAll('#sidebar-security-badge, .nav-item[data-view="security"] .nav-count');
  const quickSecuritySub = document.getElementById('quick-action-security-sub');

  try {
    let repoId = targetRepoId;
    if (!repoId) {
      const activeRepo = await getActiveRepository();
      repoId = activeRepo ? activeRepo.id : null;
    }

    if (!repoId) {
      badges.forEach(b => {
        b.style.display = 'none';
        b.textContent = '';
      });
      if (quickSecuritySub) quickSecuritySub.textContent = 'Connect repository for security insights';
      return;
    }

    const summary = await CodeMindAPI.getSecurityFindings(repoId);
    if (!summary || !Array.isArray(summary.findings)) {
      badges.forEach(b => {
        b.style.display = 'none';
        b.textContent = '';
      });
      if (quickSecuritySub) quickSecuritySub.textContent = 'All security checks passed';
      return;
    }

    // Actionable open findings are findings not yet reviewed or dismissed
    const openFindings = summary.findings.filter(f => {
      const st = (f.status || '').toUpperCase();
      return st !== 'REVIEWED' && st !== 'DISMISSED';
    });
    const count = openFindings.length;

    if (count > 0) {
      badges.forEach(b => {
        b.textContent = String(count);
        b.style.display = 'grid';
        b.setAttribute('aria-label', `${count} security findings need attention`);
      });
      if (quickSecuritySub) {
        quickSecuritySub.textContent = `${count} ${count === 1 ? 'finding needs' : 'findings need'} attention`;
      }
    } else {
      badges.forEach(b => {
        b.style.display = 'none';
        b.textContent = '';
        b.removeAttribute('aria-label');
      });
      if (quickSecuritySub) {
        if (summary.status === 'indexing_in_progress') {
          quickSecuritySub.textContent = 'Indexing in progress';
        } else if (summary.status === 'no_indexed_files' || summary.total_files === 0) {
          quickSecuritySub.textContent = 'Repository not indexed';
        } else if (summary.status === 'unsupported_files' || summary.files_scanned === 0) {
          quickSecuritySub.textContent = 'No supported files';
        } else {
          quickSecuritySub.textContent = '0 open security findings';
        }
      }
    }
  } catch (err) {
    // Honest unknown/error state - never show fake count
    badges.forEach(b => {
      b.style.display = 'none';
      b.textContent = '';
    });
  }
}
window.updateSecuritySidebarBadge = updateSecuritySidebarBadge;

// UI State Hydration & Operational Data Binding
function initCodeMind() {
  setupMobileMenu();
  setupLogoutControls();
  hydrateUserProfile();
  updateSecuritySidebarBadge();
  hydrateCurrentPage();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initCodeMind);
} else {
  // DOM is already parsed and interactive
  initCodeMind();
}

// Synchronize session expiration and logout across tabs
window.addEventListener('storage', (e) => {
  if (e.key === 'codemind_auth_logout' || (e.key === 'codemind_auth_token' && !e.newValue)) {
    const p = window.location.pathname;
    if (!p.includes('/login') && !p.includes('/signup') && !p.includes('/landing')) {
      window.location.href = '/login?expired=true';
    }
  }
});

// Global delegated listener for reliable logout invocation across dynamic views
document.addEventListener('click', (e) => {
  const logoutTarget = e.target.closest('.header-logout-btn, #header-logout-btn, .sidebar-logout-btn, #sidebar-logout-btn, .logout-action');
  if (logoutTarget) {
    e.preventDefault();
    e.stopPropagation();
    executeSecureLogout();
  }
});

async function executeSecureLogout() {
  if (isLoggingOut) return;
  isLoggingOut = true;

  try {
    const token = localStorage.getItem('codemind_auth_token');
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch('/api/v1/auth/logout', {
      method: 'POST',
      headers: headers,
      credentials: 'same-origin'
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      const msg = errData.detail || errData.message || `Logout failed with status ${res.status}`;
      throw new Error(msg);
    }

    // Only clear client auth tokens and operational storage upon confirmed server logout
    localStorage.removeItem('codemind_auth_token');
    localStorage.removeItem('codemind_active_repo_id');
    try {
      localStorage.setItem('codemind_auth_logout', String(Date.now()));
    } catch (_) {}
    sessionStorage.clear();

    // Reliable top-level navigation to existing login route
    window.location.href = '/login';
    setTimeout(() => {
      window.location.replace('/login');
    }, 120);

  } catch (err) {
    isLoggingOut = false;
    console.error('[CodeMind] Error during logout:', err);
    // Explicit user feedback; preserve state and do NOT leave user on blank dashboard
    alert('Logout failed: ' + (err.message || 'Could not contact server. Please try again.'));
  }
}

function setupLogoutControls() {
  // 1. Top-right Header Logout Button
  const headerLogoutBtns = document.querySelectorAll('.header-logout-btn, #header-logout-btn');
  headerLogoutBtns.forEach(btn => {
    // Avoid attaching multiple duplicate listeners
    if (!btn.dataset.logoutBound) {
      btn.dataset.logoutBound = 'true';
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        executeSecureLogout();
      });
    }
  });

  // 2. Bottom-left Sidebar Dropdown Logout Option
  const sidebarLogoutBtns = document.querySelectorAll('.sidebar-logout-btn, #sidebar-logout-btn, .logout-action');
  sidebarLogoutBtns.forEach(btn => {
    if (!btn.dataset.logoutBound) {
      btn.dataset.logoutBound = 'true';
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        executeSecureLogout();
      });
    }
  });

  // 3. Bottom-left Profile Dropdown Toggle Logic
  const profileContainer = document.querySelector('.sidebar-bottom .profile, #sidebar-profile-container');
  const triggerBtn = document.querySelector('.profile-dropdown-trigger, #sidebar-profile-trigger');
  const dropdownMenu = document.querySelector('.profile-dropdown-menu, #sidebar-profile-menu');
  const profileSection = document.querySelector('.sidebar-profile-section') || profileContainer?.parentElement;

  if (profileContainer && dropdownMenu) {
    const openMenu = () => {
      dropdownMenu.classList.add('active');
      profileContainer.classList.add('menu-open');
      if (profileSection) profileSection.classList.add('open');
      if (triggerBtn) triggerBtn.setAttribute('aria-expanded', 'true');
      profileContainer.setAttribute('aria-expanded', 'true');
    };

    const closeMenu = () => {
      dropdownMenu.classList.remove('active');
      profileContainer.classList.remove('menu-open');
      if (profileSection) profileSection.classList.remove('open');
      if (triggerBtn) triggerBtn.setAttribute('aria-expanded', 'false');
      profileContainer.setAttribute('aria-expanded', 'false');
    };

    const toggleMenu = (e) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      const isOpen = dropdownMenu.classList.contains('active');
      if (isOpen) {
        closeMenu();
      } else {
        openMenu();
      }
    };

    if (triggerBtn && !triggerBtn.dataset.triggerBound) {
      triggerBtn.dataset.triggerBound = 'true';
      triggerBtn.addEventListener('click', toggleMenu);
    }

    if (!profileContainer.dataset.profileBound) {
      profileContainer.dataset.profileBound = 'true';
      profileContainer.addEventListener('click', (e) => {
        if (!dropdownMenu.contains(e.target)) {
          toggleMenu(e);
        }
      });

      profileContainer.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (!dropdownMenu.contains(e.target)) {
            e.preventDefault();
            toggleMenu(e);
          }
        } else if (e.key === 'Escape' && dropdownMenu.classList.contains('active')) {
          e.preventDefault();
          closeMenu();
          profileContainer.focus();
        }
      });
    }

    // Close when clicking outside
    document.addEventListener('click', (e) => {
      if (dropdownMenu.classList.contains('active')) {
        const wrap = profileSection || profileContainer;
        if (!wrap.contains(e.target)) {
          closeMenu();
        }
      }
    });

    // Keyboard support: Escape closes menu
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && dropdownMenu.classList.contains('active')) {
        closeMenu();
        if (triggerBtn) triggerBtn.focus();
        else profileContainer.focus();
      }
    });
  }
}

function setupMobileMenu() {
  const menuBtn = document.querySelector('.menu-btn');
  const sidebar = document.querySelector('.sidebar');
  const closeBtn = document.querySelector('.mobile-close');

  if (menuBtn && sidebar) {
    menuBtn.addEventListener('click', () => sidebar.classList.add('open'));
  }
  if (closeBtn && sidebar) {
    closeBtn.addEventListener('click', () => sidebar.classList.remove('open'));
  }
}

async function hydrateUserProfile() {
  try {
    const user = await CodeMindAPI.getCurrentUser();
    if (!user) return;

    const profileNameEls = document.querySelectorAll('#sidebar-profile-name, #menu-profile-name, .sidebar .profile-info strong');
    const profileEmailEls = document.querySelectorAll('#sidebar-profile-email, #menu-profile-email, .sidebar .profile-info small');
    const avatarEls = document.querySelectorAll('.sidebar .avatar, .topbar .avatar, .avatar-small');

    if (user.full_name) {
      profileNameEls.forEach(el => el.textContent = user.full_name);
    } else if (user.email) {
      const derived = user.email.split('@')[0];
      profileNameEls.forEach(el => el.textContent = derived);
    }

    if (user.email) {
      profileEmailEls.forEach(el => el.textContent = user.email);
    }
    if (user.avatar_initials) {
      avatarEls.forEach(el => el.textContent = user.avatar_initials);
    }
  } catch (err) {
    // Graceful fallback
  }
}

async function hydrateCurrentPage() {
  const path = window.location.pathname;
  const isDashboard = path === '/' || path.includes('dashboard') || document.getElementById('view-overview');
  const isRepositories = (path.includes('repositories') && !path.includes('modal'));
  const isModal = path.includes('repositories_modal') || document.getElementById('view-modal');
  const isAssistant = path.includes('assistant');
  const isImpact = path.includes('impact');
  const isDependencies = path.includes('dependencies');
  const isCodeViewer = path.includes('code_viewer') || path.includes('code-viewer') || path === '/code' || path.startsWith('/code/');
  const isGitHistory = path.includes('git_history') || path.includes('history') || document.getElementById('view-history');
  const isSecurity = path.includes('security') || document.getElementById('view-security');
  const isDocs = path.includes('documentation') || path.includes('documents') || path.includes('docs') || document.getElementById('view-docs') || document.getElementById('docs-modules-container');
  const isSettings = path.includes('settings') || document.getElementById('view-settings');

  let activeRepo = null;
  try {
    activeRepo = await getActiveRepository();
    await hydrateGlobalTopbar(activeRepo);
  } catch (err) {
    console.warn('[CodeMind] Topbar hydration notice:', err);
  }

  if (isModal || isRepositories) {
    try { await hydrateRepositoriesView(); } catch (e) { console.error('Error hydrating repositories:', e); }
    try { await initConnectGitHubModal(); } catch (e) { console.error('Error initializing modal:', e); }
  }
  if (isDashboard) {
    try { await hydrateDashboardView(); } catch (e) { console.error('Error hydrating dashboard:', e); }
  }
  if (isAssistant) {
    try { await hydrateAssistantView(); } catch (e) { console.error('Error hydrating assistant:', e); }
  }
  if (isImpact) {
    try { await hydrateImpactAnalysisView(); } catch (e) { console.error('Error hydrating impact:', e); }
  }
  if (isDependencies) {
    try { await hydrateDependenciesView(); } catch (e) { console.error('Error hydrating dependencies:', e); }
  }
  if (isCodeViewer) {
    try { await hydrateCodeViewerView(); } catch (e) { console.error('Error hydrating code viewer:', e); }
  }
  if (isGitHistory) {
    try { await hydrateGitHistoryView(); } catch (e) { console.error('Error hydrating git history:', e); }
  }
  if (isSecurity) {
    try { await hydrateSecurityInsightsView(); } catch (e) { console.error('Error hydrating security:', e); }
  }
  if (isDocs) {
    try { await hydrateDocsView(); } catch (e) { console.error('Error hydrating docs:', e); }
  }
  if (isSettings) {
    try { await hydrateSettingsView(); } catch (e) { console.error('Error hydrating settings:', e); }
  }
}

// --- Repositories View & Modal Controller ---
let allLoadedRepos = [];

async function hydrateRepositoriesView() {
  const container = document.getElementById('repositories-container') || document.querySelector('.table-card');
  const filterRow = document.getElementById('repo-filter-row');
  if (!container) return;

  try {
    const authStatus = await CodeMindAPI.getGitHubAuthStatus();
    const repos = await CodeMindAPI.getRepositories();
    allLoadedRepos = repos || [];

    if (!repos || repos.length === 0) {
      if (filterRow) filterRow.style.display = 'none';

      const configPill = authStatus && authStatus.configured
        ? `<span class="empty-state-config-badge configured"><span class="dot"></span>GitHub OAuth Configured</span>`
        : `<span class="empty-state-config-badge unconfigured"><span class="dot"></span>OAuth Not Configured in backend/.env</span>`;

      container.innerHTML = `
        <div class="empty-state-card">
          <div class="empty-state-illustration">
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
              <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>
              <path d="M9 18c-4.51 2-5-2-7-2"/>
            </svg>
          </div>
          <h2 class="empty-state-title">Connect your first repository</h2>
          <p class="empty-state-desc">
            Connect an authorized GitHub repository to start AST parsing, dependency mapping, knowledge graph synthesis, and change-impact prediction.
          </p>
          <div>
            ${configPill}
          </div>
          <div class="empty-state-actions">
            <button type="button" class="btn btn-primary" id="btn-empty-connect">
              <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>
                <path d="M9 18c-4.51 2-5-2-7-2"/>
              </svg>
              <span>Connect GitHub</span>
            </button>
            <a href="/documentation" class="btn btn-secondary">
              <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>
              </svg>
              <span>Learn how indexing works</span>
            </a>
          </div>
          <div class="empty-state-features">
            <div class="feature-pill">
              <span class="feature-pill-icon">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m18 16 4-4-4-4"/><path d="m6 8-4 4 4 4"/><path d="m14.5 4-5 16"/></svg>
              </span>
              <div>
                <strong>AST Parsing & Code Analysis</strong>
                <small>Extracts functions, classes, and types using Tree-sitter grammars.</small>
              </div>
            </div>
            <div class="feature-pill">
              <span class="feature-pill-icon">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="m8.6 7.5 2.2 7M15.4 7.5l-2.2 7M9 6h6"/></svg>
              </span>
              <div>
                <strong>Knowledge Graph Synthesis</strong>
                <small>Maps callers, callees, imports, and cross-file dependencies.</small>
              </div>
            </div>
            <div class="feature-pill">
              <span class="feature-pill-icon">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 3v4M21 12h-4M12 21v-4M3 12h4"/></svg>
              </span>
              <div>
                <strong>Change-Impact Prediction</strong>
                <small>Simulates PR risks and blast-radius before merging changes.</small>
              </div>
            </div>
            <div class="feature-pill">
              <span class="feature-pill-icon">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>
              </span>
              <div>
                <strong>Security Vulnerability Scan</strong>
                <small>Scans for leaked credentials, SQLi, and OWASP top vulnerabilities.</small>
              </div>
            </div>
          </div>
        </div>
      `;

      const emptyConnectBtn = document.getElementById('btn-empty-connect');
      if (emptyConnectBtn) {
        emptyConnectBtn.addEventListener('click', () => {
          openConnectModal();
        });
      }
      return;
    }

    // Repositories are present: render table
    if (filterRow) filterRow.style.display = 'flex';
    renderRepositoriesTable(repos);

    // Setup search filter
    const searchInput = document.getElementById('repo-search-input');
    const statusFilter = document.getElementById('repo-status-filter');

    if (searchInput) {
      searchInput.oninput = () => filterRepositoriesList();
    }
    if (statusFilter) {
      statusFilter.onchange = () => filterRepositoriesList();
    }

  } catch (err) {
    container.innerHTML = `
      <div class="empty-state-card">
        <h3 class="empty-state-title" style="color: var(--danger);">Unable to Load Repositories</h3>
        <p class="empty-state-desc">${escapeHtml(err.message || 'Error communicating with backend service.')}</p>
        <button type="button" class="btn btn-secondary" onclick="window.location.reload()">Retry</button>
      </div>
    `;
  }
}

function cleanEvidenceSnippet(ev) {
  if (!ev) return '';
  let str = String(ev).trim();
  if (str.startsWith('Found in ')) {
    str = str.substring(9).trim();
  }
  return str;
}

function renderTechStackCell(repo) {
  const ts = repo.tech_stack || {};
  const fe = ts.frontend || [];
  const be = ts.backend || [];
  const db = ts.database || [];
  const infra = ts.infrastructure || [];

  const hasFe = fe.length > 0;
  const hasBe = be.length > 0;
  const hasDb = db.length > 0;
  const hasInfra = infra.length > 0;

  if (!hasFe && !hasBe && !hasDb && !hasInfra) {
    const fallbackLang = repo.primary_language;
    if (fallbackLang) {
      return `
        <div class="tech-stack-cell">
          <div class="tech-stack-groups">
            <div class="tech-group-row">
              <span class="tech-cat-tag frontend">FE</span>
              <div class="tech-badges-wrap">
                <span class="tech-pill tech-frontend">${escapeHtml(fallbackLang)}</span>
              </div>
            </div>
            <div class="tech-group-row">
              <span class="tech-cat-tag backend">BE</span>
              <div class="tech-badges-wrap">
                <span class="tech-pill tech-none">Not detected</span>
              </div>
            </div>
          </div>
        </div>
      `;
    }
    return `
      <div class="tech-stack-cell">
        <span class="tech-pill tech-none">Not detected</span>
      </div>
    `;
  }

  const maxVisiblePerGroup = 3;

  function renderGroupPills(items, pillClass) {
    if (!items || items.length === 0) {
      return `<span class="tech-pill tech-none">Not detected</span>`;
    }
    const visible = items.slice(0, maxVisiblePerGroup);
    const hiddenCount = items.length - maxVisiblePerGroup;
    let html = visible.map(it => {
      const ev = (it.evidence && it.evidence.length) ? it.evidence[0] : (it.evidence_file || '');
      const title = `${escapeHtml(it.name)}${it.version ? ' ' + escapeHtml(it.version) : ''} (${escapeHtml(it.category || 'tech')}${ev ? ' · ' + escapeHtml(ev) : ''})`;
      return `<span class="tech-pill ${pillClass}" title="${title}">${escapeHtml(it.name)}</span>`;
    }).join('');

    if (hiddenCount > 0) {
      html += `<span class="tech-pill tech-more" onclick="openTechStackModal(${repo.id})" title="${hiddenCount} more technologies">+${hiddenCount}</span>`;
    }
    return html;
  }

  let html = `
    <div class="tech-stack-cell">
      <div class="tech-stack-groups">
        <div class="tech-group-row">
          <span class="tech-cat-tag frontend" title="Frontend technologies">
            <svg class="icon" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span>Frontend</span>
          </span>
          <div class="tech-badges-wrap">
            ${renderGroupPills(fe, 'tech-frontend')}
          </div>
        </div>

        <div class="tech-group-row">
          <span class="tech-cat-tag backend" title="Backend technologies">
            <svg class="icon" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
            <span>Backend</span>
          </span>
          <div class="tech-badges-wrap">
            ${renderGroupPills(be, 'tech-backend')}
          </div>
        </div>
  `;

  if (hasDb) {
    html += `
        <div class="tech-group-row">
          <span class="tech-cat-tag db" title="Database & Storage">
            <svg class="icon" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
            <span>Database</span>
          </span>
          <div class="tech-badges-wrap">
            ${renderGroupPills(db, 'tech-db')}
          </div>
        </div>
    `;
  }

  if (hasInfra) {
    html += `
        <div class="tech-group-row">
          <span class="tech-cat-tag infra" title="Infrastructure & Deployment">
            <svg class="icon" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            <span>Infra</span>
          </span>
          <div class="tech-badges-wrap">
            ${renderGroupPills(infra, 'tech-infra')}
          </div>
        </div>
    `;
  }

  html += `
      </div>
      <button type="button" class="tech-details-btn" onclick="openTechStackModal(${repo.id})" title="View full technology stack details and evidence for ${escapeHtml(repo.name || '')}">
        <span>Details & evidence</span>
        <svg class="icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true" focusable="false"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
      </button>
    </div>
  `;

  return html;
}

window.openTechStackModal = async function(repoId) {
  let repo = (typeof allLoadedRepos !== 'undefined' ? allLoadedRepos : []).find(r => r.id === repoId);
  if (!repo) {
    try {
      repo = await CodeMindAPI.getRepository(repoId);
    } catch (e) {
      repo = null;
    }
  }
  if (!repo) return;

  const modal = document.getElementById('tech-stack-details-modal');
  const title = document.getElementById('tech-stack-modal-title');
  const subtitle = document.getElementById('tech-stack-modal-subtitle');
  const body = document.getElementById('tech-stack-modal-body');

  if (title) title.textContent = `${repo.full_name || repo.name} — Technology Stack`;
  if (subtitle) subtitle.textContent = `Evidence-based detection across ${formatNumber(repo.files_count || 0)} indexed files`;

  if (body) {
    const ts = repo.tech_stack || {};
    const fe = ts.frontend || [];
    const be = ts.backend || [];
    const db = ts.database || [];
    const infra = ts.infrastructure || [];
    const languages = ts.languages || [];

    function renderSection(title, iconSvg, items, emptyText, catClass) {
      return `
        <div class="tech-modal-section">
          <div class="tech-modal-sec-head">
            ${iconSvg}
            <strong>${escapeHtml(title)}</strong>
            <span class="tech-count-badge">${items.length}</span>
          </div>
          <div class="tech-modal-sec-items">
            ${items.length === 0 ? `
              <div class="tech-empty-notice">${escapeHtml(emptyText)}</div>
            ` : items.map(it => {
              const confPercent = typeof it.confidence === 'number'
                ? Math.round(it.confidence * 100)
                : (it.confidence === 'high' ? 95 : (it.confidence === 'medium' ? 80 : 65));
              const isHigh = confPercent >= 85;
              const rawEvidence = Array.isArray(it.evidence) ? it.evidence : (it.evidence_file ? [it.evidence_file] : []);
              return `
              <div class="tech-evidence-card">
                <div class="tech-card-header-row">
                  <div class="tech-card-identity">
                    <span class="tech-card-name ${catClass}">${escapeHtml(it.name)}</span>
                    ${it.type ? `<span class="tech-type-pill">${escapeHtml(it.type.toUpperCase())}</span>` : ''}
                    ${it.version ? `<code class="tech-version-pill">${escapeHtml(it.version)}</code>` : ''}
                  </div>
                  <div class="tech-card-confidence">
                    <span class="tech-confidence-badge ${isHigh ? 'conf-high' : 'conf-med'}" title="Confidence: ${confPercent}%">
                      <svg class="icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true" focusable="false"><polyline points="20 6 9 17 4 12"/></svg>
                      ${confPercent}% verified
                    </span>
                  </div>
                </div>
                <div class="tech-card-evidence">
                  ${rawEvidence.length > 0 ? `
                    <span class="tech-evidence-icon-label">
                      <svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                      Evidence:
                    </span>
                    <div class="tech-evidence-tags">
                      ${rawEvidence.map(e => `<code class="tech-evidence-path" title="${escapeHtml(e)}">${escapeHtml(cleanEvidenceSnippet(e))}</code>`).join('')}
                    </div>
                  ` : `
                    <span class="tech-evidence-inferred">
                      <svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                      Detected from repository source file extensions
                    </span>
                  `}
                </div>
              </div>
            `;
            }).join('')}
          </div>
        </div>
      `;
    }

    const feSvg = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0284c7" stroke-width="2" aria-hidden="true" focusable="false"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>';
    const beSvg = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#4f46e5" stroke-width="2" aria-hidden="true" focusable="false"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>';
    const dbSvg = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2" aria-hidden="true" focusable="false"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>';
    const infraSvg = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9333ea" stroke-width="2" aria-hidden="true" focusable="false"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>';

    let modalHtml = `
      <div class="tech-modal-grid">
        ${renderSection('Frontend Technologies', feSvg, fe, 'No frontend technologies detected in repository evidence.', 'tech-frontend')}
        ${renderSection('Backend Technologies', beSvg, be, 'No backend technologies detected in repository evidence.', 'tech-backend')}
        ${renderSection('Database & Storage', dbSvg, db, 'No database configurations or dependencies detected.', 'tech-db')}
        ${renderSection('Infrastructure & DevOps', infraSvg, infra, 'No container or infrastructure manifests detected.', 'tech-infra')}
      </div>
    `;

    if (languages.length > 0) {
      modalHtml += `
        <div class="tech-modal-languages" style="margin-top: 16px;">
          <strong>Languages Detected:</strong>
          <div class="tech-badges-wrap">
            ${languages.map(l => `<span class="tech-pill tech-frontend">${escapeHtml(l)}</span>`).join('')}
          </div>
        </div>
      `;
    }

    body.innerHTML = modalHtml;
  }

  if (modal) {
    modal.classList.remove('hidden');
    document.body.classList.add('modal-open');
    const closeBtn = modal.querySelector('.modal-close-btn');
    if (closeBtn) closeBtn.focus();
  }
};

window.closeTechStackModal = function() {
  const modal = document.getElementById('tech-stack-details-modal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.classList.remove('modal-open');
  }
};

window.openActiveSessionsModal = async function() {
  let modal = document.getElementById('active-sessions-modal');
  if (!modal) {
    const layer = document.createElement('div');
    layer.className = 'modal-layer hidden';
    layer.id = 'active-sessions-modal';
    layer.setAttribute('role', 'dialog');
    layer.setAttribute('aria-modal', 'true');
    layer.setAttribute('aria-labelledby', 'active-sessions-modal-title');
    layer.innerHTML = `
      <div class="modal-backdrop" id="active-sessions-backdrop-close" onclick="closeActiveSessionsModal()" aria-label="Close active sessions dialog"></div>
      <section class="setup-modal active-sessions-modal">
        <div class="modal-head">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="repo-logo" style="background: rgba(99, 102, 241, 0.12); color: #4f46e5; width: 36px; height: 36px; border-radius: 8px; display: grid; place-items: center;">
              <svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>
            </span>
            <div>
              <strong id="active-sessions-modal-title">Active Sessions</strong>
              <small id="active-sessions-modal-subtitle">Persistent session tracking across devices, browsers, and IP addresses</small>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 10px;">
            <button type="button" class="btn btn-secondary btn-sm" id="btn-revoke-other-sessions" style="display: inline-flex; align-items: center; gap: 5px; font-size: 11px;">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>Revoke other sessions</span>
            </button>
            <button type="button" class="icon-btn modal-close-btn" id="btn-close-active-sessions-modal" onclick="closeActiveSessionsModal()" aria-label="Close modal">
              <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m6 6 12 12M18 6 6 18" /></svg>
            </button>
          </div>
        </div>
        <div class="active-sessions-modal-body" id="active-sessions-list-container">
          <div style="padding: 24px; text-align: center; color: var(--muted); font-size: 11.5px;">Loading active sessions...</div>
        </div>
      </section>
    `;
    document.body.appendChild(layer);
    modal = layer;
  }

  modal.classList.remove('hidden');
  document.body.classList.add('modal-open');
  if (typeof window.loadActiveSessions === 'function') {
    await window.loadActiveSessions();
  }
  const closeBtn = document.getElementById('btn-close-active-sessions-modal') || modal.querySelector('.modal-close-btn');
  if (closeBtn) closeBtn.focus();
};

window.closeActiveSessionsModal = function() {
  const modal = document.getElementById('active-sessions-modal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.classList.remove('modal-open');
  }
  const triggerBtn = document.getElementById('btn-toggle-active-sessions');
  if (triggerBtn) triggerBtn.focus();
};

// Global escape key listener to dismiss modals
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    const techModal = document.getElementById('tech-stack-details-modal');
    if (techModal && !techModal.classList.contains('hidden')) {
      window.closeTechStackModal();
    }
    const sessionModal = document.getElementById('active-sessions-modal');
    if (sessionModal && !sessionModal.classList.contains('hidden')) {
      window.closeActiveSessionsModal();
    }
  }
});

function renderTechStackOverview(techStack, repoId = null) {
  if (!techStack || (
    (!techStack.frontend || techStack.frontend.length === 0) &&
    (!techStack.backend || techStack.backend.length === 0) &&
    (!techStack.database || techStack.database.length === 0) &&
    (!techStack.infrastructure || techStack.infrastructure.length === 0)
  )) {
    return `
      <div style="padding: 24px 16px; text-align: center; color: var(--muted); font-size: 11.5px; width: 100%;">
        No framework manifests or dependencies detected yet. Re-index repository to scan code.
      </div>
    `;
  }

  const categories = [
    { key: 'frontend', name: 'Frontend Stack', code: 'FE', badgeClass: 'badge-cat-fe', itemBadgeClass: 'badge-tech-fe', emptyText: 'No frontend frameworks or client code detected' },
    { key: 'backend', name: 'Backend Stack', code: 'BE', badgeClass: 'badge-cat-be', itemBadgeClass: 'badge-tech-be', emptyText: 'No backend frameworks or server entry points detected' },
    { key: 'database', name: 'Database & ORM', code: 'DB', badgeClass: 'badge-cat-db', itemBadgeClass: 'badge-tech-db', emptyText: 'No database or ORM dependencies detected' },
    { key: 'infrastructure', name: 'DevOps & Infra', code: 'INFRA', badgeClass: 'badge-cat-infra', itemBadgeClass: 'badge-tech-infra', emptyText: 'No container or deployment manifests detected' },
  ];

  function cleanEvidenceSnippet(ev) {
    if (!ev) return '';
    let str = String(ev).trim();
    if (str.startsWith('Found in ')) {
      str = str.substring(9).trim();
    }
    return str;
  }

  return `
    <div class="tech-overview-grid">
      ${categories.map(cat => {
        const items = (techStack[cat.key] || []);
        return `
          <div class="tech-overview-col">
            <div class="tech-overview-col-head">
              <span class="badge-cat ${cat.badgeClass}">${cat.code}</span>
              <strong>${cat.name}</strong>
              <span class="badge ${items.length > 0 ? 'badge-primary' : 'badge-neutral'}" style="font-size: 7.5px; padding: 1px 6px;">${items.length}</span>
            </div>
            <div class="tech-overview-col-body">
              ${items.length === 0 ? `
                <div class="tech-empty-state-notice">${cat.emptyText}</div>
              ` : items.map(item => {
                const confRaw = item.confidence;
                const isHigh = confRaw === 'high' || confRaw === 1 || confRaw === 1.0 || (typeof confRaw === 'number' && confRaw >= 0.8);
                const confColor = isHigh ? '#059669' : '#d97706';
                const confBg = isHigh ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)';
                const confText = typeof confRaw === 'string' ? confRaw.toUpperCase() : (isHigh ? 'HIGH' : 'MEDIUM');
                const rawEvidence = item.evidence || [];
                const firstEv = rawEvidence.length > 0 ? cleanEvidenceSnippet(rawEvidence[0]) : '';
                const fullTooltip = rawEvidence.map(cleanEvidenceSnippet).join('; ');
                return `
                  <div class="tech-overview-item">
                    <div class="tech-item-row">
                      <span class="badge-tech ${cat.itemBadgeClass}">${escapeHtml(item.name)}</span>
                      ${item.type ? `<small style="font-size:7.5px; color:var(--muted); text-transform:uppercase;">${escapeHtml(item.type)}</small>` : ''}
                      ${confRaw !== undefined && confRaw !== null ? `<span style="font-size:7px; margin-left:auto; padding:1px 5px; border-radius:10px; background:${confBg}; color:${confColor}; font-weight:600;">${escapeHtml(confText)}</span>` : ''}
                    </div>
                    ${firstEv ? `
                      <div class="tech-evidence-line" title="Evidence: ${escapeHtml(fullTooltip)}">
                        <svg class="icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                        <span>Evidence: <code>${escapeHtml(firstEv)}</code>${rawEvidence.length > 1 ? ` <span style="color:var(--muted); font-size:7px;">+${rawEvidence.length - 1}</span>` : ''}</span>
                      </div>
                    ` : ''}
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function updateTechStackScrollButtons() {
  const container = document.getElementById('dashboard-tech-stack-container');
  const prevBtn = document.getElementById('tech-scroll-prev');
  const nextBtn = document.getElementById('tech-scroll-next');
  const controls = document.getElementById('tech-scroll-controls');
  if (!container || !prevBtn || !nextBtn) return;

  const scrollLeft = Math.ceil(container.scrollLeft);
  const maxScrollLeft = Math.max(0, container.scrollWidth - container.clientWidth);
  const isOverflowing = maxScrollLeft > 4;

  if (controls) {
    controls.style.display = isOverflowing ? 'inline-flex' : 'none';
  }

  if (!isOverflowing) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    return;
  }

  prevBtn.disabled = scrollLeft <= 2;
  nextBtn.disabled = scrollLeft >= maxScrollLeft - 2;
}

function scrollTechStack(direction) {
  const container = document.getElementById('dashboard-tech-stack-container');
  if (!container) return;

  const col = container.querySelector('.tech-overview-col');
  const colWidth = col ? (col.getBoundingClientRect().width + 12) : 180;
  const scrollAmount = Math.max(colWidth, Math.round(container.clientWidth * 0.75));

  container.scrollBy({
    left: direction === 'left' ? -scrollAmount : scrollAmount,
    behavior: 'smooth'
  });
}

function initTechStackScrollControls() {
  const prevBtn = document.getElementById('tech-scroll-prev');
  const nextBtn = document.getElementById('tech-scroll-next');
  const container = document.getElementById('dashboard-tech-stack-container');

  if (prevBtn && !prevBtn._hasClickListener) {
    prevBtn._hasClickListener = true;
    prevBtn.addEventListener('click', (e) => {
      e.preventDefault();
      scrollTechStack('left');
    });
  }
  if (nextBtn && !nextBtn._hasClickListener) {
    nextBtn._hasClickListener = true;
    nextBtn.addEventListener('click', (e) => {
      e.preventDefault();
      scrollTechStack('right');
    });
  }

  if (container && !container._hasScrollListener) {
    container._hasScrollListener = true;
    container.addEventListener('scroll', () => {
      updateTechStackScrollButtons();
    }, { passive: true });
  }

  if (!window._techStackResizeBound) {
    window._techStackResizeBound = true;
    window.addEventListener('resize', () => {
      updateTechStackScrollButtons();
    }, { passive: true });
  }

  updateTechStackScrollButtons();
}

window.updateTechStackScrollButtons = updateTechStackScrollButtons;
window.scrollTechStack = scrollTechStack;
window.initTechStackScrollControls = initTechStackScrollControls;

function renderRepositoriesTable(repos) {
  const container = document.getElementById('repositories-container') || document.querySelector('.table-card');
  if (!container) return;

  const headHtml = `
    <section class="card table-card" id="repo-table-card">
      <div class="table-head">
        <span class="col-repo">Repository</span>
        <span class="col-tech">Technology Stack</span>
        <span class="col-status">Status</span>
        <span class="col-stats">Files & Symbols</span>
        <span class="col-actions">Actions</span>
      </div>
      <div id="repo-table-body">
  `;

  let rowsHtml = '';
  if (repos.length === 0) {
    rowsHtml = `
      <div style="padding: 32px; text-align: center; color: var(--muted); font-size: 12px;">
        No repositories matched your search or status filter.
      </div>
    `;
  } else {
    rowsHtml = repos.map((repo, idx) => {
      const statusBadge = repo.status === 'ready'
        ? '<span class="badge badge-success">Ready</span>'
        : repo.status === 'indexing'
        ? '<span class="badge badge-warning">Indexing</span>'
        : repo.status === 'failed'
        ? '<span class="badge badge-danger">Failed</span>'
        : '<span class="badge badge-neutral">Pending</span>';

      let syncBadge = '';
      if (repo.sync_status === 'syncing') {
        syncBadge = ' <span class="badge badge-warning" title="Syncing new commits">Syncing</span>';
      } else if (repo.sync_status === 'update_available') {
        syncBadge = ' <span class="badge badge-info" title="New remote commits available">Update available</span>';
      } else if (repo.sync_status === 'failed' || repo.sync_status === 'rate_limited') {
        const isRate = repo.sync_status === 'rate_limited';
        syncBadge = ` <button type="button" class="badge sync-badge-btn ${isRate ? 'sync-warning' : ''}" onclick="openSyncErrorModal(${repo.id})" title="${isRate ? 'GitHub rate limit active - Click for diagnosis and recovery' : 'Click to view failure diagnosis & recovery options'}" aria-label="View sync error details for ${escapeHtml(repo.name || '')}">Sync failed</button>`;
      } else if (repo.sync_status === 'synced' || repo.last_synced_commit_sha) {
        syncBadge = ' <span class="badge badge-neutral" title="Repository synchronized with latest commit">Synced</span>';
      }

      const displayedSha = repo.last_synced_commit_sha || repo.current_revision;
      const shaSnippet = displayedSha ? ` · <span title="Commit SHA: ${escapeHtml(displayedSha)}">SHA: <code>${escapeHtml(displayedSha.substring(0, 7))}</code></span>` : '';

      // Collect tech keywords for row dataset
      const techKeywords = [];
      if (repo.primary_language) techKeywords.push(repo.primary_language);
      if (repo.tech_stack) {
        const ts = repo.tech_stack;
        (ts.frontend || []).forEach(t => techKeywords.push(t.name));
        (ts.backend || []).forEach(t => techKeywords.push(t.name));
        (ts.database || []).forEach(t => techKeywords.push(t.name));
        (ts.infrastructure || []).forEach(t => techKeywords.push(t.name));
        (ts.languages || []).forEach(l => techKeywords.push(l));
      }

      const techCellHtml = renderTechStackCell(repo);

      return `
        <div class="table-row" data-repo-id="${repo.id}" data-repo-name="${escapeHtml((repo.name || '').toLowerCase())}" data-repo-full="${escapeHtml((repo.full_name || '').toLowerCase())}" data-repo-status="${escapeHtml((repo.status || 'pending').toLowerCase())}" data-repo-lang="${escapeHtml((repo.primary_language || '').toLowerCase())}" data-repo-tech="${escapeHtml(techKeywords.join(' ').toLowerCase())}">
          <div class="col-repo">
            <a href="/dashboard?repo=${repo.id}" class="repo-title-link" onclick="localStorage.setItem('codemind_active_repo_id', ${repo.id})" title="Open dashboard for ${escapeHtml(repo.name || '')}">
              <span class="repo-logo small">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>
                </svg>
              </span>
              <span class="repo-meta-wrap">
                <strong>${escapeHtml(repo.full_name || repo.name)}</strong>
                <small>${escapeHtml(repo.default_branch || 'main')} · ${repo.is_private ? 'Private' : 'Public'} · GitHub${shaSnippet}</small>
              </span>
            </a>
          </div>
          <div class="col-tech">${techCellHtml}</div>
          <div class="col-status">${statusBadge}${syncBadge}</div>
          <div class="col-stats repo-stats-col">
            <span class="repo-stat-item"><strong class="repo-stat-num">${formatNumber(repo.files_count || 0)}</strong> files</span>
            <span class="repo-stat-dot">·</span>
            <span class="repo-stat-item"><strong class="repo-stat-num">${formatNumber(repo.symbols_count || 0)}</strong> symbols</span>
          </div>
          <div class="col-actions repo-actions-cell">
            <button type="button" class="btn btn-ghost" onclick="triggerRepoIndex(${repo.id}, '${escapeHtml(repo.name || '')}')" title="Index or re-index">Index</button>
            <a href="/dashboard?repo=${repo.id}" class="btn btn-ghost" onclick="localStorage.setItem('codemind_active_repo_id', ${repo.id})" title="View Dashboard Overview">Overview</a>
            <a href="/git_history?repo=${repo.id}" class="btn btn-ghost" title="Browse commits">Browse</a>
            <a href="/code_viewer?repo=${repo.id}" class="btn btn-ghost" title="Explore code">Explore</a>
            <button type="button" class="btn btn-ghost btn-danger-action" onclick="deleteRepo(${repo.id}, '${escapeHtml(repo.full_name || repo.name || '')}', this)" style="color: var(--danger);" title="Disconnect repository">Disconnect</button>
          </div>
        </div>
      `;
    }).join('');
  }

  container.innerHTML = headHtml + rowsHtml + `</div></section>`;
}

function filterRepositoriesList() {
  const searchInput = document.getElementById('repo-search-input');
  const statusFilter = document.getElementById('repo-status-filter');
  const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
  const selectedStatus = (statusFilter ? statusFilter.value : 'all').toLowerCase();

  const filtered = allLoadedRepos.filter(repo => {
    // Collect all tech names for querying
    const techWords = [];
    if (repo.primary_language) techWords.push(repo.primary_language.toLowerCase());
    if (repo.tech_stack) {
      const ts = repo.tech_stack;
      (ts.frontend || []).forEach(t => techWords.push((t.name || '').toLowerCase()));
      (ts.backend || []).forEach(t => techWords.push((t.name || '').toLowerCase()));
      (ts.database || []).forEach(t => techWords.push((t.name || '').toLowerCase()));
      (ts.infrastructure || []).forEach(t => techWords.push((t.name || '').toLowerCase()));
      (ts.languages || []).forEach(l => techWords.push((l || '').toLowerCase()));
      if (ts.summary) {
        if (ts.summary.frontend_text) techWords.push(ts.summary.frontend_text.toLowerCase());
        if (ts.summary.backend_text) techWords.push(ts.summary.backend_text.toLowerCase());
        if (ts.summary.database_text) techWords.push(ts.summary.database_text.toLowerCase());
        if (ts.summary.infrastructure_text) techWords.push(ts.summary.infrastructure_text.toLowerCase());
      }
    }
    const techSearchText = techWords.join(' ');

    const nameMatch = !query ||
      (repo.name && repo.name.toLowerCase().includes(query)) ||
      (repo.full_name && repo.full_name.toLowerCase().includes(query)) ||
      (repo.default_branch && repo.default_branch.toLowerCase().includes(query)) ||
      (repo.primary_language && repo.primary_language.toLowerCase().includes(query)) ||
      techSearchText.includes(query);

    const statusMatch = selectedStatus === 'all' || (repo.status || 'pending').toLowerCase() === selectedStatus;
    return nameMatch && statusMatch;
  });

  renderRepositoriesTable(filtered);
}

// ============================================================================
// Sync Error Diagnosis & Recovery Modal Handlers
// ============================================================================
let currentSyncModalRepoId = null;
let currentSyncModalData = null;

async function openSyncErrorModal(repoId) {
  currentSyncModalRepoId = repoId;
  currentSyncModalData = null;
  const modal = document.getElementById('sync-error-details-modal');
  const body = document.getElementById('sync-error-modal-body');
  const statusMsg = document.getElementById('sync-error-modal-status-msg');
  const retryBtn = document.getElementById('btn-retry-sync');
  if (!modal || !body) return;

  if (retryBtn) {
    retryBtn.disabled = false;
    retryBtn.innerHTML = `
      <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
      <span>Retry Sync</span>
    `;
  }
  if (statusMsg) statusMsg.textContent = '';

  body.innerHTML = `
    <div style="padding: 30px; text-align: center; color: var(--muted); font-size: 13px;">
      <div class="spinner" style="margin: 0 auto 10px auto;"></div>
      Loading synchronization error details...
    </div>
  `;

  modal.classList.remove('hidden');
  document.body.classList.add('modal-open');

  try {
    const data = await CodeMindAPI.getSyncStatus(repoId);
    currentSyncModalData = data;
    renderSyncModalContent(data);
  } catch (err) {
    body.innerHTML = `
      <div class="sync-error-banner">
        <div class="sync-error-banner-icon">
          <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        </div>
        <div class="sync-error-banner-text">
          <strong>Failed to load diagnosis details</strong>
          <p>${escapeHtml(err.message || 'Unknown network error')}</p>
        </div>
      </div>
    `;
  }
}

function renderSyncModalContent(data) {
  const body = document.getElementById('sync-error-modal-body');
  const title = document.getElementById('sync-error-modal-title');
  const subtitle = document.getElementById('sync-error-modal-subtitle');
  if (!body) return;

  const isRateLimit = data.sync_status === 'rate_limited';
  const category = data.error_category || (isRateLimit ? 'RateLimit' : 'Error');
  const code = data.error_code || (isRateLimit ? 'GITHUB_RATE_LIMITED' : 'SYNC_FAILED');
  const operation = data.failed_operation || 'Fetch latest branch commit';
  const branch = data.branch || data.default_branch || 'main';
  const reason = data.error_message || data.sync_error || 'An unexpected synchronization error occurred.';
  const suggestedAction = data.suggested_action || 'Click Retry Sync to trigger an immediate repository check.';

  if (title) {
    title.textContent = `Sync failed — ${category}`;
  }
  if (subtitle) {
    subtitle.textContent = `${data.full_name || data.repository_name} · Branch: ${branch}`;
  }

  const formatTs = (ts) => {
    if (!ts) return '<span style="color: var(--muted);">None</span>';
    try {
      const d = new Date(ts);
      return d.toLocaleString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short'
      });
    } catch {
      return escapeHtml(ts);
    }
  };

  const attemptTimeStr = formatTs(data.last_attempt_at || data.last_checked_at);
  const successTimeStr = formatTs(data.last_success_at || data.last_synced_at);
  const successSha = data.last_successful_commit_sha || data.last_synced_commit_sha;
  const shaDisplay = successSha ? `<code>${escapeHtml(successSha.substring(0, 8))}</code>` : '<span style="color: var(--muted);">None</span>';

  body.innerHTML = `
    <div class="sync-error-banner ${isRateLimit ? 'warning' : ''}">
      <div class="sync-error-banner-icon">
        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </div>
      <div class="sync-error-banner-text">
        <strong>${escapeHtml(category)} (${escapeHtml(code)})</strong>
        <p>${escapeHtml(reason)}</p>
      </div>
    </div>

    <div class="sync-details-grid">
      <div class="sync-detail-item">
        <span class="sync-detail-label">Repository</span>
        <span class="sync-detail-value">${escapeHtml(data.full_name || data.repository_name)}</span>
      </div>
      <div class="sync-detail-item">
        <span class="sync-detail-label">Branch</span>
        <span class="sync-detail-value"><code>${escapeHtml(branch)}</code></span>
      </div>
      <div class="sync-detail-item">
        <span class="sync-detail-label">Current Sync Status</span>
        <span class="sync-detail-value">
          <span class="badge ${isRateLimit ? 'badge-warning' : 'badge-danger'}">
            ${escapeHtml(data.sync_status || 'failed')}
          </span>
        </span>
      </div>
      <div class="sync-detail-item">
        <span class="sync-detail-label">Failed Operation</span>
        <span class="sync-detail-value">${escapeHtml(operation)}</span>
      </div>
      <div class="sync-detail-item">
        <span class="sync-detail-label">Failure Timestamp</span>
        <span class="sync-detail-value">${attemptTimeStr}</span>
      </div>
      <div class="sync-detail-item">
        <span class="sync-detail-label">Last Successful Sync</span>
        <span class="sync-detail-value">${successTimeStr}</span>
      </div>
      <div class="sync-detail-item">
        <span class="sync-detail-label">Last Successful Commit</span>
        <span class="sync-detail-value">${shaDisplay}</span>
      </div>
      <div class="sync-detail-item">
        <span class="sync-detail-label">Retry Attempts</span>
        <span class="sync-detail-value">${data.retry_count != null ? data.retry_count : 0} / 3</span>
      </div>
    </div>

    <div class="sync-suggestion-card">
      <div class="suggestion-icon">
        <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="10"/>
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
      </div>
      <div>
        <strong>Suggested Action</strong>
        <p>${escapeHtml(suggestedAction)}</p>
      </div>
    </div>
  `;
}

function closeSyncErrorModal() {
  const modal = document.getElementById('sync-error-details-modal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.classList.remove('modal-open');
  }
}

async function retrySyncFromModal() {
  if (!currentSyncModalRepoId) return;
  const retryBtn = document.getElementById('btn-retry-sync');
  const statusMsg = document.getElementById('sync-error-modal-status-msg');

  if (retryBtn) {
    retryBtn.disabled = true;
    retryBtn.innerHTML = `
      <span class="spinner" style="width: 12px; height: 12px; border-width: 2px; margin-right: 6px;"></span>
      <span>Retrying...</span>
    `;
  }
  if (statusMsg) {
    statusMsg.style.color = 'var(--text-muted, #64748b)';
    statusMsg.textContent = 'Checking remote repository updates...';
  }

  try {
    const updated = await CodeMindAPI.triggerSync(currentSyncModalRepoId);
    currentSyncModalData = updated;

    if (updated.sync_status === 'synced' || updated.status === 'synced') {
      if (statusMsg) {
        statusMsg.style.color = 'var(--success, #10b981)';
        statusMsg.textContent = 'Synchronization successful!';
      }
      renderSyncModalContent(updated);
      setTimeout(() => {
        closeSyncErrorModal();
        if (typeof hydrateRepositoriesView === 'function') {
          hydrateRepositoriesView();
        }
      }, 1500);
    } else if (updated.sync_status === 'syncing' || updated.status === 'syncing') {
      if (statusMsg) {
        statusMsg.style.color = 'var(--primary, #6366f1)';
        statusMsg.textContent = 'New commit detected. Indexing enqueued!';
      }
      renderSyncModalContent(updated);
      setTimeout(() => {
        closeSyncErrorModal();
        if (typeof hydrateRepositoriesView === 'function') {
          hydrateRepositoriesView();
        }
      }, 1500);
    } else {
      // Still failed
      if (statusMsg) {
        statusMsg.style.color = 'var(--danger, #ef4444)';
        statusMsg.textContent = 'Retry attempt failed. See updated reason above.';
      }
      renderSyncModalContent(updated);
    }
  } catch (err) {
    if (statusMsg) {
      statusMsg.style.color = 'var(--danger, #ef4444)';
      statusMsg.textContent = `Error: ${err.message}`;
    }
  } finally {
    if (retryBtn) {
      retryBtn.disabled = false;
      retryBtn.innerHTML = `
        <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
        <span>Retry Sync</span>
      `;
    }
  }
}

function copySyncErrorDetails() {
  const statusMsg = document.getElementById('sync-error-modal-status-msg');
  if (!currentSyncModalData) {
    if (statusMsg) statusMsg.textContent = 'No error details to copy.';
    return;
  }

  const payload = {
    repository: currentSyncModalData.full_name || currentSyncModalData.repository_name,
    branch: currentSyncModalData.branch || currentSyncModalData.default_branch || 'main',
    sync_status: currentSyncModalData.sync_status,
    error_code: currentSyncModalData.error_code,
    error_category: currentSyncModalData.error_category,
    failed_operation: currentSyncModalData.failed_operation,
    error_message: currentSyncModalData.error_message || currentSyncModalData.sync_error,
    suggested_action: currentSyncModalData.suggested_action,
    last_attempt_at: currentSyncModalData.last_attempt_at || currentSyncModalData.last_checked_at,
    last_successful_sync_at: currentSyncModalData.last_success_at || currentSyncModalData.last_synced_at,
    last_successful_commit_sha: currentSyncModalData.last_successful_commit_sha || currentSyncModalData.last_synced_commit_sha,
    retry_count: currentSyncModalData.retry_count
  };

  const text = JSON.stringify(payload, null, 2);
  const showCopied = () => {
    if (statusMsg) {
      statusMsg.style.color = 'var(--primary, #6366f1)';
      statusMsg.textContent = 'Error details copied to clipboard!';
      setTimeout(() => {
        if (statusMsg && statusMsg.textContent === 'Error details copied to clipboard!') {
          statusMsg.textContent = '';
        }
      }, 3000);
    }
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(showCopied).catch(() => fallbackCopy(text, showCopied));
  } else {
    fallbackCopy(text, showCopied);
  }
}

function fallbackCopy(text, callback) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
    callback();
  } catch (e) {
    const statusMsg = document.getElementById('sync-error-modal-status-msg');
    if (statusMsg) statusMsg.textContent = 'Failed to copy to clipboard.';
  } finally {
    if (ta.parentNode) {
      ta.parentNode.removeChild(ta);
    }
  }
}

window.openSyncErrorModal = openSyncErrorModal;
window.closeSyncErrorModal = closeSyncErrorModal;
window.retrySyncFromModal = retrySyncFromModal;
window.copySyncErrorDetails = copySyncErrorDetails;

// Global open/close modal triggers
window.openConnectModal = function() {
  const modal = document.getElementById('connect-github-modal');
  if (modal) {
    modal.classList.remove('hidden');
    document.body.classList.add('modal-open');
    document.body.style.overflow = 'hidden';
    renderModalStep1();
  } else {
    window.location.href = '/repositories_modal';
  }
};

window.closeConnectModal = function() {
  const isDedicatedModalPage = window.location.pathname.includes('repositories_modal');
  if (isDedicatedModalPage) {
    window.location.href = '/repositories';
    return;
  }
  const modal = document.getElementById('connect-github-modal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
  }
};

let cachedAuthStatus = null;
let selectedGitHubRepo = null;
let indexingPollInterval = null;

async function initConnectGitHubModal() {
  const modal = document.getElementById('connect-github-modal');
  if (!modal) return;

  // Prevent duplicate initialization and duplicate listeners
  if (modal.dataset.initialized === 'true') {
    return;
  }
  modal.dataset.initialized = 'true';

  const openBtn = document.getElementById('btn-open-connect-modal');
  const closeBtn = document.getElementById('modal-close-x-btn');
  const backdrop = document.getElementById('modal-backdrop-close');
  const setupModal = modal.querySelector('.setup-modal');

  // CRITICAL FIX: Stop click propagation inside the modal dialog so clicking inputs, buttons,
  // file pickers, or empty space inside the modal NEVER bubbles to the backdrop or closes the modal
  if (setupModal) {
    setupModal.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  }

  if (openBtn) {
    openBtn.addEventListener('click', (e) => {
      e.preventDefault();
      openConnectModal();
    });
  }
  if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeConnectModal();
    });
  }
  if (backdrop) {
    backdrop.addEventListener('click', (e) => {
      // Intentional close ONLY when directly clicking the backdrop surface
      if (e.target === backdrop) {
        e.preventDefault();
        closeConnectModal();
      }
    });
  }

  // Handle clicking on the outer modal layer outside the setup-modal dialog
  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      e.preventDefault();
      closeConnectModal();
    }
  });

  // Accessibility: Escape key closes modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const isVisible = !modal.classList.contains('hidden');
      if (isVisible) {
        closeConnectModal();
      }
    }
  });

  const urlParams = new URLSearchParams(window.location.search);
  const isDedicatedModalPage = window.location.pathname.includes('repositories_modal');
  const isJustConnected = urlParams.get('github_connected') === '1';

  if (isDedicatedModalPage || isJustConnected || urlParams.get('open_modal') === '1') {
    modal.classList.remove('hidden');
    document.body.classList.add('modal-open');
    document.body.style.overflow = 'hidden';
    if (isJustConnected) {
      window.history.replaceState({}, document.title, window.location.pathname);
      await renderModalStep2();
    } else {
      await renderModalStep1();
    }
  }
}

function updateModalStepIndicators(currentStep) {
  const ind1 = document.getElementById('modal-step-ind-1');
  const ind2 = document.getElementById('modal-step-ind-2');
  const ind3 = document.getElementById('modal-step-ind-3');
  if (!ind1 || !ind2 || !ind3) return;

  ind1.className = currentStep === 1 ? 'active' : currentStep > 1 ? 'done' : '';
  ind2.className = currentStep === 2 ? 'active' : currentStep > 2 ? 'done' : '';
  ind3.className = currentStep === 3 ? 'active' : '';

  ind1.innerHTML = currentStep > 1 
    ? `<i><svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg></i>Authorize` 
    : `<i>1</i>Authorize`;
  ind2.innerHTML = currentStep > 2 
    ? `<i><svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg></i>Select` 
    : `<i>2</i>Select`;
  ind3.innerHTML = `<i>3</i>Index`;
}

async function renderModalStep1() {
  updateModalStepIndicators(1);
  const body = document.getElementById('modal-body-content');
  if (!body) return;

  body.innerHTML = `
    <div style="padding: 30px; text-align: center; color: var(--muted);">
      <svg class="icon animate-spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
      <p style="margin-top: 8px; font-size: 11px;">Checking GitHub connection status...</p>
    </div>
  `;

  try {
    cachedAuthStatus = await CodeMindAPI.getGitHubAuthStatus();
  } catch (e) {
    cachedAuthStatus = { configured: false, connected: false, accounts: [] };
  }

  const accounts = (cachedAuthStatus && cachedAuthStatus.accounts) || [];

  // 1. Connected Accounts Overview
  let connectedAccountsHtml = '';
  if (accounts.length > 0) {
    connectedAccountsHtml = `
      <div style="margin-bottom: 16px; padding: 12px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <strong style="font-size: 11.5px; color: var(--text);">Connected GitHub Accounts (${accounts.length})</strong>
          <span style="font-size: 10px; color: var(--muted);">Encrypted with AES-256-GCM</span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px;">
          ${accounts.map(acc => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="badge ${acc.auth_method === 'pat' ? 'badge-primary' : 'badge-success'}" style="font-size: 9.5px;">${escapeHtml(acc.auth_method.toUpperCase())}</span>
                <strong style="font-size: 11.5px; color: var(--text);">@${escapeHtml(acc.github_username)}</strong>
                ${acc.label ? `<small style="color: var(--muted); font-size: 10px;">(${escapeHtml(acc.label)})</small>` : ''}
              </div>
              <button type="button" class="btn btn-secondary btn-sm btn-disconnect-single-account" data-account-id="${acc.id}" style="color: var(--danger); font-size: 10px; padding: 2px 8px;">
                Disconnect
              </button>
            </div>
          `).join('')}
        </div>
        <button type="button" class="btn btn-primary full-btn" id="btn-proceed-select" style="margin-top: 4px;">
          <span>Browse Authorized Repositories (${accounts.length} account${accounts.length > 1 ? 's' : ''}) →</span>
        </button>
      </div>
    `;
  }

  // Account selector dropdown for direct import form
  let accountSelectorOptions = `<option value="">Auto-detect / Public (No credentials)</option>`;
  if (accounts.length > 0) {
    accounts.forEach(acc => {
      accountSelectorOptions += `<option value="${acc.id}">Use @${escapeHtml(acc.github_username)} (${acc.auth_method.toUpperCase()})</option>`;
    });
  }

  body.innerHTML = `
    <!-- Connected Accounts Header if any -->
    ${connectedAccountsHtml}

    <!-- Method A: Connect by URL or Path -->
    <div>
      <h2 style="font-size: 13.5px; font-weight: 600; margin-bottom: 4px;">Import Repository by URL or Path</h2>
      <p style="font-size: 11px; color: var(--muted); margin-bottom: 10px;">
        Accepts public or private GitHub URLs (e.g. <code>https://github.com/owner/repo</code>) or paths (e.g. <code>owner/repo</code>).
      </p>

      <div id="public-repo-error" class="inline-error" style="display: none; color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; padding: 8px 12px; border-radius: 6px; font-size: 11px; margin-bottom: 10px;"></div>

      <form id="form-direct-repo" class="direct-connect-form" style="display: flex; flex-direction: column; gap: 8px;">
        <div>
          <label for="input-direct-repo" style="display: block; font-size: 11px; font-weight: 600; margin-bottom: 4px; color: var(--text);">Repository URL or Path</label>
          <input type="text" id="input-direct-repo" placeholder="owner/repo or https://github.com/owner/repo" required style="width: 100%; margin-bottom: 6px;" autocomplete="off" spellcheck="false" />
        </div>
        ${accounts.length > 0 ? `
          <div>
            <label for="select-direct-repo-account" style="display: block; font-size: 10.5px; font-weight: 500; margin-bottom: 3px; color: var(--muted);">Authorized Account (required for private repositories)</label>
            <select id="select-direct-repo-account" style="width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font-size: 11px; background: var(--surface); color: var(--text);">
              ${accountSelectorOptions}
            </select>
          </div>
        ` : ''}
        <button type="submit" class="btn btn-primary" id="btn-direct-submit" style="align-self: flex-start; margin-top: 2px;">Connect & Index</button>
      </form>
    </div>

    <!-- Method B: Authorize GitHub (OAuth and PAT Guide) -->
    <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border);">
      <h2 style="font-size: 13.5px; font-weight: 600; margin-bottom: 4px;">Authorize GitHub Account</h2>
      <p style="font-size: 11px; color: var(--muted); margin-bottom: 10px;">
        Connect one or multiple personal or organization accounts using OAuth or Fine-grained Personal Access Tokens.
      </p>

      <!-- Tab Buttons: OAuth vs PAT -->
      <div style="display: flex; gap: 8px; margin-bottom: 12px;">
        <button type="button" class="btn btn-secondary btn-sm" id="btn-tab-oauth" style="font-weight: 600;">
          GitHub OAuth
        </button>
        <button type="button" class="btn btn-secondary btn-sm" id="btn-tab-pat">
          Connect with Token (PAT)
        </button>
      </div>

      <!-- OAuth Section -->
      <div id="section-oauth-flow">
        ${cachedAuthStatus && cachedAuthStatus.configured ? `
          <div style="padding: 10px 12px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius);">
            <p style="font-size: 11px; color: var(--muted); margin: 0 0 10px;">Authorize access to your personal and organization repositories via GitHub OAuth.</p>
            <button type="button" class="btn btn-secondary full-btn" id="btn-start-oauth">
              <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>
                <path d="M9 18c-4.51 2-5-2-7-2"/>
              </svg>
              <span>Authorize with GitHub OAuth</span>
            </button>
          </div>
        ` : `
          <div style="padding: 10px 12px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius); font-size: 11px; color: var(--muted);">
            <strong style="color: var(--text); font-size: 11px;">GitHub OAuth App Unconfigured</strong>
            <p style="margin: 2px 0 0; color: var(--muted); font-size: 10.5px;">To enable OAuth, set <code>GITHUB_CLIENT_ID</code> and <code>GITHUB_CLIENT_SECRET</code> in <code>backend/.env</code>. Alternatively, use Personal Access Token below.</p>
          </div>
        `}
      </div>

      <!-- PAT Setup Guide Section (Hidden by default, shown on click) -->
      <div id="section-pat-flow" style="display: none; padding: 12px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius);">
        <strong style="font-size: 12px; color: var(--text); display: block; margin-bottom: 6px;">How to generate and connect a Personal Access Token</strong>
        
        <ol style="font-size: 11px; line-height: 1.55; color: var(--muted); margin: 0 0 12px 18px; padding: 0;">
          <li>
            Open GitHub token settings: 
            <a href="https://github.com/settings/personal-access-tokens" target="_blank" rel="noopener noreferrer" style="color: var(--primary); text-decoration: underline; font-weight: 600;">
              https://github.com/settings/personal-access-tokens ↗
            </a>
          </li>
          <li>Select <strong>Fine-grained tokens</strong> and click <strong>"Generate new token"</strong>.</li>
          <li>Enter a descriptive token name and select an appropriate expiration.</li>
          <li>Choose the intended resource owner: your personal account or an organization that permits this authorization.</li>
          <li>Select only the repositories that CodeMind AI needs to access.</li>
          <li>Grant minimum permissions: Use read-only repository permissions (<strong>Contents: Read-only</strong>, <strong>Metadata: Read-only</strong>).</li>
          <li>Generate the token and copy it immediately. (GitHub will not display the full token again).</li>
          <li>Return to CodeMind AI, paste the token into the secure input below, and click <strong>"Connect GitHub"</strong>.</li>
        </ol>

        <div id="pat-inline-error" class="inline-error" style="display: none; color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; padding: 8px 12px; border-radius: 6px; font-size: 11px; margin-bottom: 10px;"></div>
        <div id="pat-inline-success" class="inline-success" style="display: none; color: #065f46; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 8px 12px; border-radius: 6px; font-size: 11px; margin-bottom: 10px;"></div>

        <form id="form-connect-pat" style="display: flex; flex-direction: column; gap: 8px;">
          <div>
            <label for="input-pat-token" style="display: block; font-size: 11px; font-weight: 600; margin-bottom: 4px; color: var(--text);">Personal Access Token</label>
            <div style="display: flex; gap: 6px; align-items: center;">
              <input type="password" id="input-pat-token" placeholder="ghp_... or github_pat_..." required style="flex: 1;" autocomplete="off" spellcheck="false" />
              <button type="button" class="btn btn-secondary btn-sm" id="btn-toggle-pat-visibility" style="padding: 6px 10px; font-size: 10.5px;">Show</button>
            </div>
          </div>
          <div>
            <label for="input-pat-label" style="display: block; font-size: 10.5px; font-weight: 500; margin-bottom: 2px; color: var(--muted);">Token Label (Optional)</label>
            <input type="text" id="input-pat-label" placeholder="e.g. Work Projects, Personal PAT" style="width: 100%;" autocomplete="off" />
          </div>
          <div style="font-size: 10px; color: var(--muted); margin: 2px 0;">
            🔒 Tokens are encrypted on the server with AES-256-GCM. Tokens are never exposed to frontend code or shared.
          </div>
          <div style="display: flex; gap: 8px; margin-top: 4px;">
            <button type="submit" class="btn btn-primary" id="btn-pat-submit">Connect GitHub</button>
            <button type="button" class="btn btn-secondary" id="btn-pat-cancel">Cancel</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Method C: Upload Local Project Folder -->
    <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border);">
      <h2 style="font-size: 13.5px; font-weight: 600; margin-bottom: 4px;">Or Upload a Local Project Folder (.zip)</h2>
      <p style="font-size: 11px; color: var(--muted); margin-bottom: 10px;">
        Upload a zipped local codebase to run offline AST parsing, knowledge graph, and AI search.
      </p>

      <div id="folder-upload-error" class="inline-error" style="display: none; color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; padding: 8px 12px; border-radius: 6px; font-size: 11px; margin-bottom: 10px;"></div>

      <form id="form-upload-folder" style="display: flex; flex-direction: column; gap: 8px;">
        <div style="display: flex; flex-direction: column; gap: 4px;">
          <label for="input-folder-zip" style="font-size: 11px; font-weight: 600; color: var(--text);">Project Archive (.zip)</label>
          <div style="display: flex; gap: 8px; align-items: center;">
            <input type="file" id="input-folder-zip" accept=".zip" required style="flex: 1;" />
            <input type="text" id="input-folder-name" placeholder="Project name (optional)" aria-label="Project name (optional)" style="width: 170px;" autocomplete="off" />
          </div>
          <div id="folder-zip-selected-info" style="display: none; font-size: 11px; color: var(--primary); font-weight: 500; margin-top: 3px;"></div>
        </div>
        <button type="submit" class="btn btn-secondary" id="btn-folder-submit" style="align-self: flex-start; min-width: 140px; margin-top: 2px;">Upload & Index</button>
      </form>
    </div>
  `;

  // Handlers for Tab Switching
  const tabOAuth = document.getElementById('btn-tab-oauth');
  const tabPAT = document.getElementById('btn-tab-pat');
  const sectionOAuth = document.getElementById('section-oauth-flow');
  const sectionPAT = document.getElementById('section-pat-flow');

  if (tabOAuth && tabPAT && sectionOAuth && sectionPAT) {
    tabOAuth.addEventListener('click', () => {
      tabOAuth.style.fontWeight = '600';
      tabPAT.style.fontWeight = 'normal';
      sectionOAuth.style.display = 'block';
      sectionPAT.style.display = 'none';
    });

    tabPAT.addEventListener('click', () => {
      tabPAT.style.fontWeight = '600';
      tabOAuth.style.fontWeight = 'normal';
      sectionOAuth.style.display = 'none';
      sectionPAT.style.display = 'block';
    });
  }

  // PAT Visibility Toggle
  const toggleBtn = document.getElementById('btn-toggle-pat-visibility');
  const patInput = document.getElementById('input-pat-token');
  if (toggleBtn && patInput) {
    toggleBtn.addEventListener('click', () => {
      if (patInput.type === 'password') {
        patInput.type = 'text';
        toggleBtn.textContent = 'Hide';
      } else {
        patInput.type = 'password';
        toggleBtn.textContent = 'Show';
      }
    });
  }

  // PAT Form Cancel
  const cancelPatBtn = document.getElementById('btn-pat-cancel');
  if (cancelPatBtn) {
    cancelPatBtn.addEventListener('click', () => {
      if (sectionPAT && sectionOAuth) {
        sectionPAT.style.display = 'none';
        sectionOAuth.style.display = 'block';
        if (tabOAuth) tabOAuth.style.fontWeight = '600';
        if (tabPAT) tabPAT.style.fontWeight = 'normal';
      }
    });
  }

  // PAT Form Submission
  const patForm = document.getElementById('form-connect-pat');
  if (patForm) {
    patForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const tokenVal = (patInput ? patInput.value : '').trim();
      const labelInput = document.getElementById('input-pat-label');
      const labelVal = labelInput ? labelInput.value.trim() : null;
      const submitBtn = document.getElementById('btn-pat-submit');
      const errBox = document.getElementById('pat-inline-error');
      const succBox = document.getElementById('pat-inline-success');

      if (errBox) errBox.style.display = 'none';
      if (succBox) succBox.style.display = 'none';

      if (!tokenVal) {
        if (errBox) {
          errBox.textContent = 'Please paste a valid Personal Access Token.';
          errBox.style.display = 'block';
        }
        return;
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Validating token...`;

      try {
        const connectedAcc = await CodeMindAPI.connectGitHubPAT(tokenVal, labelVal);
        // Clear sensitive input immediately after successful transmission
        if (patInput) patInput.value = '';
        if (labelInput) labelInput.value = '';

        if (succBox) {
          succBox.textContent = `✓ Successfully connected @${connectedAcc.github_username}! Redirecting to repository selection...`;
          succBox.style.display = 'block';
        }

        setTimeout(() => {
          renderModalStep2(connectedAcc.id);
        }, 800);
      } catch (err) {
        if (errBox) {
          errBox.textContent = err.message || 'Token validation failed. Please check permissions and expiration.';
          errBox.style.display = 'block';
        } else {
          alert(`Validation failed: ${err.message}`);
        }
        submitBtn.disabled = false;
        submitBtn.textContent = 'Connect GitHub';
      }
    });
  }

  // Single Account Disconnect Handlers
  const disconnectBtns = body.querySelectorAll('.btn-disconnect-single-account');
  disconnectBtns.forEach(btn => {
    btn.addEventListener('click', async () => {
      const accId = btn.getAttribute('data-account-id');
      if (!confirm('Disconnect this GitHub account? Indexed repositories in CodeMind AI will be preserved safely.')) return;
      try {
        await CodeMindAPI.disconnectGitHubAccount(accId);
        renderModalStep1();
      } catch (err) {
        alert(`Failed to disconnect account: ${err.message}`);
      }
    });
  });

  const startOAuthBtn = document.getElementById('btn-start-oauth');
  if (startOAuthBtn) {
    startOAuthBtn.addEventListener('click', () => {
      startOAuthBtn.disabled = true;
      startOAuthBtn.innerHTML = `<span>Redirecting to GitHub...</span>`;
      window.location.href = '/api/v1/auth/github/login?redirect=true';
    });
  }

  const proceedSelectBtn = document.getElementById('btn-proceed-select');
  if (proceedSelectBtn) {
    proceedSelectBtn.addEventListener('click', () => {
      renderModalStep2();
    });
  }

  const directForm = document.getElementById('form-direct-repo');
  if (directForm) {
    directForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = document.getElementById('input-direct-repo');
      const accountSelect = document.getElementById('select-direct-repo-account');
      const submitBtn = document.getElementById('btn-direct-submit');
      const errBox = document.getElementById('public-repo-error');
      if (errBox) errBox.style.display = 'none';

      const fullRepo = (input ? input.value : '').trim();
      const selectedAccId = accountSelect && accountSelect.value ? parseInt(accountSelect.value) : null;

      if (!fullRepo) {
        if (errBox) {
          errBox.textContent = 'Please enter a repository path (e.g. pallets/flask) or full GitHub URL.';
          errBox.style.display = 'block';
        }
        if (input) input.focus();
        return;
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Connecting...`;

      try {
        const repo = await CodeMindAPI.importRepository(fullRepo, selectedAccId, true);
        renderModalStep3(repo);
      } catch (err) {
        if (errBox) {
          errBox.textContent = err.message || 'Failed to connect repository.';
          errBox.style.display = 'block';
        } else {
          alert(`Failed to connect repository: ${err.message}`);
        }
        submitBtn.disabled = false;
        submitBtn.textContent = 'Connect & Index';
      }
    });
  }

  const folderFileInput = document.getElementById('input-folder-zip');
  const folderZipInfo = document.getElementById('folder-zip-selected-info');
  const folderNameInput = document.getElementById('input-folder-name');
  if (folderFileInput && folderZipInfo) {
    folderFileInput.addEventListener('change', () => {
      if (folderFileInput.files && folderFileInput.files.length > 0) {
        const file = folderFileInput.files[0];
        const sizeKb = Math.round(file.size / 1024);
        const sizeFormatted = sizeKb > 1024 ? (sizeKb / 1024).toFixed(1) + ' MB' : sizeKb + ' KB';
        folderZipInfo.innerHTML = `Selected: <strong>${escapeHtml(file.name)}</strong> (${sizeFormatted})`;
        folderZipInfo.style.display = 'block';

        if (folderNameInput && !folderNameInput.value.trim()) {
          folderNameInput.value = file.name.replace(/\.zip$/i, '');
        }
      } else {
        folderZipInfo.style.display = 'none';
      }
    });
  }

  const folderForm = document.getElementById('form-upload-folder');
  if (folderForm) {
    folderForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById('input-folder-zip');
      const nameInput = document.getElementById('input-folder-name');
      const submitBtn = document.getElementById('btn-folder-submit');
      const errBox = document.getElementById('folder-upload-error');
      if (errBox) errBox.style.display = 'none';

      if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        if (errBox) {
          errBox.textContent = 'Please choose a .zip file of your project repository.';
          errBox.style.display = 'block';
        }
        return;
      }

      const file = fileInput.files[0];
      if (!file.name.toLowerCase().endsWith('.zip')) {
        if (errBox) {
          errBox.textContent = 'Only .zip files are supported.';
          errBox.style.display = 'block';
        }
        return;
      }

      const formData = new FormData();
      formData.append('file', file);
      if (nameInput && nameInput.value.trim()) {
        formData.append('name', nameInput.value.trim());
      }
      formData.append('auto_index', 'true');

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Uploading...`;

      try {
        const repo = await CodeMindAPI.uploadFolder(formData);
        renderModalStep3(repo);
      } catch (err) {
        if (errBox) {
          errBox.textContent = err.message || 'Failed to upload project folder.';
          errBox.style.display = 'block';
        } else {
          alert(`Failed to upload project folder: ${err.message}`);
        }
        submitBtn.disabled = false;
        submitBtn.textContent = 'Upload & Index';
      }
    });
  }
}

async function renderModalStep2(initialAccountId = null) {
  updateModalStepIndicators(2);
  const body = document.getElementById('modal-body-content');
  if (!body) return;

  body.innerHTML = `
    <div style="padding: 30px; text-align: center; color: var(--muted);">
      <svg class="icon animate-spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
      <p style="margin-top: 8px; font-size: 11px;">Fetching accessible repositories from GitHub...</p>
    </div>
  `;

  try {
    let accounts = [];
    try {
      const accRes = await CodeMindAPI.getGitHubAccounts();
      accounts = accRes.accounts || [];
    } catch (e) {
      accounts = [];
    }

    let activeAccountId = initialAccountId;
    if (!activeAccountId && accounts.length > 0) {
      activeAccountId = accounts[0].id;
    }

    const fetchRepos = async (accId) => {
      if (accId) {
        return CodeMindAPI.getGitHubAccountRepositories(accId);
      }
      return CodeMindAPI.getGitHubRepositories();
    };

    let ghRepos = await fetchRepos(activeAccountId);

    const renderRepoList = (repos) => {
      if (!repos || repos.length === 0) {
        return `
          <div class="empty-state" style="padding: 24px; text-align: center;">
            <h3 style="font-size: 12px; margin-bottom: 4px;">No Repositories Accessible</h3>
            <p style="color: var(--muted); font-size: 10.5px; margin: 4px 0 12px;">This account has not granted access to any repositories. Check fine-grained permissions or repository selection in GitHub settings.</p>
          </div>
        `;
      }

      return repos.map((repo, idx) => `
        <div class="repo-option ${idx === 0 ? 'selected' : ''}" data-full-name="${escapeHtml(repo.full_name)}" data-name="${escapeHtml(repo.name)}" data-branch="${escapeHtml(repo.default_branch || 'main')}" data-private="${repo.is_private}" data-lang="${escapeHtml(repo.primary_language || '')}" data-id="${repo.id}" data-acc-id="${repo.connected_account_id || activeAccountId || ''}">
          <span class="radio-dot"></span>
          <span class="repo-logo small"><svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg></span>
          <span>
            <strong>${escapeHtml(repo.full_name)}</strong>
            <small>${escapeHtml(repo.default_branch || 'main')} · ${repo.is_private ? 'Private' : 'Public'} · ${escapeHtml(repo.primary_language || 'Polyglot')}</small>
          </span>
          ${repo.is_connected ? '<span class="badge badge-neutral">Already Connected</span>' : ''}
        </div>
      `).join('');
    };

    let accountSwitcherHtml = '';
    if (accounts.length > 1) {
      accountSwitcherHtml = `
        <div style="margin-bottom: 12px;">
          <label for="modal-account-switcher" style="display: block; font-size: 10.5px; font-weight: 600; color: var(--muted); margin-bottom: 4px;">Viewing account repositories:</label>
          <select id="modal-account-switcher" style="width: 100%; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 11px; background: var(--surface); color: var(--text);">
            ${accounts.map(a => `<option value="${a.id}" ${a.id === activeAccountId ? 'selected' : ''}>@${escapeHtml(a.github_username)} (${a.auth_method.toUpperCase()}${a.label ? ` - ${escapeHtml(a.label)}` : ''})</option>`).join('')}
          </select>
        </div>
      `;
    }

    body.innerHTML = `
      <h2>Select a repository</h2>
      <p>Choose an authorized repository to register and index with CodeMind AI.</p>
      
      ${accountSwitcherHtml}

      <div class="modal-search" style="margin-bottom: 10px;">
        <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
        <input type="text" id="modal-repo-search-input" placeholder="Filter repositories..." />
      </div>

      <div id="modal-repo-options-list" style="max-height: 260px; overflow-y: auto; margin-bottom: 16px;">
        ${renderRepoList(ghRepos)}
      </div>

      <div class="modal-actions" style="justify-content: space-between;">
        <button type="button" class="btn btn-secondary" onclick="renderModalStep1()">Back</button>
        <button type="button" class="btn btn-primary" id="btn-modal-confirm-select" ${!ghRepos || ghRepos.length === 0 ? 'disabled' : ''}>Continue to Indexing →</button>
      </div>
    `;

    selectedGitHubRepo = ghRepos && ghRepos.length > 0 ? { ...ghRepos[0], connected_account_id: activeAccountId } : null;

    const bindRepoOptions = () => {
      const options = body.querySelectorAll('.repo-option');
      options.forEach(opt => {
        opt.addEventListener('click', () => {
          options.forEach(o => o.classList.remove('selected'));
          opt.classList.add('selected');
          const fullName = opt.getAttribute('data-full-name');
          const matched = ghRepos.find(r => r.full_name === fullName);
          selectedGitHubRepo = matched ? { ...matched, connected_account_id: activeAccountId } : {
            name: opt.getAttribute('data-name'),
            full_name: fullName,
            default_branch: opt.getAttribute('data-branch'),
            is_private: opt.getAttribute('data-private') === 'true',
            primary_language: opt.getAttribute('data-lang'),
            id: parseInt(opt.getAttribute('data-id')),
            connected_account_id: activeAccountId
          };
        });
      });
    };
    bindRepoOptions();

    // Account Switcher Listener
    const switcher = document.getElementById('modal-account-switcher');
    if (switcher) {
      switcher.addEventListener('change', async () => {
        const newAccId = parseInt(switcher.value);
        activeAccountId = newAccId;
        const listContainer = document.getElementById('modal-repo-options-list');
        if (listContainer) {
          listContainer.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--muted);"><svg class="icon animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg><span style="margin-left: 6px; font-size: 11px;">Loading repositories for selected account...</span></div>`;
        }
        try {
          ghRepos = await fetchRepos(newAccId);
          if (listContainer) {
            listContainer.innerHTML = renderRepoList(ghRepos);
            selectedGitHubRepo = ghRepos && ghRepos.length > 0 ? { ...ghRepos[0], connected_account_id: newAccId } : null;
            bindRepoOptions();
          }
          const confirmBtn = document.getElementById('btn-modal-confirm-select');
          if (confirmBtn) {
            confirmBtn.disabled = !ghRepos || ghRepos.length === 0;
          }
        } catch (err) {
          if (listContainer) {
            listContainer.innerHTML = `<div style="padding: 16px; color: #b91c1c; font-size: 11px;">Failed to load repositories: ${escapeHtml(err.message)}</div>`;
          }
        }
      });
    }

    const searchInput = document.getElementById('modal-repo-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        const q = searchInput.value.trim().toLowerCase();
        const options = body.querySelectorAll('.repo-option');
        options.forEach(opt => {
          const fn = (opt.getAttribute('data-full-name') || '').toLowerCase();
          opt.style.display = fn.includes(q) ? 'flex' : 'none';
        });
      });
    }

    const confirmBtn = document.getElementById('btn-modal-confirm-select');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', async () => {
        if (!selectedGitHubRepo) {
          alert('Please select a repository.');
          return;
        }

        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Connecting...';

        try {
          const registered = await CodeMindAPI.registerRepository({
            name: selectedGitHubRepo.name,
            full_name: selectedGitHubRepo.full_name,
            default_branch: selectedGitHubRepo.default_branch || 'main',
            is_private: selectedGitHubRepo.is_private || false,
            primary_language: selectedGitHubRepo.primary_language || null,
            github_repo_id: selectedGitHubRepo.id,
            connected_account_id: selectedGitHubRepo.connected_account_id || activeAccountId || null
          });

          renderModalStep3(registered);
        } catch (err) {
          alert(`Error registering repository: ${err.message}`);
          confirmBtn.disabled = false;
          confirmBtn.textContent = 'Continue to Indexing →';
        }
      });
    }
  } catch (err) {
    body.innerHTML = `
      <div style="padding: 24px; text-align: center; color: var(--danger);">
        <strong>Failed to load repositories from GitHub</strong>
        <p style="font-size: 11px; color: var(--muted); margin: 6px 0 16px;">${escapeHtml(err.message)}</p>
        <button type="button" class="btn btn-secondary" onclick="renderModalStep1()">Back to Step 1</button>
      </div>
    `;
  }
}

async function renderModalStep3(repo) {
  updateModalStepIndicators(3);
  const body = document.getElementById('modal-body-content');
  if (!body) return;

  body.innerHTML = `
    <div class="indexing-body">
      <div class="scan-orb">
        <svg class="icon animate-spin" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
      </div>
      <h2>Indexing ${escapeHtml(repo.full_name)}</h2>
      <p id="indexing-status-desc">Automated analysis pipeline is parsing files and constructing code knowledge graph...</p>
      
      <div class="index-progress">
        <i id="indexing-progress-bar" style="width: 30%;"></i>
      </div>

      <div id="indexing-stage-list">
        <span id="stg-reg" class="done">
          <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg>
          Repository registered in workspace
        </span>
        <span id="stg-ast" class="active">
          <i></i>
          Extracting AST symbols & syntax structures
        </span>
        <span id="stg-graph">
          <span class="pending-dot"></span>
          Building entity dependency knowledge graph
        </span>
        <span id="stg-embeddings">
          <span class="pending-dot"></span>
          Generating 768-dimensional hybrid embeddings
        </span>
      </div>

      <div class="modal-actions" id="indexing-complete-actions" style="display: none; justify-content: center; gap: 10px; margin-top: 20px;">
        <a href="/repositories" class="btn btn-secondary">View Repositories</a>
        <a href="/dashboard" class="btn btn-primary">Open Dashboard →</a>
      </div>
    </div>
  `;

  try {
    await CodeMindAPI.triggerIndexing(repo.id, repo.default_branch || 'main');
  } catch (e) {
    // Pipeline may already have been triggered upon registration
  }

  if (indexingPollInterval) clearInterval(indexingPollInterval);

  let pollCount = 0;
  indexingPollInterval = setInterval(async () => {
    pollCount++;
    try {
      const statusRes = await CodeMindAPI.getIndexingStatus(repo.id);
      const progressBar = document.getElementById('indexing-progress-bar');
      const statusDesc = document.getElementById('indexing-status-desc');
      const stgAst = document.getElementById('stg-ast');
      const stgGraph = document.getElementById('stg-graph');
      const stgEmbeddings = document.getElementById('stg-embeddings');
      const actionsDiv = document.getElementById('indexing-complete-actions');

      if (statusRes.status === 'ready') {
        clearInterval(indexingPollInterval);
        if (progressBar) progressBar.style.width = '100%';
        if (statusDesc) {
          statusDesc.innerHTML = `<strong>Indexing Complete!</strong> Indexed ${statusRes.files_count || 0} files and ${statusRes.symbols_count || 0} code symbols.`;
        }

        if (stgAst) stgAst.className = 'done';
        if (stgGraph) stgGraph.className = 'done';
        if (stgEmbeddings) stgEmbeddings.className = 'done';

        if (actionsDiv) actionsDiv.style.display = 'flex';

        hydrateRepositoriesView();
      } else if (statusRes.status === 'failed') {
        clearInterval(indexingPollInterval);
        const errMsg = (statusRes.current_job && statusRes.current_job.error_message) || 'Indexing pipeline encountered an error.';
        if (statusDesc) {
          statusDesc.innerHTML = `<span style="color: var(--danger);"><strong>Indexing Failed:</strong> ${escapeHtml(errMsg)}</span>`;
        }
        if (actionsDiv) actionsDiv.style.display = 'flex';
      } else {
        const job = statusRes.current_job;
        const pct = job && job.progress_percent ? job.progress_percent : Math.min(20 + pollCount * 5, 88);
        if (progressBar) progressBar.style.width = `${pct}%`;

        const stage = job ? (job.stage || '').toLowerCase() : '';
        if (statusDesc && job && job.stage) {
          statusDesc.textContent = `Stage: ${job.stage.toUpperCase()} (${job.progress_percent || 0}%) — analyzing repository contents...`;
        }

        if (stage === 'parsing' || stage === 'ast') {
          if (stgAst) stgAst.className = 'active';
        } else if (stage === 'graph') {
          if (stgAst) stgAst.className = 'done';
          if (stgGraph) stgGraph.className = 'active';
        } else if (stage === 'embeddings' || stage === 'vector') {
          if (stgAst) stgAst.className = 'done';
          if (stgGraph) stgGraph.className = 'done';
          if (stgEmbeddings) stgEmbeddings.className = 'active';
        }
      }
    } catch (e) {
      // Keep polling
    }
  }, 2000);
}

window.triggerRepoIndex = async function(repoId, name) {
  try {
    await CodeMindAPI.triggerIndexing(repoId);
    alert(`Indexing started for ${name || 'repository'}.`);
    hydrateRepositoriesView();
  } catch (err) {
    alert(`Failed to trigger indexing: ${err.message}`);
  }
};

// Viewport-Centered Notification Component (Accessible status/toast)
function showCenteredNotification({ title, repoName, message, type = 'success', duration = 4200 }) {
  const existing = document.getElementById('cm-centered-notification-container');
  if (existing) existing.remove();

  const backdrop = document.createElement('div');
  backdrop.id = 'cm-centered-notification-container';
  backdrop.className = 'cm-centered-notification-backdrop';
  backdrop.setAttribute('role', type === 'error' ? 'alert' : 'status');
  backdrop.setAttribute('aria-live', 'polite');

  const isSuccess = type === 'success';
  const iconSvg = isSuccess
    ? `<svg class="icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M20 6 9 17l-5-5"/></svg>`
    : `<svg class="icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;

  backdrop.innerHTML = `
    <div class="cm-centered-notification-card" tabindex="-1">
      <button type="button" class="cm-centered-notification-close" id="btn-close-centered-notification" aria-label="Close notification" title="Close">
        <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m6 6 12 12M18 6 6 18"/></svg>
      </button>
      <div class="cm-centered-notification-icon ${type}">
        ${iconSvg}
      </div>
      <h3 class="cm-centered-notification-title">${escapeHtml(title)}</h3>
      ${repoName ? `<div class="cm-centered-notification-repo"><svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg><span>${escapeHtml(repoName)}</span></div>` : ''}
      ${message ? `<p class="cm-centered-notification-msg">${escapeHtml(message)}</p>` : ''}
      <div class="cm-centered-notification-actions">
        <button type="button" class="btn btn-secondary btn-sm" id="btn-ack-centered-notification">Dismiss</button>
      </div>
    </div>
  `;

  document.body.appendChild(backdrop);

  function dismiss() {
    if (!backdrop.parentNode) return;
    backdrop.classList.add('closing');
    setTimeout(() => {
      if (backdrop.parentNode) backdrop.remove();
    }, 200);
    document.removeEventListener('keydown', handleKey);
  }

  function handleKey(e) {
    if (e.key === 'Escape') dismiss();
  }
  document.addEventListener('keydown', handleKey);

  const closeBtn = backdrop.querySelector('#btn-close-centered-notification');
  const ackBtn = backdrop.querySelector('#btn-ack-centered-notification');
  if (closeBtn) closeBtn.onclick = dismiss;
  if (ackBtn) ackBtn.onclick = dismiss;

  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) dismiss();
  });

  if (duration > 0) {
    let timer = setTimeout(dismiss, duration);
    const card = backdrop.querySelector('.cm-centered-notification-card');
    if (card) {
      card.addEventListener('mouseenter', () => clearTimeout(timer));
      card.addEventListener('mouseleave', () => {
        timer = setTimeout(dismiss, 2500);
      });
    }
  }

  return backdrop;
}
window.showCenteredNotification = showCenteredNotification;

// In-flight disconnect tracking to prevent duplicate clicks / double submissions
const inFlightDisconnects = new Set();

window.deleteRepo = async function(repoId, fullName, triggerBtn = null) {
  const numericId = parseInt(repoId, 10);
  if (!numericId || inFlightDisconnects.has(numericId)) {
    return;
  }

  const confirmed = confirm(
    `Are you sure you want to disconnect ${fullName || 'this repository'}?\n\n` +
    `This will remove the repository connection and clean up its indexed code symbols and knowledge graph associations.`
  );
  if (!confirmed) return;

  inFlightDisconnects.add(numericId);

  // Disable button and indicate loading state
  let btn = triggerBtn;
  if (!btn) {
    btn = document.querySelector(`.table-row[data-repo-id="${numericId}"] button[title="Disconnect repository"]`);
  }
  const originalText = btn ? btn.textContent : 'Disconnect';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Disconnecting...';
    btn.style.opacity = '0.6';
    btn.style.cursor = 'not-allowed';
  }

  try {
    const result = await CodeMindAPI.deleteRepository(numericId);
    const displayName = (result && (result.full_name || result.name)) || fullName || `Repository #${numericId}`;

    // Remove the row from the DOM table immediately with clean transition
    const rowEl = document.querySelector(`.table-row[data-repo-id="${numericId}"]`);
    if (rowEl) {
      rowEl.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
      rowEl.style.opacity = '0';
      rowEl.style.transform = 'scale(0.98)';
      setTimeout(() => {
        if (rowEl.parentNode) rowEl.remove();
      }, 200);
    }

    // Update in-memory loaded repositories
    allLoadedRepos = allLoadedRepos.filter(r => r.id !== numericId);

    // Refresh active repository if the deleted one was selected
    const storedActiveId = localStorage.getItem('codemind_active_repo_id');
    if (storedActiveId && parseInt(storedActiveId, 10) === numericId) {
      if (allLoadedRepos.length > 0) {
        const nextRepo = allLoadedRepos[0];
        localStorage.setItem('codemind_active_repo_id', nextRepo.id);
        const topbarRepo = document.querySelector('.repo-selector strong');
        if (topbarRepo) {
          topbarRepo.textContent = nextRepo.name || nextRepo.full_name || 'Select repository';
        }
      } else {
        localStorage.removeItem('codemind_active_repo_id');
        const topbarRepo = document.querySelector('.repo-selector strong');
        if (topbarRepo) {
          topbarRepo.textContent = 'Select repository';
        }
      }
    }

    // Show truthful empty state if no repositories remain
    if (allLoadedRepos.length === 0) {
      const container = document.getElementById('repositories-container') || document.querySelector('.table-card');
      const filterRow = document.getElementById('repo-filter-row');
      if (filterRow) filterRow.style.display = 'none';
      if (container) {
        container.innerHTML = `
          <div class="empty-state-card">
            <div class="empty-state-illustration">
              <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>
                <path d="M9 18c-4.51 2-5-2-7-2"/>
              </svg>
            </div>
            <h2 class="empty-state-title">Connect your first repository</h2>
            <p class="empty-state-desc">
              Connect an authorized GitHub repository to start AST parsing, dependency mapping, knowledge graph synthesis, and change-impact prediction.
            </p>
            <div class="empty-state-actions">
              <button type="button" class="btn btn-primary" id="btn-empty-connect" onclick="openConnectModal()">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                  <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>
                  <path d="M9 18c-4.51 2-5-2-7-2"/>
                </svg>
                <span>Connect GitHub</span>
              </button>
            </div>
          </div>
        `;
      }
    }

    // Display the required centered success notification with actual repo name
    showCenteredNotification({
      title: 'Repository disconnected successfully',
      repoName: displayName,
      message: 'The repository association and indexed graph data have been removed from your workspace.',
      type: 'success',
      duration: 4200
    });

  } catch (err) {
    console.error('[deleteRepo] Disconnect failure:', err);

    if (err.status === 404) {
      // Repository was already disconnected or deleted from database
      const rowEl = document.querySelector(`.table-row[data-repo-id="${numericId}"]`);
      if (rowEl) rowEl.remove();
      allLoadedRepos = allLoadedRepos.filter(r => r.id !== numericId);

      showCenteredNotification({
        title: 'Repository already disconnected',
        repoName: fullName,
        message: 'This repository is no longer present in your workspace.',
        type: 'error',
        duration: 4500
      });
    } else {
      if (btn) {
        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.opacity = '';
        btn.style.cursor = '';
      }
      showCenteredNotification({
        title: 'Failed to disconnect repository',
        repoName: fullName,
        message: err.message || 'An unexpected error occurred while disconnecting the repository.',
        type: 'error',
        duration: 5000
      });
    }
  } finally {
    inFlightDisconnects.delete(numericId);
  }
};

function getTimeBasedGreeting(fullName, date = new Date()) {
  const hour = (date instanceof Date ? date : new Date()).getHours();
  let prefix = 'Good night';
  if (hour >= 5 && hour < 12) {
    prefix = 'Good morning';
  } else if (hour >= 12 && hour < 17) {
    prefix = 'Good afternoon';
  } else if (hour >= 17 && hour < 21) {
    prefix = 'Good evening';
  }

  const firstName = (fullName && typeof fullName === 'string') ? fullName.trim().split(/\s+/)[0] : '';
  return firstName ? `${prefix}, ${firstName}` : prefix;
}

let currentDashboardRequestId = 0;

async function hydrateDashboardView(targetRepoId = null) {
  const requestId = ++currentDashboardRequestId;

  try {
    let activeRepo = null;
    if (targetRepoId) {
      const repos = await CodeMindAPI.getRepositories();
      activeRepo = (repos || []).find(r => r.id === parseInt(targetRepoId) || (r.name && r.name.toLowerCase() === String(targetRepoId).toLowerCase())) || null;
      if (activeRepo) {
        localStorage.setItem('codemind_active_repo_id', activeRepo.id);
      }
    }
    if (!activeRepo) {
      activeRepo = await getActiveRepository();
    }

    const topbarRepo = document.querySelector('.repo-selector strong');
    const topbarBranch = document.getElementById('topbar-branch-text');
    const bannerRepo = document.querySelector('.repo-title strong');
    const bannerDesc = document.querySelector('.repo-banner p');
    const healthText = document.querySelector('.index-health strong');
    const healthSub = document.querySelector('.index-health small');
    const healthDot = document.querySelector('.index-health .status-dot');
    const metricValues = document.querySelectorAll('.metric-value');
    const metricBadges = document.querySelectorAll('.metric-card .badge');
    const archContainer = document.getElementById('dashboard-architecture-container');
    const techStackContainer = document.getElementById('dashboard-tech-stack-container');
    const commitsContainer = document.getElementById('dashboard-recent-commits');
    const questionsContainer = document.getElementById('dashboard-recent-questions');
    const greetingHeader = document.querySelector('.page-header h1');
    const lastIndexedBtn = document.querySelector('.header-actions .btn-secondary span');
    const askCodeMindBtn = document.querySelector('.header-actions .btn-primary');

    // 1. Immediately apply local time-based greeting from cached profile or asynchronous fetch
    if (greetingHeader) {
      const cachedUser = window._codemind_cached_user;
      if (cachedUser && cachedUser.full_name) {
        greetingHeader.textContent = getTimeBasedGreeting(cachedUser.full_name);
      } else {
        CodeMindAPI.getCurrentUser().then(u => {
          if (u && u.full_name && greetingHeader && currentDashboardRequestId === requestId) {
            greetingHeader.textContent = getTimeBasedGreeting(u.full_name);
          }
        }).catch(() => {});
      }
    }

    // 2. Immediately clear stale data and show loading indicators
    metricValues.forEach(el => { el.textContent = '—'; });

    if (activeRepo) {
      if (topbarRepo) topbarRepo.textContent = activeRepo.name;
      if (topbarBranch) topbarBranch.textContent = activeRepo.default_branch || 'main';
      if (bannerRepo) bannerRepo.textContent = activeRepo.full_name;
      const initialSummary = activeRepo.tech_stack?.summary?.full_summary || activeRepo.primary_language || 'Polyglot';
      if (bannerDesc) bannerDesc.textContent = `${activeRepo.description || 'Repository'} · ${initialSummary}`;
      if (healthText) healthText.textContent = 'Loading repository metrics...';
      if (healthSub) healthSub.textContent = `Fetching indexed status on ${activeRepo.default_branch || 'main'}`;
      if (healthDot) healthDot.className = 'status-dot';
      if (askCodeMindBtn) askCodeMindBtn.href = `/assistant?repo=${activeRepo.id}`;
    }

    if (techStackContainer) {
      techStackContainer.innerHTML = `
        <div style="padding: 24px 16px; text-align: center; color: var(--muted); font-size: 11.5px; width: 100%;">
          Analyzing repository technology stack and evidence...
        </div>
      `;
      initTechStackScrollControls();
    }
    if (archContainer) {
      archContainer.innerHTML = `
        <div style="padding: 36px 16px; text-align: center; color: var(--muted); font-size: 11.5px; width: 100%;">
          Synthesizing architecture overview for ${activeRepo ? escapeHtml(activeRepo.name) : 'repository'}...
        </div>
      `;
    }
    if (commitsContainer) {
      commitsContainer.innerHTML = `
        <div style="padding: 24px 12px; text-align: center; color: var(--muted); font-size: 11.5px;">
          Loading recent commits...
        </div>
      `;
    }
    if (questionsContainer) {
      questionsContainer.innerHTML = `
        <div style="padding: 24px 12px; text-align: center; color: var(--muted); font-size: 11.5px;">
          Loading repository investigations...
        </div>
      `;
    }

    // Update Quick Action Links with target active repository ID
    if (activeRepo) {
      const quickActionLinks = document.querySelectorAll('.quick-card a.quick-action');
      quickActionLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href) {
          const base = href.split('?')[0];
          link.setAttribute('href', `${base}?repo=${activeRepo.id}`);
        }
      });
      const exploreGraphLink = document.querySelector('.architecture-card .btn-ghost');
      if (exploreGraphLink) {
        exploreGraphLink.setAttribute('href', `/dependencies?repo=${activeRepo.id}`);
      }
      const viewHistoryLink = document.querySelector('.activity-card a[href*="git_history"]');
      if (viewHistoryLink) {
        viewHistoryLink.setAttribute('href', `/git_history?repo=${activeRepo.id}`);
      }
      const openAssistantLink = document.querySelector('.activity-card a[href*="assistant"]');
      if (openAssistantLink) {
        openAssistantLink.setAttribute('href', `/assistant?repo=${activeRepo.id}`);
      }
    } else {
      // No active repository selected
      if (topbarRepo) topbarRepo.textContent = 'No repository';
      if (bannerRepo) bannerRepo.textContent = 'No repository connected';
      if (bannerDesc) bannerDesc.textContent = 'Connect a repository to begin automated code analysis';
      if (healthText) healthText.textContent = 'No index data';
      if (healthSub) healthSub.textContent = 'Connect repository to index files';
      if (healthDot) healthDot.className = 'status-dot warning';

      metricValues.forEach(el => { el.textContent = '0'; });
      metricBadges.forEach(badge => {
        badge.className = 'badge badge-neutral';
        badge.textContent = 'Not Indexed';
      });

      if (techStackContainer) {
        techStackContainer.innerHTML = `
          <div style="padding: 24px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem; width: 100%;">
            Connect a repository to view detected technology stack and evidence.
          </div>
        `;
        initTechStackScrollControls();
      }
      if (archContainer) {
        archContainer.innerHTML = `
          <div style="padding: 24px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem; width: 100%;">
            Connect a repository to view architecture relationships.
          </div>
        `;
      }
      if (commitsContainer) {
        commitsContainer.innerHTML = `
          <div style="padding: 18px 12px; text-align: center; color: var(--text-muted); font-size: 0.82rem;">
            Connect a repository to view recent commits.
          </div>
        `;
      }
      if (questionsContainer) {
        questionsContainer.innerHTML = `
          <div style="padding: 18px 12px; text-align: center; color: var(--text-muted); font-size: 0.82rem;">
            Connect a repository to view AI questions.
          </div>
        `;
      }
      return;
    }

    // 3. Decouple sub-tasks so failure or slow response in one does not block others
    const overviewPromise = (async () => {
      try {
        const data = await CodeMindAPI.getDashboardOverview(activeRepo.id);
        if (requestId !== currentDashboardRequestId) return;
        if (!data) return;

        if (greetingHeader && data.greeting) {
          greetingHeader.textContent = data.greeting;
        }

        if (data.active_repository) {
          const repo = data.active_repository;
          if (topbarRepo) topbarRepo.textContent = repo.name;
          if (topbarBranch) topbarBranch.textContent = repo.default_branch || 'main';
          if (bannerRepo) bannerRepo.textContent = repo.full_name;
          const fullSummary = repo.tech_stack?.summary?.full_summary || repo.primary_language || 'Polyglot';
          if (bannerDesc) bannerDesc.textContent = `${repo.description || 'Repository'} · ${fullSummary}`;

          if (techStackContainer) {
            try {
              techStackContainer.innerHTML = renderTechStackOverview(repo.tech_stack, repo.id);
            } catch (tsErr) {
              console.error('[hydrateDashboardView] Tech stack render error:', tsErr);
              techStackContainer.innerHTML = `
                <div style="padding: 24px 16px; text-align: center; color: var(--muted); font-size: 11.5px; width: 100%;">
                  No framework manifests or dependencies detected yet. Re-index repository to scan code.
                </div>
              `;
            }
            initTechStackScrollControls();
            setTimeout(updateTechStackScrollButtons, 50);
          }

          const isReady = repo.status === 'ready';
          const isIndexing = repo.status === 'indexing';
          const isFailed = repo.status === 'failed';

          if (healthText) {
            healthText.textContent = isReady
              ? 'Repository is ready'
              : isIndexing
              ? 'Indexing in progress'
              : isFailed
              ? 'Indexing failed'
              : 'Not indexed yet';
          }
          if (healthSub) {
            healthSub.textContent = isReady
              ? `${formatNumber(data.files_indexed || 0)} files indexed on ${repo.default_branch || 'main'}`
              : isIndexing
              ? `Extracting AST symbols on ${repo.default_branch || 'main'}...`
              : isFailed
              ? 'Indexing encountered an error'
              : `Click 'Index' to start code analysis`;
          }
          if (healthDot) {
            healthDot.className = isReady
              ? 'status-dot'
              : isIndexing
              ? 'status-dot warning'
              : isFailed
              ? 'status-dot danger'
              : 'status-dot neutral';
          }

          if (lastIndexedBtn) {
            lastIndexedBtn.textContent = repo.last_indexed_at ? `Last indexed ${formatTimeAgo(repo.last_indexed_at)}` : 'Not indexed';
          }

          // Display repository-specific metrics strictly from selected repository
          if (metricValues.length >= 4) {
            metricValues[0].textContent = formatNumber(data.files_indexed !== null && data.files_indexed !== undefined ? data.files_indexed : 0);
            metricValues[1].textContent = formatNumber(data.functions_classes !== null && data.functions_classes !== undefined ? data.functions_classes : 0);
            metricValues[2].textContent = formatNumber(data.apis_detected !== null && data.apis_detected !== undefined ? data.apis_detected : 0);
            metricValues[3].textContent = formatNumber(data.dependencies_mapped !== null && data.dependencies_mapped !== undefined ? data.dependencies_mapped : 0);
          }

          metricBadges.forEach(badge => {
            if (isReady && (data.files_indexed || 0) > 0) {
              badge.className = 'badge badge-success';
              badge.textContent = 'Indexed';
            } else if (isIndexing) {
              badge.className = 'badge badge-warning';
              badge.textContent = 'Indexing';
            } else if (isFailed) {
              badge.className = 'badge badge-danger';
              badge.textContent = 'Failed';
            } else {
              badge.className = 'badge badge-neutral';
              badge.textContent = 'Not Indexed';
            }
          });
        }

        if (questionsContainer) {
          if (!data.recent_questions || data.recent_questions.length === 0) {
            questionsContainer.innerHTML = `
              <div class="empty-state" style="padding: 18px 12px; text-align: center;">
                <p class="empty-state-desc" style="margin: 0 0 10px; font-size: 0.82rem; color: var(--text-muted);">No AI questions asked yet for this repository.</p>
                <a href="/assistant?repo=${activeRepo.id}" class="btn btn-secondary btn-sm" style="text-decoration:none;"><span>Ask your first question</span></a>
              </div>
            `;
          } else {
            questionsContainer.innerHTML = data.recent_questions.map(q => `
              <a href="/assistant?conversation_id=${encodeURIComponent(q.conversation_id)}&repo=${encodeURIComponent(activeRepo.id)}" class="activity-item" style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; border-bottom:1px solid var(--border); text-decoration:none; color:inherit; border-radius:6px; transition:background 0.2s;" onmouseover="this.style.background='var(--surface-subtle, rgba(255,255,255,0.03))'" onmouseout="this.style.background='transparent'">
                <div style="flex:1; min-width:0; margin-right:12px;">
                  <strong style="display:block; font-size:0.83rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text);">${escapeHtml(q.title || q.question)}</strong>
                  ${q.answer_preview ? `<small style="color:var(--muted); font-size:0.74rem; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:2px;">${escapeHtml(q.answer_preview)}</small>` : ''}
                </div>
                <small style="color:var(--muted); font-size:0.72rem; white-space:nowrap;">${formatRelativeTime(q.created_at)}</small>
              </a>
            `).join('');
          }
        }
      } catch (err) {
        if (requestId !== currentDashboardRequestId) return;
        console.error('[hydrateDashboardView] Overview request failed:', err);
        if (healthText) healthText.textContent = 'Metrics unavailable';
        if (healthSub) healthSub.textContent = 'Could not retrieve repository metrics from server';
        if (healthDot) healthDot.className = 'status-dot danger';
        metricValues.forEach(el => { el.textContent = '—'; });
        if (techStackContainer) {
          techStackContainer.innerHTML = `
            <div style="padding: 24px 16px; text-align: center; color: var(--muted); font-size: 11.5px; width: 100%;">
              Technology stack unavailable. <a href="javascript:void(0)" onclick="hydrateDashboardView(${activeRepo.id})" style="color: var(--primary); text-decoration: underline;">Retry</a>
            </div>
          `;
          initTechStackScrollControls();
        }
        if (questionsContainer) {
          questionsContainer.innerHTML = `
            <div style="padding: 24px 12px; text-align: center; color: var(--text-muted); font-size: 0.82rem;">
              Could not load repository investigations.
            </div>
          `;
        }
      }
    })();

    // 4. Hydrate Recent Commits for the selected repository independently
    const commitsPromise = (async () => {
      if (!commitsContainer) return;
      try {
        const commitsRes = await CodeMindAPI.getCommits(activeRepo.id, { perPage: 3 });
        if (requestId !== currentDashboardRequestId) return;
        if (commitsRes && commitsRes.commits && commitsRes.commits.length > 0) {
          commitsContainer.innerHTML = commitsRes.commits.map(c => {
            const author = escapeHtml(c.author_name || 'Contributor');
            let timeStr = '';
            if (c.author_date) {
              timeStr = formatRelativeTime(c.author_date);
            }
            if (!timeStr && c.time_ago && c.time_ago !== 'Recently') {
              timeStr = c.time_ago;
            } else if (!timeStr && c.committed_at) {
              timeStr = formatRelativeTime(c.committed_at);
            } else if (!timeStr) {
              timeStr = c.time_ago || 'Recently';
            }

            const fullMsg = escapeHtml(c.message || 'Commit');
            const firstLine = escapeHtml((c.message || 'Commit').split('\n')[0]);
            const shaShort = escapeHtml((c.short_sha || c.commit_sha || c.sha || '').substring(0, 7));

            return `
              <a href="/git_history?repo=${activeRepo.id}&sha=${encodeURIComponent(c.commit_sha || c.sha || '')}" class="commit-row" title="${fullMsg}">
                <div class="commit-main">
                  <strong class="commit-msg">${firstLine}</strong>
                  <div class="commit-meta">
                    <span>${author}</span>
                    <span>·</span>
                    <span>${escapeHtml(timeStr)}</span>
                  </div>
                </div>
                <code class="commit-sha-badge">${shaShort}</code>
              </a>
            `;
          }).join('');
        } else {
          commitsContainer.innerHTML = `
            <div style="padding: 24px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem;">
              No commits retrieved yet for this repository.
            </div>
          `;
        }
      } catch (e) {
        if (requestId !== currentDashboardRequestId) return;
        console.error('[hydrateDashboardView] Commits request failed:', e);
        commitsContainer.innerHTML = `
          <div style="padding: 24px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem;">
            Could not load commits (${escapeHtml(e.message || 'unavailable')}).
          </div>
        `;
      }
    })();

    // 5. Hydrate Architecture Overview for the selected repository independently
    const archPromise = (async () => {
      if (!archContainer) return;
      try {
        const graphRes = await CodeMindAPI.getRepositoryGraph(activeRepo.id, 12);
        if (requestId !== currentDashboardRequestId) return;
        if (graphRes && graphRes.nodes && graphRes.nodes.length > 0) {
          const displayNodes = graphRes.nodes.slice(0, 6);
          archContainer.innerHTML = `
            <div class="architecture-grid">
              ${displayNodes.map(n => {
                const rawType = (n.node_type || n.type || 'Component');
                const nodeType = rawType.toLowerCase();
                const typeBadgeClass = nodeType === 'class' ? 'badge-primary' :
                                       nodeType === 'function' ? 'badge-info' :
                                       nodeType === 'service' ? 'badge-warning' : 'badge-neutral';
                const fullName = escapeHtml(n.name || 'Component');
                const fullPath = escapeHtml(n.file_path || 'AST Symbol');
                return `
                  <a href="/dependencies?repo=${activeRepo.id}&node=${encodeURIComponent(n.name)}" class="arch-card-item" title="${fullName} (${fullPath})">
                    <div class="arch-card-header">
                      <span class="badge ${typeBadgeClass}" style="font-size: 0.68rem; text-transform: uppercase;">${escapeHtml(rawType)}</span>
                      <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false" style="color: var(--muted);"><path d="m9 18 6-6-6-6"/></svg>
                    </div>
                    <div>
                      <strong class="arch-card-name" title="${fullName}">${fullName}</strong>
                      <small class="arch-card-path" title="${fullPath}">${fullPath}</small>
                    </div>
                  </a>
                `;
              }).join('')}
            </div>
            ${graphRes.nodes.length > 6 ? `
              <div style="margin-top: 12px; text-align: right;">
                <a href="/dependencies?repo=${activeRepo.id}" style="font-size: 0.78rem; font-weight: 600; color: var(--primary); text-decoration: none;">
                  Explore all ${graphRes.nodes.length} entities in graph →
                </a>
              </div>
            ` : ''}
          `;
        } else {
          archContainer.innerHTML = `
            <div style="padding: 28px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem; width: 100%;">
              No architecture relationships mapped yet. Complete repository indexing to synthesize component architecture.
            </div>
          `;
        }
      } catch (e) {
        if (requestId !== currentDashboardRequestId) return;
        console.error('[hydrateDashboardView] Architecture graph request failed:', e);
        archContainer.innerHTML = `
          <div style="padding: 28px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem; width: 100%;">
            Could not load architecture graph (${escapeHtml(e.message || 'unavailable')}).
          </div>
        `;
      }
    })();

    await Promise.allSettled([overviewTask, commitsPromise, archPromise]);
  } catch (err) {
    console.warn('Error in hydrateDashboardView:', err);
  }
}

async function getActiveRepository() {
  try {
    const repos = await CodeMindAPI.getRepositories();
    if (!repos || repos.length === 0) return null;
    const urlParams = new URLSearchParams(window.location.search);
    const repoParam = urlParams.get('repo');
    if (repoParam) {
      const p = repoParam.trim().toLowerCase();
      const found = repos.find(r => 
        String(r.id) === p || 
        (r.name && r.name.toLowerCase() === p) ||
        (r.full_name && r.full_name.toLowerCase() === p)
      );
      if (found) {
        localStorage.setItem('codemind_active_repo_id', found.id);
        return found;
      }
    }
    const storedId = localStorage.getItem('codemind_active_repo_id');
    if (storedId) {
      const found = repos.find(r => r.id === parseInt(storedId));
      if (found) return found;
    }
    localStorage.setItem('codemind_active_repo_id', repos[0].id);
    return repos[0];
  } catch (err) {
    return null;
  }
}

// Global helper to switch active repository across CodeMind UI
window.switchActiveRepository = async function(repoId) {
  try {
    const repos = await CodeMindAPI.getRepositories();
    const target = (repos || []).find(r => r.id === parseInt(repoId));
    if (!target) return;

    localStorage.setItem('codemind_active_repo_id', target.id);
    sessionStorage.removeItem('codemind_active_conversation_id');

    // Update topbar header immediately
    const topbarRepo = document.querySelector('.repo-selector strong');
    const topbarBranch = document.getElementById('topbar-branch-text');
    if (topbarRepo) topbarRepo.textContent = target.name;
    if (topbarBranch) topbarBranch.textContent = target.default_branch || 'main';

    // Abort any in-flight assistant generation before switching repositories
    if (window.currentStreamAbortController) {
      window.currentStreamAbortController.abort();
      window.currentStreamAbortController = null;
    }

    // Immediately update sidebar security badge for the newly selected repository
    await updateSecuritySidebarBadge(target.id);

    const path = window.location.pathname;
    const isDashboard = path === '/' || path.includes('dashboard') || document.getElementById('view-overview');

    if (isDashboard) {
      const url = new URL(window.location);
      url.searchParams.set('repo', target.id);
      url.searchParams.delete('conversation_id');
      window.history.pushState({}, '', url);
      await hydrateDashboardView(target.id);
    } else {
      const url = new URL(window.location);
      url.searchParams.set('repo', target.id);
      url.searchParams.delete('conversation_id');
      window.location.href = url.toString();
    }
  } catch (err) {
    console.warn('Error switching repository:', err);
  }
};

// --- AI Code Assistant Hydration, Markdown Rendering & Chat History ---
function formatRelativeTime(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const diffSec = Math.floor((now - d) / 1000);
  if (diffSec < 45) return 'Just now';
  if (diffSec < 3600) return `${Math.max(1, Math.floor(diffSec / 60))}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 172800) return 'Yesterday';
  if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * ChatGPT-Style Markdown Parser & Sanitizer
 * Renders headings H1-H4, bold, italic, code blocks with syntax styling & copy buttons,
 * inline code, blockquotes/callouts, responsive tables, lists, and clickable citations.
 * Automatically sanitizes content to prevent XSS.
 */
/**
 * Universal Human-Readable Mathematical Formula Renderer (KaTeX)
 * Formats inline \( ... \) and display \[ ... \] equations cleanly.
 * Normalizes unescaped underscores in \text{...} and handles malformed math gracefully.
 */
function renderKatex(tex, isDisplay) {
  let cleanTex = String(tex || '').trim();
  if (!cleanTex) return '';

  // Normalize unescaped underscores inside \text{...} so LaTeX does not treat them as math subscripts
  cleanTex = cleanTex.replace(/\\text\{([^{}]+)\}/g, (m, t) => '\\text{' + t.replace(/_/g, '\\_') + '}');

  if (typeof katex !== 'undefined' && typeof katex.renderToString === 'function') {
    try {
      return katex.renderToString(cleanTex, {
        displayMode: isDisplay,
        throwOnError: false,
        errorColor: '#f87171'
      });
    } catch (e) {
      console.warn('KaTeX rendering error:', e);
    }
  }

  // Graceful fallback when KaTeX is unavailable or fails
  const escaped = escapeHtml(cleanTex);
  if (isDisplay) {
    return `<div class="katex-fallback"><code>\\[ ${escaped} \\]</code></div>`;
  }
  return `<span class="katex-fallback"><code>\\(${escaped}\\)</code></span>`;
}

function renderMarkdown(content, citations = []) {
  if (!content) return '';

  let text = String(content);

  // 1. Strip raw internal system delimiters, serialization artifacts, or leaked SVGs
  text = text.replace(/<<<[A-Za-z0-9_]+>>>[\s\S]*?<<<END_[A-Za-z0-9_]+>>>/g, '');
  text = text.replace(/\[DELIMITER_FILTERED\]/g, '');
  text = text.replace(/@@CM_[A-Za-z0-9_]+@@/g, '');
  text = text.replace(/<svg[\s\S]*?<\/svg>/gi, '');
  text = text.replace(/<svg[^>]*\/?>/gi, '');
  text = text.replace(/<\/svg>/gi, '');

  // 2. Protect fenced code blocks using collision-free tokens
  const codeBlocks = [];
  text = text.replace(/```([a-zA-Z0-9_-]*)[ \t]*\r?\n([\s\S]*?)(?:```|$)/g, (match, lang, code) => {
    const placeholder = `@@CM_CODE_BLOCK_${codeBlocks.length}@@`;
    codeBlocks.push({ lang: (lang || 'code').trim(), code: code });
    return `\n\n${placeholder}\n\n`;
  });

  // 3. Protect inline code using collision-free tokens
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (match, code) => {
    const placeholder = `@@CM_INLINE_CODE_${inlineCodes.length}@@`;
    inlineCodes.push(code);
    return placeholder;
  });

  // 3.5 Protect display math blocks using collision-free tokens
  const mathDisplayBlocks = [];
  // Match standard display delimiters \[ ... \] and $$ ... $$
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (match, tex) => {
    const placeholder = `@@CM_MATH_DISPLAY_${mathDisplayBlocks.length}@@`;
    mathDisplayBlocks.push(tex);
    return `\n\n${placeholder}\n\n`;
  });
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (match, tex) => {
    const placeholder = `@@CM_MATH_DISPLAY_${mathDisplayBlocks.length}@@`;
    mathDisplayBlocks.push(tex);
    return `\n\n${placeholder}\n\n`;
  });
  // Handle streaming response chunks that end with an unclosed display math delimiter
  text = text.replace(/\\\[([\s\S]+)$/, (match, tex) => {
    const placeholder = `@@CM_MATH_DISPLAY_${mathDisplayBlocks.length}@@`;
    mathDisplayBlocks.push(tex);
    return `\n\n${placeholder}\n\n`;
  });
  text = text.replace(/\$\$([\s\S]+)$/, (match, tex) => {
    const placeholder = `@@CM_MATH_DISPLAY_${mathDisplayBlocks.length}@@`;
    mathDisplayBlocks.push(tex);
    return `\n\n${placeholder}\n\n`;
  });
  // Clean up trailing unclosed delimiter without body during active streaming
  text = text.replace(/(?:\\\[|\$\$)$/, '');

  // 3.6 Protect inline math blocks using collision-free tokens
  const mathInlineBlocks = [];
  // Match standard inline delimiters \( ... \)
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, (match, tex) => {
    const placeholder = `@@CM_MATH_INLINE_${mathInlineBlocks.length}@@`;
    mathInlineBlocks.push(tex);
    return placeholder;
  });
  // Handle streaming response chunks that end with an unclosed inline math delimiter
  text = text.replace(/\\\(([\s\S]+)$/, (match, tex) => {
    const placeholder = `@@CM_MATH_INLINE_${mathInlineBlocks.length}@@`;
    mathInlineBlocks.push(tex);
    return placeholder;
  });
  // Clean up trailing unclosed inline delimiter without body during active streaming
  text = text.replace(/\\\($/, '');

  // Support inline $...$ when not currency (e.g. $E=mc^2$)
  text = text.replace(/(^|[^\\\$])\$(?!\d|\s)([^\$\n]+?)(?<!\s)\$(?!\$)/g, (match, prefix, tex) => {
    if (/^\s*\d+(?:\.\d+)?\s*$/.test(tex)) return match;
    const placeholder = `@@CM_MATH_INLINE_${mathInlineBlocks.length}@@`;
    mathInlineBlocks.push(tex);
    return `${prefix}${placeholder}`;
  });
  // Handle streaming unclosed inline $
  text = text.replace(/(^|[^\\\$])\$(?!\d|\s)([^\$\n]+)$/, (match, prefix, tex) => {
    if (/^\s*\d+(?:\.\d+)?\s*$/.test(tex)) return match;
    const placeholder = `@@CM_MATH_INLINE_${mathInlineBlocks.length}@@`;
    mathInlineBlocks.push(tex);
    return `${prefix}${placeholder}`;
  });

  // 4. HTML escape remaining prose for strict XSS prevention
  text = escapeHtml(text);

  // 5. Tables: detect markdown tables
  const tableRegex = /((?:^[ \t]*\|[^\n]+\|[ \t]*\n)+)/gm;
  text = text.replace(tableRegex, (match) => {
    const rawLines = match.trim().split('\n').map(l => l.trim());
    if (rawLines.length >= 2 && rawLines[1].includes('|') && /^[|\s\-:]+$/.test(rawLines[1])) {
      const parseCells = (row) => row.split('|').slice(1, -1).map(c => c.trim());
      const headerCells = parseCells(rawLines[0]);
      const bodyRows = rawLines.slice(2).map(parseCells);
      let tableHtml = '<div class="table-responsive"><table class="markdown-table"><thead><tr>';
      headerCells.forEach(h => { tableHtml += `<th>${h}</th>`; });
      tableHtml += '</tr></thead><tbody>';
      bodyRows.forEach(row => {
        tableHtml += '<tr>';
        row.forEach(cell => { tableHtml += `<td>${cell}</td>`; });
        tableHtml += '</tr>';
      });
      tableHtml += '</tbody></table></div>';
      return tableHtml + '\n\n';
    }
    return match;
  });

  // 6. Headings H1-H4
  text = text.replace(/^#### (.*?)$/gm, '<h4>$1</h4>');
  text = text.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
  text = text.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
  text = text.replace(/^# (.*?)$/gm, '<h1>$1</h1>');

  // 7. Blockquotes & Callouts
  text = text.replace(/^(?:&gt;|>)[ ]?\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ ]?\n?((?:(?:&gt;|>).*\n?)*)/gim, (match, type, body) => {
    const cleanBody = body.replace(/^(?:&gt;|>)[ ]?/gm, '').trim();
    const calloutClass = `callout-${type.toLowerCase()}`;
    return `<blockquote class="callout ${calloutClass}"><strong>${type.toUpperCase()}:</strong> ${cleanBody}</blockquote>\n\n`;
  });
  text = text.replace(/^(?:&gt;|>)[ ]?(.*)$/gm, '<blockquote>$1</blockquote>');
  text = text.replace(/<\/blockquote>\n<blockquote>/g, '<br>');

  // 8. Horizontal Rules
  text = text.replace(/^(?:---|\*\*\*|___)[ \t]*$/gm, '<hr class="markdown-divider">');

  // 9. Ordered & Unordered Lists
  const lines = text.split('\n');
  const outputLines = [];
  let inUl = false;
  let inOl = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const ulMatch = line.match(/^[ \t]*[-*+][ \t]+(.*)$/);
    const olMatch = line.match(/^[ \t]*(\d+)\.[ \t]+(.*)$/);

    if (ulMatch) {
      if (inOl) { outputLines.push('</ol>'); inOl = false; }
      if (!inUl) { outputLines.push('<ul>'); inUl = true; }
      outputLines.push(`<li>${ulMatch[1]}</li>`);
    } else if (olMatch) {
      if (inUl) { outputLines.push('</ul>'); inUl = false; }
      if (!inOl) { outputLines.push('<ol>'); inOl = true; }
      outputLines.push(`<li>${olMatch[2]}</li>`);
    } else {
      if (inUl) { outputLines.push('</ul>'); inUl = false; }
      if (inOl) { outputLines.push('</ol>'); inOl = false; }
      outputLines.push(line);
    }
  }
  if (inUl) outputLines.push('</ul>');
  if (inOl) outputLines.push('</ol>');
  text = outputLines.join('\n');

  // 10. Links: [anchor](url) - process before citations so [label](url) isn't mistaken for citations
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, href) => {
    const safeHref = (href.startsWith('http://') || href.startsWith('https://') || href.startsWith('/') || href.startsWith('code_viewer'))
      ? href : '#';
    return `<a href="${safeHref}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  // 11. Clickable citations: [Source 1: file.py (Lines 1-10)], [Source 1], [1]
  text = text.replace(/\[(?:Source\s+)?(\d+)(?::[^\]]+)?\]/gi, (match, idx) => {
    return `<button type="button" class="citation-pill" data-source-index="${idx}" title="View source citation [${idx}] in evidence panel">[${idx}]</button>`;
  });

  // 12. Bold and Italic (with word-boundary safety to preserve intra-word underscores like calculate_xyz_not_present)
  text = text.replace(/\*\*([^\*\n]+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/(^|\s)__([^_\n]+?)__(?=\s|[.,;:!?]|$)/g, '$1<strong>$2</strong>');
  text = text.replace(/(?<!\*)\*([^\*\n]+?)\*(?!\*)/g, '<em>$1</em>');
  text = text.replace(/(^|\s)_([^_\n]+?)_(?=\s|[.,;:!?]|$)/g, '$1<em>$2</em>');

  // 13. Paragraphs: split by double newlines
  const paragraphs = text.split(/\n\s*\n/);
  const formattedParas = paragraphs.map(p => {
    const trimmed = p.trim();
    if (!trimmed) return '';
    if (/^<(h[1-4]|ul|ol|blockquote|div|hr|table)/i.test(trimmed) || /^@@CM_CODE_BLOCK_\d+@@$/.test(trimmed) || /^@@CM_MATH_DISPLAY_\d+@@$/.test(trimmed)) {
      return trimmed;
    }
    const withBreaks = trimmed.replace(/\n/g, '<br>');
    return `<p>${withBreaks}</p>`;
  });
  text = formattedParas.filter(Boolean).join('\n\n');

  // 14. Restore inline code safely
  text = text.replace(/@@CM_INLINE_CODE_(\d+)@@/g, (match, idx) => {
    const code = inlineCodes[parseInt(idx)] || '';
    return `<code class="inline-code">${escapeHtml(code)}</code>`;
  });

  // 15. Restore code blocks with language badge and copy button
  text = text.replace(/@@CM_CODE_BLOCK_(\d+)@@/g, (match, idx) => {
    const block = codeBlocks[parseInt(idx)];
    if (!block) return '';
    const lang = block.lang || 'code';
    const escaped = escapeHtml(block.code);
    const rawForData = encodeURIComponent(block.code);
    return `
      <div class="code-block-wrapper">
        <div class="code-block-header">
          <span class="code-block-lang">${escapeHtml(lang)}</span>
          <button type="button" class="code-copy-btn" data-raw-code="${rawForData}" title="Copy code">
            <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            <span>Copy</span>
          </button>
        </div>
        <pre><code class="language-${escapeHtml(lang)}">${escaped}</code></pre>
      </div>
    `;
  });

  // 15.5 Restore display math
  text = text.replace(/@@CM_MATH_DISPLAY_(\d+)@@/g, (match, idx) => {
    const tex = mathDisplayBlocks[parseInt(idx)];
    if (tex === undefined) return '';
    const rendered = renderKatex(tex, true);
    return `<div class="math-display">${rendered}</div>`;
  });

  // 15.6 Restore inline math
  text = text.replace(/@@CM_MATH_INLINE_(\d+)@@/g, (match, idx) => {
    const tex = mathInlineBlocks[parseInt(idx)];
    if (tex === undefined) return '';
    const rendered = renderKatex(tex, false);
    return `<span class="math-inline">${rendered}</span>`;
  });

  // 16. Final safety sweep: strip any orphan placeholders before content reaches visible DOM
  text = text.replace(/@@CM_[A-Za-z0-9_]+@@/g, '');

  return text;
}

async function hydrateAssistantView() {
  let activeRepo = await getActiveRepository();
  let allLoadedRepos = [];
  try {
    allLoadedRepos = (await CodeMindAPI.getRepositories()) || [];
  } catch (e) {
    allLoadedRepos = [];
  }
  const assistantLayout = document.querySelector('.assistant-layout');
  const historySidebar = document.getElementById('history-sidebar');
  const historyToggleBtn = document.getElementById('history-toggle-btn');
  const historyCloseBtn = document.getElementById('history-close-btn');
  const historyBackdrop = document.getElementById('history-backdrop');
  const historyListEl = document.getElementById('history-conversations-list');
  const historyCountBadge = document.getElementById('history-count-badge');
  const historySearchInput = document.getElementById('history-search-input');
  const historySearchClear = document.getElementById('history-search-clear');
  const historyNewBtn = document.getElementById('history-new-btn');
  const btnNewConversation = document.getElementById('btn-new-conversation');

  const titleEl = document.getElementById('assistant-conversation-title') || document.querySelector('.assistant-header h1');
  const subtitleEl = document.getElementById('assistant-repo-subtitle') || document.querySelector('.assistant-header p');
  const composerTag = document.querySelector('.composer span');
  const sendBtn = document.querySelector('.send-btn');
  const textarea = document.querySelector('.composer textarea');
  const messagesContainer = document.querySelector('.messages');

  // Modals
  const deleteModal = document.getElementById('delete-modal-backdrop');
  const deleteModalTitle = document.getElementById('delete-modal-conv-title');
  const deleteModalConfirm = document.getElementById('delete-modal-confirm');
  const deleteModalCancel = document.getElementById('delete-modal-cancel');
  const deleteModalClose = document.getElementById('delete-modal-close');
  const deleteModalError = document.getElementById('delete-modal-error');
  const deleteModalErrorText = document.getElementById('delete-modal-error-text');

  const renameModal = document.getElementById('rename-modal-backdrop');
  const renameInput = document.getElementById('rename-input');
  const renameModalConfirm = document.getElementById('rename-modal-confirm');
  const renameModalCancel = document.getElementById('rename-modal-cancel');
  const renameModalClose = document.getElementById('rename-modal-close');

  let currentConversationId = null;
  let conversationsCache = [];
  let isSending = false;
  let isDeleting = false;
  let activeLoadingConvId = null;
  let pendingDeleteId = null;
  let pendingRenameId = null;
  let searchTimeout = null;
  let currentStreamAbortController = null;

  // Auto-resize textarea
  function autoResizeTextarea() {
    if (!textarea) return;
    textarea.style.height = 'auto';
    const newH = Math.min(Math.max(textarea.scrollHeight, 44), 160);
    textarea.style.height = newH + 'px';
  }

  // Auto-scroll helper: only scrolls if user was near bottom or forced
  function scrollToLatest(force = false) {
    if (!messagesContainer) return;
    const threshold = 160;
    const isNearBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight < threshold;
    if (force || isNearBottom) {
      messagesContainer.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
    }
  }

  // Update header context tags
  function updateHeaderContext(repoName, branch) {
    const rName = repoName || activeRepo?.name || 'acme-platform';
    const rBranch = branch || activeRepo?.default_branch || 'main';
    if (subtitleEl) {
      subtitleEl.innerHTML = `${escapeHtml(rName)} <span>·</span> ${escapeHtml(rBranch)} <span>·</span> Hybrid retrieval`;
    }
    if (composerTag) {
      composerTag.innerHTML = `
        <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg> ${escapeHtml(rName)} <b>·</b>
        <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="6" cy="5" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="6" cy="19" r="2"/><path d="M6 7v10M8 7c5 0 4-2 8-2"/></svg> ${escapeHtml(rBranch)}
      `;
    }
  }

  updateHeaderContext();
  initEvidenceTabs();

  // --- Load Conversation List ---
  async function loadHistory(query = '') {
    if (!historyListEl) return;
    try {
      const data = await CodeMindAPI.getAssistantConversations({ search: query });
      conversationsCache = data || [];
      if (historyCountBadge) historyCountBadge.textContent = conversationsCache.length;

      if (conversationsCache.length === 0) {
        historyListEl.innerHTML = `
          <div class="history-empty">
            <svg class="icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
            <p>${query ? 'No matching conversations' : 'No previous conversations'}</p>
            <small>${query ? 'Try a different search term.' : 'Ask a question below to start your first conversation.'}</small>
          </div>
        `;
        return;
      }

      historyListEl.innerHTML = conversationsCache.map(conv => {
        const isActive = conv.id === currentConversationId;
        const timeAgo = formatRelativeTime(conv.updated_at || conv.created_at);
        const repoBadge = conv.repository_name ? `<span class="history-item-repo">${escapeHtml(conv.repository_name)}${conv.branch ? ' · ' + escapeHtml(conv.branch) : ''}</span>` : '';
        const previewText = conv.last_message_preview || 'No messages yet';

        return `
          <div class="history-item ${isActive ? 'active' : ''}" data-conv-id="${conv.id}">
            <div class="history-item-top">
              <span class="history-item-title" title="${escapeHtml(conv.title)}">${escapeHtml(conv.title)}</span>
              <div class="history-item-actions">
                <button type="button" class="history-action-btn rename-btn" data-conv-id="${conv.id}" title="Rename conversation">
                  <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                <button type="button" class="history-action-btn delete-btn" data-conv-id="${conv.id}" title="Delete conversation">
                  <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </div>
            </div>
            <div class="history-item-preview">${escapeHtml(previewText)}</div>
            <div class="history-item-meta">
              ${repoBadge}
              <time>${timeAgo}</time>
            </div>
          </div>
        `;
      }).join('');

      // Wire item clicks
      historyListEl.querySelectorAll('.history-item').forEach(el => {
        el.addEventListener('click', (e) => {
          if (e.target.closest('.history-action-btn')) return;
          const convId = parseInt(el.getAttribute('data-conv-id'));
          if (convId && convId !== currentConversationId) {
            openConversation(convId);
          }
        });
      });

      // Wire rename buttons
      historyListEl.querySelectorAll('.rename-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          e.preventDefault();
          const convId = parseInt(btn.getAttribute('data-conv-id'));
          const conv = conversationsCache.find(c => c.id === convId);
          if (conv) showRenameModal(conv);
        });
      });

      // Wire delete buttons
      historyListEl.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          e.preventDefault();
          const convId = parseInt(btn.getAttribute('data-conv-id'));
          const conv = conversationsCache.find(c => c.id === convId);
          if (conv) showDeleteModal(conv);
        });
      });

    } catch (err) {
      historyListEl.innerHTML = `
        <div class="history-empty" style="color:var(--status-danger);">
          <p>Failed to load history</p>
          <small>${escapeHtml(err.message || 'Server error')}</small>
        </div>
      `;
    }
  }

  let currentHistoryAbortController = null;
  const initialEmptyPromptHtml = document.getElementById('assistant-empty-prompt')?.outerHTML || '';

  // --- Open Conversation ---
  async function openConversation(convId) {
    if (currentStreamAbortController) {
      try { currentStreamAbortController.abort(); } catch (_) {}
      currentStreamAbortController = null;
    }
    if (currentHistoryAbortController) {
      try { currentHistoryAbortController.abort(); } catch (_) {}
      currentHistoryAbortController = null;
    }
    currentHistoryAbortController = new AbortController();

    isSending = false;
    activeLoadingConvId = convId;
    currentConversationId = convId;
    sessionStorage.setItem('codemind_active_conversation_id', String(convId));

    // Reset composer state immediately
    const stopBtn = document.getElementById('stop-generating-btn');
    if (stopBtn) stopBtn.style.display = 'none';
    if (sendBtn) {
      sendBtn.style.display = 'grid';
      sendBtn.disabled = !textarea?.value?.trim();
    }
    if (textarea) {
      textarea.disabled = false;
      autoResizeTextarea();
    }

    // Update active highlight
    historyListEl?.querySelectorAll('.history-item').forEach(el => {
      if (parseInt(el.getAttribute('data-conv-id')) === convId) {
        el.classList.add('active');
      } else {
        el.classList.remove('active');
      }
    });

    // Close mobile history if open
    if (assistantLayout) assistantLayout.classList.remove('history-open');

    // Reset center panel scroll position immediately when switching conversations
    if (messagesContainer) messagesContainer.scrollTop = 0;

    // Show conversation loading skeleton immediately
    messagesContainer.innerHTML = `
      <div class="conversation-skeleton-container" role="status" aria-label="Loading conversation history">
        <div class="conv-skeleton-msg">
          <div class="conv-skeleton-avatar"></div>
          <div class="conv-skeleton-bubble">
            <div class="conv-skeleton-line short"></div>
            <div class="conv-skeleton-line medium"></div>
          </div>
        </div>
        <div class="conv-skeleton-msg" style="align-self: flex-start; width: 100%;">
          <div class="conv-skeleton-avatar" style="background:#e0e7ff;"></div>
          <div class="conv-skeleton-bubble">
            <div class="conv-skeleton-line long"></div>
            <div class="conv-skeleton-line medium"></div>
            <div class="conv-skeleton-line short"></div>
          </div>
        </div>
      </div>
    `;

    try {
      const conv = await CodeMindAPI.getAssistantConversation(convId, {
        signal: currentHistoryAbortController.signal
      });
      if (activeLoadingConvId !== convId) return;

      if (conv.repository_id) {
        const repoList = (typeof allLoadedRepos !== 'undefined' && Array.isArray(allLoadedRepos) && allLoadedRepos.length > 0)
          ? allLoadedRepos
          : (await CodeMindAPI.getRepositories().catch(() => [])) || [];
        allLoadedRepos = repoList;

        const matchedRepo = repoList.find(r => r.id === conv.repository_id);
        activeRepo = matchedRepo || {
          id: conv.repository_id,
          name: conv.repository_name,
          default_branch: conv.branch || 'main'
        };
        localStorage.setItem('codemind_active_repo_id', String(conv.repository_id));

        // Update topbar repo selector to match the conversation
        const topbarRepo = document.querySelector('.repo-selector strong');
        const topbarBranch = document.getElementById('topbar-branch-text');
        if (topbarRepo && activeRepo.name) topbarRepo.textContent = activeRepo.name;
        if (topbarBranch) topbarBranch.textContent = activeRepo.default_branch || conv.branch || 'main';
      }

      if (titleEl) titleEl.textContent = conv.title || 'AI Code Assistant';
      updateHeaderContext(conv.repository_name || (activeRepo ? activeRepo.name : null), conv.branch || (activeRepo ? activeRepo.default_branch : null));

      messagesContainer.innerHTML = '';

      const msgs = Array.isArray(conv.messages) ? [...conv.messages] : [];
      msgs.sort((a, b) => (a.id || 0) - (b.id || 0));

      if (msgs.length === 0) {
        messagesContainer.innerHTML = initialEmptyPromptHtml;
        messagesContainer.querySelectorAll('.suggestion-prompt-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            const text = btn.querySelector('span')?.textContent?.trim();
            if (text && textarea) {
              textarea.value = text;
              autoResizeTextarea();
              handleSend(text);
            }
          });
        });
        return;
      }

      let lastCitations = [];

      msgs.forEach(msg => {
        try {
          if (msg.role === 'user') {
            const userContent = msg.content || '';
            const userHtml = `
              <div class="user-message">
                <span class="avatar">You</span>
                <div>
                  <span>You</span>
                  <p>${escapeHtml(userContent)}</p>
                </div>
              </div>
            `;
            messagesContainer.insertAdjacentHTML('beforeend', userHtml);
          } else if (msg.role === 'assistant') {
            const isFailed = msg.status === 'failed';
            const isCancelled = msg.status === 'cancelled';
            const citations = Array.isArray(msg.citations) ? msg.citations : [];
            if (citations.length > 0) lastCitations = citations;

            let citationsBadge = citations.length > 0
              ? `<span class="badge badge-success"><svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg> <span class="badge-text">${citations.length} sources verified</span></span>`
              : `<span class="badge badge-neutral">No source matches</span>`;

            if (isFailed) {
              citationsBadge = `<span class="badge badge-danger">Generation Error</span>`;
            } else if (isCancelled) {
              citationsBadge = `<span class="badge badge-neutral stream-status-badge"><span class="badge-text">Generation stopped</span></span>`;
            }

            let metadata = (typeof msg.evidence_metadata === 'object' && msg.evidence_metadata !== null) ? msg.evidence_metadata : {};
            let relatedHtml = '';
            if (Array.isArray(metadata.related_components) && metadata.related_components.length > 0) {
              relatedHtml = `
                <div style="margin-top:14px;">
                  <h3 style="font-size:11.5px; margin:0 0 6px;">Related components</h3>
                  <div class="related-grid">
                    ${metadata.related_components.map(c => `
                      <a href="/code_viewer?repo=${activeRepo ? activeRepo.id : ''}&file=${encodeURIComponent(c.file_path || '')}" style="text-decoration:none;">
                        <button type="button">
                          <span class="type-icon ${c.type === 'class' ? 'middleware' : 'service'}">${c.type ? c.type[0].toUpperCase() : 'C'}</span>
                          <span>
                            <strong>${escapeHtml(c.name)}</strong>
                            <small>${escapeHtml(c.file_path || 'Repository component')}</small>
                          </span>
                          <span class="badge ${c.impact_level === 'DIRECT' ? 'badge-danger' : 'badge-warning'}">${c.impact_level || 'DIRECT'}</span>
                        </button>
                      </a>
                    `).join('')}
                  </div>
                </div>
              `;
            }

            let riskHtml = '';
            if (metadata.risk_callout && metadata.risk_callout.summary) {
              riskHtml = `
                <div class="risk-callout">
                  <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 3v4M21 12h-4M12 21v-4M3 12h4"/></svg>
                  <div>
                    <strong>Potential impact</strong>
                    <p>${escapeHtml(metadata.risk_callout.summary)}</p>
                    <a href="/impact_analysis" style="text-decoration:none; display:inline-flex; align-items:center; gap:4px; font-weight:700; font-size:8.5px; color:#92400e;">
                      Analyze change impact →
                    </a>
                  </div>
                </div>
              `;
            }

            let factsHtml = '';
            if (metadata.facts) {
              factsHtml = `
                <div class="facts">
                  <span><i class="fact-dot confirmed"></i>Confirmed facts <b>${metadata.facts.confirmed || 0}</b></span>
                  <span><i class="fact-dot inference"></i>Inferences <b>${metadata.facts.inferences || 0}</b></span>
                  <span><i class="fact-dot unknown"></i>Unknowns <b>${metadata.facts.unknowns || 0}</b></span>
                </div>
              `;
            }

            let retryHtml = '';
            if (isFailed || isCancelled) {
              retryHtml = `
                <div style="margin-top:10px;">
                  <button type="button" class="btn btn-secondary btn-sm retry-msg-btn">
                    <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                    <span>${isCancelled ? 'Retry question' : 'Retry response'}</span>
                  </button>
                </div>
              `;
            }

            let renderedLead = renderMarkdown(msg.content || '', citations);
            if (isCancelled && !renderedLead.includes('Generation stopped') && !renderedLead.includes('Response cancelled')) {
              renderedLead += `
                <div class="generation-stopped-notice" style="margin-top:10px; display:inline-flex; align-items:center; gap:6px; font-size:11.5px; color:var(--text-muted); padding:4px 8px; background:var(--surface-subtle); border-radius:4px; border:1px solid var(--border);">
                  <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true" focusable="false"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
                  <span>Response cancelled</span>
                </div>
              `;
            }

            const asstHtml = `
              <div class="ai-message ${isFailed ? 'ai-failed' : ''}">
                <div class="ai-message-head">
                  <span class="ai-orb">
                    <svg class="icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m12 3-1.7 4.3L6 9l4.3 1.7L12 15l1.7-4.3L18 9l-4.3-1.7L12 3Z"/><path d="m5 15-.8 2.2L2 18l2.2.8L5 21l.8-2.2L8 18l-2.2-.8L5 15Z"/></svg>
                  </span>
                  <div class="ai-title-wrap">
                    <strong class="brand-title">CodeMind</strong>
                    ${citationsBadge}
                  </div>
                </div>
                <div class="answer">
                  <div class="answer-lead markdown-body">${renderedLead}</div>
                  ${relatedHtml}
                  ${riskHtml}
                  ${factsHtml}
                  <div class="msg-actions">
                    <button type="button" class="msg-action-btn copy-answer-btn" title="Copy response to clipboard" aria-label="Copy response to clipboard">
                      <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                      <span class="btn-label">Copy</span>
                    </button>
                    <button type="button" class="msg-action-btn feedback-good-btn" title="Helpful response">
                      <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
                    </button>
                    <button type="button" class="msg-action-btn feedback-bad-btn" title="Not helpful">
                      <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>
                    </button>
                  </div>
                  ${retryHtml}
                </div>
              </div>
            `;
            messagesContainer.insertAdjacentHTML('beforeend', asstHtml);
          }
        } catch (msgErr) {
          console.warn('[CodeMind] Error rendering message in conversation:', msgErr);
        }
      });

      // Populate evidence panel with last available citations
      populateEvidencePanel(lastCitations, { name: conv.repository_name, current_revision: conv.branch });

      // Position chat at the latest message at the bottom on initial load
      requestAnimationFrame(() => {
        if (activeLoadingConvId === convId && messagesContainer) {
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
      });

      // Update URL query state
      const url = new URL(window.location);
      url.searchParams.set('conversation_id', convId);
      if (conv.repository_id) {
        url.searchParams.set('repo', conv.repository_id);
      }
      window.history.pushState({}, '', url);

    } catch (err) {
      if (err.name === 'AbortError' || currentHistoryAbortController?.signal?.aborted) {
        return; // Stale request cancelled by newer conversation switch
      }
      if (activeLoadingConvId !== convId) return;
      messagesContainer.innerHTML = `
        <div class="assistant-error" role="alert">
          <svg class="icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
          <h2>Unable to load conversation</h2>
          <p>${escapeHtml(err.message || 'Conversation could not be loaded.')}</p>
          <div style="display:flex; justify-content:center; gap:8px; margin-top:14px;">
            <button type="button" class="btn btn-secondary" id="retry-load-conv-btn">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
              <span>Retry</span>
            </button>
            <button type="button" class="btn btn-primary" id="error-new-conv">Start new conversation</button>
          </div>
        </div>
      `;
      document.getElementById('retry-load-conv-btn')?.addEventListener('click', () => openConversation(convId));
      document.getElementById('error-new-conv')?.addEventListener('click', startNewConversation);
    }
  }

  // --- Start New Conversation ---
  async function startNewConversation() {
    if (currentStreamAbortController) {
      currentStreamAbortController.abort();
      currentStreamAbortController = null;
    }
    if (currentHistoryAbortController) {
      currentHistoryAbortController.abort();
      currentHistoryAbortController = null;
    }
    isSending = false;
    currentConversationId = null;
    sessionStorage.removeItem('codemind_active_conversation_id');
    activeRepo = await getActiveRepository();
    if (titleEl) titleEl.textContent = 'AI Code Assistant';
    updateHeaderContext(activeRepo ? activeRepo.name : null, activeRepo ? activeRepo.default_branch : 'main');

    // Reset composer state
    let stopBtn = document.getElementById('stop-generating-btn');
    if (stopBtn) stopBtn.style.display = 'none';
    if (sendBtn) sendBtn.style.display = 'grid';
    if (textarea) {
      textarea.disabled = false;
      textarea.value = '';
      autoResizeTextarea();
      textarea.focus();
    }

    // Reset evidence panel
    populateEvidencePanel([], activeRepo);

    // Unselect sidebar items
    if (historyListEl) {
      historyListEl.querySelectorAll('.history-item').forEach(el => el.classList.remove('active'));
    }

    // Restore empty prompt
    if (messagesContainer) {
      messagesContainer.innerHTML = initialEmptyPromptHtml;
      messagesContainer.querySelectorAll('.suggestion-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const text = btn.querySelector('span')?.textContent?.trim();
          if (text && textarea) {
            textarea.value = text;
            autoResizeTextarea();
            handleSend(text);
          }
        });
      });
    }

    const url = new URL(window.location);
    url.searchParams.delete('conversation_id');
    window.history.pushState({}, '', url);

    if (assistantLayout) assistantLayout.classList.remove('history-open');
    if (textarea) {
      textarea.value = '';
      autoResizeTextarea();
      textarea.focus();
    }
    if (sendBtn) sendBtn.disabled = true;
  }

  // --- Modals logic ---
  function showDeleteModal(conv) {
    if (isDeleting) return;
    pendingDeleteId = conv.id;
    if (deleteModalTitle) deleteModalTitle.textContent = `"${conv.title}"`;
    if (deleteModalError) deleteModalError.style.display = 'none';
    if (deleteModalConfirm) {
      deleteModalConfirm.disabled = false;
      deleteModalConfirm.textContent = 'Delete';
    }
    if (deleteModalCancel) deleteModalCancel.disabled = false;
    if (deleteModal) deleteModal.style.display = 'flex';
  }

  function hideDeleteModal() {
    if (isDeleting) return;
    pendingDeleteId = null;
    if (deleteModalError) deleteModalError.style.display = 'none';
    if (deleteModal) deleteModal.style.display = 'none';
  }

  if (deleteModalCancel) deleteModalCancel.addEventListener('click', hideDeleteModal);
  if (deleteModalClose) deleteModalClose.addEventListener('click', hideDeleteModal);
  if (deleteModalConfirm) {
    deleteModalConfirm.addEventListener('click', async () => {
      if (!pendingDeleteId || isDeleting) return;
      const targetId = pendingDeleteId;
      isDeleting = true;
      deleteModalConfirm.disabled = true;
      deleteModalConfirm.textContent = 'Deleting...';
      if (deleteModalCancel) deleteModalCancel.disabled = true;
      if (deleteModalError) deleteModalError.style.display = 'none';

      try {
        await CodeMindAPI.deleteAssistantConversation(targetId);

        // Remove from memory cache
        conversationsCache = conversationsCache.filter(c => c.id !== targetId);
        if (historyCountBadge) historyCountBadge.textContent = conversationsCache.length;

        // Remove item from sidebar DOM immediately
        const itemEl = historyListEl?.querySelector(`.history-item[data-conv-id="${targetId}"]`);
        if (itemEl) itemEl.remove();

        // If list is now empty, render empty state
        if (conversationsCache.length === 0 && historyListEl) {
          historyListEl.innerHTML = `
            <div class="history-empty">
              <svg class="icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
              <p>No previous conversations</p>
              <small>Ask a question below to start your first conversation.</small>
            </div>
          `;
        }

        isDeleting = false;
        pendingDeleteId = null;
        if (deleteModal) deleteModal.style.display = 'none';

        // If the deleted conversation was active, reset center panel & URL state
        if (currentConversationId === targetId) {
          startNewConversation();
        }
        // If another conversation was active, keep it uninterrupted!
      } catch (err) {
        isDeleting = false;
        deleteModalConfirm.disabled = false;
        deleteModalConfirm.textContent = 'Retry Delete';
        if (deleteModalCancel) deleteModalCancel.disabled = false;
        if (deleteModalError) {
          deleteModalError.style.display = 'block';
          if (deleteModalErrorText) {
            deleteModalErrorText.textContent = `Deletion failed: ${err.message || 'Server error'}. Click Retry Delete to try again.`;
          }
        }
      }
    });
  }

  function showRenameModal(conv) {
    pendingRenameId = conv.id;
    if (renameInput) renameInput.value = conv.title || '';
    if (renameModal) renameModal.style.display = 'flex';
    if (renameInput) renameInput.focus();
  }

  function hideRenameModal() {
    pendingRenameId = null;
    if (renameModal) renameModal.style.display = 'none';
  }

  if (renameModalCancel) renameModalCancel.addEventListener('click', hideRenameModal);
  if (renameModalClose) renameModalClose.addEventListener('click', hideRenameModal);
  if (renameModalConfirm) {
    renameModalConfirm.addEventListener('click', async () => {
      if (!pendingRenameId) return;
      const newTitle = renameInput ? renameInput.value.trim() : '';
      if (!newTitle) return;
      try {
        await CodeMindAPI.updateAssistantConversation(pendingRenameId, { title: newTitle });
        hideRenameModal();
        if (currentConversationId === pendingRenameId && titleEl) {
          titleEl.textContent = newTitle;
        }
        await loadHistory(historySearchInput?.value?.trim() || '');
      } catch (err) {
        alert('Failed to rename conversation: ' + (err.message || 'Unknown error'));
        hideRenameModal();
      }
    });
  }

  // --- Send Message & Question Answering (Streaming SSE) ---
  async function handleSend(retryQuestion = null) {
    const q = retryQuestion || textarea?.value?.trim();
    if (!q || isSending) return;

    if (!activeRepo) {
      alert('Please connect and index a repository first.');
      return;
    }

    let requestConvId = currentConversationId;
    isSending = true;
    if (sendBtn) sendBtn.disabled = true;
    if (!retryQuestion && textarea) {
      textarea.value = '';
      autoResizeTextarea();
    }

    // Hide empty starter prompt
    const emptyPrompt = document.getElementById('assistant-empty-prompt');
    if (emptyPrompt) emptyPrompt.style.display = 'none';

    // If new question, append user message
    if (!retryQuestion) {
      const userMsgHtml = `
        <div class="user-message">
          <span class="avatar">You</span>
          <div>
            <span>You</span>
            <p>${escapeHtml(q)}</p>
          </div>
        </div>
      `;
      messagesContainer.insertAdjacentHTML('beforeend', userMsgHtml);
      requestAnimationFrame(() => {
        if (messagesContainer) messagesContainer.scrollTop = messagesContainer.scrollHeight;
      });
    }

    // Create streaming AI message container with immediate thinking placeholder
    const aiMsgId = 'ai-stream-' + Date.now();
    const aiMsgHtml = `
      <div class="ai-message" id="${aiMsgId}">
        <div class="ai-message-head">
          <span class="ai-orb pulsing">
            <svg class="icon animate-spin" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
          </span>
          <div class="ai-title-wrap">
            <strong class="brand-title">CodeMind</strong>
            <span class="badge badge-neutral stream-status-badge"><span class="badge-text">Searching your codebase...</span></span>
          </div>
        </div>
        <div class="answer">
          <div class="assistant-thinking-state" id="${aiMsgId}-thinking" role="status" aria-live="polite">
            <div class="thinking-header">
              <div class="thinking-spinner">
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
              </div>
              <span class="thinking-label">Searching your codebase...</span>
            </div>
            <div class="thinking-shimmer-bar"></div>
          </div>
          <div class="answer-lead markdown-body live-token-body" style="display:none;"></div>
          <div class="related-container"></div>
          <div class="risk-container"></div>
          <div class="facts" style="display:none;"></div>
          <div class="msg-actions" style="display:none;"></div>
        </div>
      </div>
    `;
    messagesContainer.insertAdjacentHTML('beforeend', aiMsgHtml);
    requestAnimationFrame(() => {
      if (messagesContainer) messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });

    const aiMsgEl = document.getElementById(aiMsgId);
    const liveTokenBody = aiMsgEl ? aiMsgEl.querySelector('.live-token-body') : null;
    const thinkingEl = aiMsgEl ? aiMsgEl.querySelector('.assistant-thinking-state') : null;
    const thinkingLabel = thinkingEl ? thinkingEl.querySelector('.thinking-label') : null;
    const statusBadge = aiMsgEl ? aiMsgEl.querySelector('.stream-status-badge') : null;

    function resetComposerState() {
      isSending = false;
      currentStreamAbortController = null;
      window.currentStreamAbortController = null;
      const curStopBtn = document.getElementById('stop-generating-btn');
      if (curStopBtn) curStopBtn.style.display = 'none';
      if (sendBtn) {
        sendBtn.style.display = 'grid';
        sendBtn.disabled = !textarea?.value?.trim();
      }
      if (textarea) {
        textarea.disabled = false;
        textarea.focus();
      }
    }

    // Show stop button in composer and hide send button
    let stopBtn = document.getElementById('stop-generating-btn');
    if (!stopBtn && sendBtn && sendBtn.parentNode) {
      stopBtn = document.createElement('button');
      stopBtn.id = 'stop-generating-btn';
      stopBtn.type = 'button';
      stopBtn.className = 'stop-btn';
      stopBtn.title = 'Stop generating';
      stopBtn.setAttribute('aria-label', 'Stop generating');
      stopBtn.innerHTML = '<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true" focusable="false"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';
      sendBtn.parentNode.insertBefore(stopBtn, sendBtn.nextSibling);
    }
    if (stopBtn) {
      stopBtn.style.display = 'grid';
      stopBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (currentStreamAbortController) {
          try { currentStreamAbortController.abort(); } catch (_) {}
        }
        resetComposerState();
      };
    }
    if (sendBtn) sendBtn.style.display = 'none';
    if (textarea) textarea.disabled = true;

    currentStreamAbortController = new AbortController();
    window.currentStreamAbortController = currentStreamAbortController;
    let accumulatedTokens = '';
    let streamCitations = [];

    try {
      const onEvent = async (event, data) => {
        // If user navigated away or switched conversation, ignore
        if (requestConvId !== null && currentConversationId !== requestConvId) {
          return;
        }

        if (event === 'meta') {
          if (data && data.conversation_id && !currentConversationId) {
            currentConversationId = data.conversation_id;
            requestConvId = currentConversationId;
            sessionStorage.setItem('codemind_active_conversation_id', String(currentConversationId));
            const url = new URL(window.location);
            url.searchParams.set('conversation_id', currentConversationId);
            window.history.pushState({}, '', url);
          }
        } else if (event === 'status') {
          const msg = (data && data.message) || 'Thinking through the code...';
          if (thinkingLabel) {
            thinkingLabel.textContent = msg;
          }
          if (statusBadge && !statusBadge.classList.contains('badge-success')) {
            const badgeTextEl = statusBadge.querySelector('.badge-text');
            if (badgeTextEl) badgeTextEl.textContent = msg;
          }
        } else if (event === 'citation') {
          if (data && Array.isArray(data.citations) && data.citations.length > 0) {
            streamCitations = data.citations;
            populateEvidencePanel(streamCitations, activeRepo);
            if (statusBadge) {
              statusBadge.className = 'badge badge-success stream-status-badge';
              statusBadge.innerHTML = `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg> <span class="badge-text">${streamCitations.length} sources verified</span>`;
            }
            if (thinkingLabel) {
              thinkingLabel.textContent = 'Thinking through verified code...';
            }
          }
        } else if (event === 'token') {
          // Hide thinking state immediately when first token arrives
          if (thinkingEl && thinkingEl.style.display !== 'none') {
            thinkingEl.style.display = 'none';
          }
          if (liveTokenBody && liveTokenBody.style.display === 'none') {
            liveTokenBody.style.display = 'block';
          }
          accumulatedTokens += (data && data.token) || '';
          if (liveTokenBody) {
            liveTokenBody.innerHTML = renderMarkdown(accumulatedTokens, streamCitations);
          }
          // Only auto-scroll if near bottom
          const threshold = 180;
          const wasNearBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight < threshold;
          if (wasNearBottom) {
            messagesContainer.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
          }
        } else if (event === 'done') {
          if (thinkingEl) thinkingEl.style.display = 'none';
          if (liveTokenBody) liveTokenBody.style.display = 'block';
          const finalAnswer = (data && data.answer) || accumulatedTokens;
          const finalCitations = (data && data.citations) || streamCitations;
          if (liveTokenBody) {
            liveTokenBody.innerHTML = renderMarkdown(finalAnswer, finalCitations);
          }

          // Convert orb back to normal
          const orb = aiMsgEl ? aiMsgEl.querySelector('.ai-orb') : null;
          if (orb) {
            orb.classList.remove('pulsing');
            orb.innerHTML = `<svg class="icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m12 3-1.7 4.3L6 9l4.3 1.7L12 15l1.7-4.3L18 9l-4.3-1.7L12 3Z"/><path d="m5 15-.8 2.2L2 18l2.2.8L5 21l.8-2.2L8 18l-2.2-.8L5 15Z"/></svg>`;
          }

          // Update citation badge
          if (statusBadge) {
            if (finalCitations && finalCitations.length > 0) {
              statusBadge.className = 'badge badge-success';
              statusBadge.innerHTML = `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg> <span class="badge-text">${finalCitations.length} sources verified</span>`;
            } else {
              statusBadge.className = 'badge badge-neutral';
              statusBadge.innerHTML = `<span class="badge-text">No source matches</span>`;
            }
          }

          // Render facts
          const factsEl = aiMsgEl ? aiMsgEl.querySelector('.facts') : null;
          if (factsEl && data && data.facts) {
            factsEl.style.display = 'flex';
            factsEl.innerHTML = `
              <span><i class="fact-dot confirmed"></i>Confirmed facts <b>${data.facts?.confirmed || 0}</b></span>
              <span><i class="fact-dot inference"></i>Inferences <b>${data.facts?.inferences || 0}</b></span>
              <span><i class="fact-dot unknown"></i>Unknowns <b>${data.facts?.unknowns || 0}</b></span>
            `;
          }

          // Related components
          if (data && data.related_components && data.related_components.length > 0) {
            const relContainer = aiMsgEl ? aiMsgEl.querySelector('.related-container') : null;
            if (relContainer) {
              relContainer.innerHTML = `
                <div style="margin-top:14px;">
                  <h3 style="font-size:11.5px; margin:0 0 6px;">Related components</h3>
                  <div class="related-grid">
                    ${data.related_components.map(c => `
                      <a href="/code_viewer?repo=${activeRepo ? activeRepo.id : ''}&file=${encodeURIComponent(c.file_path || '')}" style="text-decoration:none;">
                        <button type="button">
                          <span class="type-icon ${c.type === 'class' ? 'middleware' : 'service'}">${c.type ? c.type[0].toUpperCase() : 'C'}</span>
                          <span>
                            <strong>${escapeHtml(c.name)}</strong>
                            <small>${escapeHtml(c.file_path || 'Repository component')}</small>
                          </span>
                          <span class="badge ${c.impact_level === 'DIRECT' ? 'badge-danger' : 'badge-warning'}">${c.impact_level || 'DIRECT'}</span>
                        </button>
                      </a>
                    `).join('')}
                  </div>
                </div>
              `;
            }
          }

          // Risk callout
          if (data && data.risk_callout && data.risk_callout.summary) {
            const riskContainer = aiMsgEl ? aiMsgEl.querySelector('.risk-container') : null;
            if (riskContainer) {
              riskContainer.innerHTML = `
                <div class="risk-callout">
                  <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 3v4M21 12h-4M12 21v-4M3 12h4"/></svg>
                  <div>
                    <strong>Potential impact</strong>
                    <p>${escapeHtml(data.risk_callout.summary)}</p>
                    <a href="/impact_analysis" style="text-decoration:none; display:inline-flex; align-items:center; gap:4px; font-weight:700; font-size:8.5px; color:#92400e;">
                      Analyze change impact →
                    </a>
                  </div>
                </div>
              `;
            }
          }

          // Msg actions
          const actionsEl = aiMsgEl ? aiMsgEl.querySelector('.msg-actions') : null;
          if (actionsEl) {
            actionsEl.style.display = 'flex';
            actionsEl.innerHTML = `
              <button type="button" class="msg-action-btn copy-answer-btn" title="Copy response to clipboard" aria-label="Copy response to clipboard">
                <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                <span class="btn-label">Copy</span>
              </button>
              <button type="button" class="msg-action-btn feedback-good-btn" title="Helpful response">
                <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
              </button>
              <button type="button" class="msg-action-btn feedback-bad-btn" title="Not helpful">
                <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>
              </button>
            `;
          }

          // Populate final evidence panel
          populateEvidencePanel(finalCitations, activeRepo);

          // Refresh history list
          await loadHistory(historySearchInput?.value?.trim() || '');

          if (currentConversationId) {
            const activeConv = conversationsCache.find(c => c.id === currentConversationId);
            if (activeConv && titleEl) {
              titleEl.textContent = activeConv.title;
            }
          }
        } else if (event === 'error') {
          if (thinkingEl) thinkingEl.style.display = 'none';
          if (liveTokenBody) liveTokenBody.style.display = 'block';
          if (aiMsgEl) aiMsgEl.classList.add('ai-failed');
          if (statusBadge) {
            statusBadge.className = 'badge badge-danger';
            statusBadge.innerHTML = `<span class="badge-text">Generation Error</span>`;
          }
          if (liveTokenBody) {
            liveTokenBody.innerHTML = `
              <p style="color:var(--status-danger);"><strong>Error querying assistant:</strong> ${escapeHtml(data.message || data.detail || 'Server error occurred during generation.')}</p>
              <div style="margin-top:10px;">
                <button type="button" class="btn btn-secondary btn-sm retry-btn-action">
                  <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                  <span>Retry</span>
                </button>
              </div>
            `;
            liveTokenBody.querySelector('.retry-btn-action')?.addEventListener('click', () => {
              aiMsgEl.remove();
              handleSend(q);
            });
          }
        }
      };

      if (currentConversationId) {
        await CodeMindAPI.streamConversationMessage(
          currentConversationId,
          q,
          {
            repositoryId: activeRepo.id,
            branch: activeRepo.default_branch || 'main',
            signal: currentStreamAbortController.signal
          },
          onEvent
        );
      } else {
        await CodeMindAPI.streamQueryAssistant(
          activeRepo.id,
          q,
          null,
          {
            signal: currentStreamAbortController.signal
          },
          onEvent
        );
      }

    } catch (err) {
      const isAborted = (err && (err.name === 'AbortError' || err.message?.includes('aborted'))) || (currentStreamAbortController && currentStreamAbortController.signal.aborted);
      if (thinkingEl) thinkingEl.style.display = 'none';
      if (liveTokenBody) liveTokenBody.style.display = 'block';

      if (isAborted) {
        // User cancelled or switched conversation - show clear "Response cancelled" state
        if (aiMsgEl && document.body.contains(aiMsgEl)) {
          const orb = aiMsgEl.querySelector('.ai-orb');
          if (orb) {
            orb.classList.remove('pulsing');
            orb.innerHTML = `<svg class="icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m12 3-1.7 4.3L6 9l4.3 1.7L12 15l1.7-4.3L18 9l-4.3-1.7L12 3Z"/></svg>`;
          }
          if (statusBadge) {
            statusBadge.className = 'badge badge-neutral stream-status-badge';
            statusBadge.innerHTML = `<span class="badge-text">Response cancelled</span>`;
          }
          const cancelledHtml = `
            <div class="generation-stopped-notice" style="margin-top:10px; display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--text-muted); padding:6px 10px; background:var(--surface-subtle); border-radius:6px; border:1px solid var(--border);">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true" focusable="false"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>Response cancelled</span>
              <button type="button" class="btn btn-secondary btn-sm retry-cancelled-btn" style="margin-left:6px; padding:2px 8px; font-size:11px;">Retry</button>
            </div>
          `;
          if (liveTokenBody) {
            if (accumulatedTokens && accumulatedTokens.trim()) {
              liveTokenBody.innerHTML = renderMarkdown(accumulatedTokens, streamCitations) + cancelledHtml;
            } else {
              liveTokenBody.innerHTML = cancelledHtml;
            }
            liveTokenBody.querySelector('.retry-cancelled-btn')?.addEventListener('click', () => {
              aiMsgEl.remove();
              handleSend(q);
            });
          }
        }
        return;
      }

      if (requestConvId !== null && currentConversationId !== requestConvId) {
        return;
      }

      if (aiMsgEl) aiMsgEl.classList.add('ai-failed');
      if (statusBadge) {
        statusBadge.className = 'badge badge-danger';
        statusBadge.innerHTML = `<span class="badge-text">Generation Error</span>`;
      }
      if (liveTokenBody) {
        liveTokenBody.innerHTML = `
          <p style="color:var(--status-danger);"><strong>Error querying assistant:</strong> ${escapeHtml(err.message || 'Server error occurred during streaming.')}</p>
          <div style="margin-top:10px;">
            <button type="button" class="btn btn-secondary btn-sm retry-stream-err-btn">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
              <span>Retry</span>
            </button>
          </div>
        `;
        liveTokenBody.querySelector('.retry-stream-err-btn')?.addEventListener('click', () => {
          aiMsgEl.remove();
          handleSend(q);
        });
      }
    } finally {
      resetComposerState();
    }
  }

  // Backward-compatible alias for any code or buttons calling submitQuestion
  function submitQuestion(text) {
    return handleSend(text);
  }
  window.submitQuestion = submitQuestion;

  // Handle delegated message actions & retry
  if (messagesContainer) {
    messagesContainer.addEventListener('click', async (e) => {
      // Retry button
      const retryBtn = e.target.closest('.retry-btn-action, .retry-msg-btn');
      if (retryBtn) {
        const allUserMsgs = messagesContainer.querySelectorAll('.user-message p');
        if (allUserMsgs.length > 0) {
          const lastQuestion = allUserMsgs[allUserMsgs.length - 1].textContent;
          handleSend(lastQuestion);
        }
        return;
      }

      // Copy code block button
      const copyCodeBtn = e.target.closest('.code-copy-btn');
      if (copyCodeBtn) {
        const rawEncoded = copyCodeBtn.getAttribute('data-raw-code');
        const codeText = rawEncoded ? decodeURIComponent(rawEncoded) : (copyCodeBtn.closest('.code-block-wrapper')?.querySelector('code')?.textContent || '');
        if (codeText) {
          try {
            await navigator.clipboard.writeText(codeText);
            const span = copyCodeBtn.querySelector('span');
            if (span) {
              const orig = span.textContent;
              span.textContent = 'Copied!';
              copyCodeBtn.style.color = '#10b981';
              setTimeout(() => {
                span.textContent = orig;
                copyCodeBtn.style.color = '';
              }, 2000);
            }
          } catch (err) {
            console.warn('Clipboard copy failed:', err);
          }
        }
        return;
      }

      // Copy entire answer button
      const copyAnsBtn = e.target.closest('.copy-answer-btn');
      if (copyAnsBtn) {
        const aiMsg = copyAnsBtn.closest('.ai-message');
        const lead = aiMsg?.querySelector('.answer-lead');
        if (lead) {
          try {
            const clone = lead.cloneNode(true);
            clone.querySelectorAll('.code-copy-btn, .code-block-header, .citation-pill, .btn, button, svg').forEach(el => el.remove());
            const cleanText = (clone.innerText || clone.textContent || '').trim();
            await navigator.clipboard.writeText(cleanText);
            const span = copyAnsBtn.querySelector('.btn-label') || copyAnsBtn.querySelector('span');
            if (span) {
              const orig = span.textContent;
              span.textContent = 'Copied!';
              setTimeout(() => { span.textContent = orig; }, 2000);
            }
          } catch (err) {
            console.warn('Clipboard copy failed:', err);
          }
        }
        return;
      }

      // Thumbs up / down feedback
      const goodBtn = e.target.closest('.feedback-good-btn');
      if (goodBtn) {
        goodBtn.classList.toggle('active');
        const badBtn = goodBtn.parentElement.querySelector('.feedback-bad-btn');
        if (badBtn) badBtn.classList.remove('active');
        return;
      }
      const badBtn = e.target.closest('.feedback-bad-btn');
      if (badBtn) {
        badBtn.classList.toggle('active');
        const goodBtn = badBtn.parentElement.querySelector('.feedback-good-btn');
        if (goodBtn) goodBtn.classList.remove('active');
        return;
      }

      // Citation pill click: highlight evidence card
      const citationPill = e.target.closest('.citation-pill');
      if (citationPill) {
        const sourceIndex = citationPill.getAttribute('data-source-index');
        const targetCard = document.querySelector(`.source-card[data-source-index="${sourceIndex}"]`);
        if (targetCard) {
          targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
          targetCard.classList.add('flash-highlight');
          setTimeout(() => { targetCard.classList.remove('flash-highlight'); }, 2000);
        }
        return;
      }
    });
  }

  // Wire send controls & textarea
  if (sendBtn) {
    sendBtn.disabled = !textarea?.value?.trim();
    sendBtn.addEventListener('click', () => handleSend());
  }

  if (textarea) {
    textarea.addEventListener('input', () => {
      autoResizeTextarea();
      if (sendBtn) sendBtn.disabled = isSending || !textarea.value.trim();
    });

    textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        if (e.shiftKey) {
          // Allow newline with Shift+Enter
          return;
        }
        // Desktop: Enter sends
        if (window.innerWidth > 768) {
          e.preventDefault();
          handleSend();
        }
      }
    });
  }

  // Wire suggestion prompt buttons
  const suggestionBtns = document.querySelectorAll('.suggestion-prompt-btn');
  suggestionBtns.forEach(btn => {
    btn.onclick = () => {
      const text = btn.querySelector('span')?.textContent || '';
      if (textarea && text) {
        textarea.value = text;
        autoResizeTextarea();
        if (sendBtn) sendBtn.disabled = false;
        textarea.focus();
      }
    };
  });

  // Wire new conversation buttons
  if (historyNewBtn) historyNewBtn.addEventListener('click', startNewConversation);
  if (btnNewConversation) btnNewConversation.addEventListener('click', startNewConversation);

  // Wire history sidebar toggle
  if (historyToggleBtn) {
    historyToggleBtn.addEventListener('click', () => {
      if (window.innerWidth <= 992) {
        if (assistantLayout) assistantLayout.classList.toggle('history-open');
      } else {
        if (assistantLayout) assistantLayout.classList.toggle('history-closed');
      }
    });
  }
  if (historyCloseBtn) {
    historyCloseBtn.addEventListener('click', () => {
      if (assistantLayout) assistantLayout.classList.remove('history-open');
    });
  }
  if (historyBackdrop) {
    historyBackdrop.addEventListener('click', () => {
      if (assistantLayout) assistantLayout.classList.remove('history-open');
    });
  }

  // Wire history search with debounce
  if (historySearchInput) {
    historySearchInput.addEventListener('input', (e) => {
      const val = e.target.value.trim();
      if (historySearchClear) historySearchClear.style.display = val ? 'inline-block' : 'none';
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        loadHistory(val);
      }, 250);
    });
  }

  if (historySearchClear) {
    historySearchClear.addEventListener('click', () => {
      if (historySearchInput) {
        historySearchInput.value = '';
        historySearchClear.style.display = 'none';
        loadHistory('');
      }
    });
  }

  // Load initial history
  await loadHistory();

  // Check URL params
  const urlParams = new URLSearchParams(window.location.search);
  const convParam = urlParams.get('conversation_id');
  const qParam = urlParams.get('q');

  if (convParam) {
    const parsedId = parseInt(convParam);
    if (!isNaN(parsedId)) {
      openConversation(parsedId);
    }
  } else if (qParam && textarea) {
    textarea.value = qParam;
    autoResizeTextarea();
    if (sendBtn) sendBtn.disabled = false;
    textarea.focus();
  } else {
    // Check if there is an active conversation stored in session
    const storedConvId = sessionStorage.getItem('codemind_active_conversation_id');
    if (storedConvId) {
      const parsedStored = parseInt(storedConvId);
      const cached = conversationsCache.find(c => c.id === parsedStored);
      if (cached && (!activeRepo || !cached.repository_id || cached.repository_id === activeRepo.id)) {
        openConversation(parsedStored);
      } else {
        sessionStorage.removeItem('codemind_active_conversation_id');
      }
    }
  }
}

let currentEvidenceCitations = [];
let currentEvidenceRepo = null;
let activeEvidenceTab = 'sources';
let evidenceTabsInitialized = false;

function initEvidenceTabs() {
  if (evidenceTabsInitialized) return;
  evidenceTabsInitialized = true;

  const sourcesTabBtn = document.getElementById('evidence-tab-sources');
  const detailsTabBtn = document.getElementById('evidence-tab-details');
  const toggleDrawerBtn = document.getElementById('btn-toggle-evidence');
  const evidencePanel = document.querySelector('.evidence-panel');

  if (sourcesTabBtn) {
    sourcesTabBtn.onclick = (e) => {
      e.preventDefault();
      activeEvidenceTab = 'sources';
      sourcesTabBtn.classList.add('active');
      sourcesTabBtn.setAttribute('aria-selected', 'true');
      if (detailsTabBtn) {
        detailsTabBtn.classList.remove('active');
        detailsTabBtn.setAttribute('aria-selected', 'false');
      }
      renderEvidencePanelContent();
    };
  }

  if (detailsTabBtn) {
    detailsTabBtn.onclick = (e) => {
      e.preventDefault();
      activeEvidenceTab = 'details';
      detailsTabBtn.classList.add('active');
      detailsTabBtn.setAttribute('aria-selected', 'true');
      if (sourcesTabBtn) {
        sourcesTabBtn.classList.remove('active');
        sourcesTabBtn.setAttribute('aria-selected', 'false');
      }
      renderEvidencePanelContent();
    };
  }

  if (toggleDrawerBtn && evidencePanel) {
    toggleDrawerBtn.onclick = (e) => {
      e.preventDefault();
      evidencePanel.classList.toggle('open');
    };
  }
}

function renderEvidencePanelContent() {
  const evidenceBody = document.querySelector('.evidence-body');
  const countBadge = document.getElementById('evidence-count-badge') || document.querySelector('.evidence-head .badge');
  if (!evidenceBody) return;

  const validCitations = Array.isArray(currentEvidenceCitations) ? currentEvidenceCitations : [];
  const repo = currentEvidenceRepo;
  const repoId = repo ? repo.id : '';

  // Calculate unique files
  const uniqueFileSet = new Set(validCitations.map(c => c.file_path).filter(Boolean));
  if (countBadge) {
    if (validCitations.length === 0) {
      countBadge.textContent = '0';
    } else {
      countBadge.textContent = `${validCitations.length} chunk${validCitations.length === 1 ? '' : 's'} · ${uniqueFileSet.size} file${uniqueFileSet.size === 1 ? '' : 's'}`;
    }
  }

  if (activeEvidenceTab === 'sources') {
    if (validCitations.length === 0) {
      evidenceBody.innerHTML = `
        <div style="padding: 36px 16px; text-align: center; color: var(--muted); font-size: 11.5px;">
          <svg class="icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="margin-bottom: 8px;" aria-hidden="true" focusable="false"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></svg>
          <p style="margin: 0; font-weight: 600;">No active query evidence</p>
          <small style="display: block; margin-top: 4px; color: var(--muted);">Citations and verified source lines will appear here after you ask a question.</small>
        </div>
      `;
      return;
    }

    // Group citations by file
    const fileGroups = {};
    validCitations.forEach(c => {
      const path = c.file_path || 'unknown_file';
      if (!fileGroups[path]) fileGroups[path] = [];
      fileGroups[path].push(c);
    });

    let sourcesHtml = '<span class="panel-label">PRIMARY SOURCES</span>';
    
    for (const [filePath, chunks] of Object.entries(fileGroups)) {
      const fileName = filePath.split('/').pop();
      sourcesHtml += `
        <div class="evidence-file-group">
          <div class="evidence-file-header" title="${escapeHtml(filePath)}">
            <span style="display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/></svg>
              <strong style="overflow: hidden; text-overflow: ellipsis;">${escapeHtml(fileName)}</strong>
            </span>
            <span class="badge badge-neutral" style="font-size: 10px;">${chunks.length} chunk${chunks.length === 1 ? '' : 's'}</span>
          </div>
          <div class="evidence-chunks-list">
            ${chunks.map((c) => {
              // Clean snippet of duplicate headers
              let cleanedSnippet = (c.snippet || '').trim();
              if (cleanedSnippet.startsWith('// File:')) {
                const lines = cleanedSnippet.split('\n');
                if (lines[0].includes('Lines:')) lines.shift();
                cleanedSnippet = lines.join('\n').trim();
              }
              const scoreText = c.similarity_percent || '80%';
              const targetUrl = `/code_viewer?repo=${repoId}&file=${encodeURIComponent(c.file_path)}&start=${c.start_line || 1}&end=${c.end_line || 1}`;

              return `
                <div class="evidence-chunk-card" data-source-index="${c.source_index}" id="evidence-source-${c.source_index}" onclick="selectEvidenceCard(this)">
                  <div class="evidence-chunk-top">
                    <span style="font-weight: 600; color: var(--text);">Lines ${c.start_line || 1}–${c.end_line || 1}</span>
                    <span class="badge badge-success" style="font-size: 10px;">${escapeHtml(scoreText)}</span>
                  </div>
                  <div class="evidence-snippet-box">${escapeHtml(cleanedSnippet)}</div>
                  <div style="margin-top: 6px; display: flex; justify-content: flex-end;">
                    <a href="${targetUrl}" class="evidence-chunk-action" onclick="event.stopPropagation();" title="Inspect source lines in Code Viewer">
                      <span>View in Code Viewer</span>
                      <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="m9 18 6-6-6-6"/></svg>
                    </a>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    evidenceBody.innerHTML = sourcesHtml;

  } else {
    // Details Tab Content
    const rev = (repo && repo.current_revision) ? repo.current_revision.substring(0, 7) : 'HEAD';
    const repoName = repo ? repo.name : 'Active repository';
    const branchName = (repo && repo.default_branch) ? repo.default_branch : 'main';

    let avgScore = 0;
    if (validCitations.length > 0) {
      const sum = validCitations.reduce((acc, c) => {
        const val = parseInt(c.similarity_percent) || 80;
        return acc + val;
      }, 0);
      avgScore = Math.round(sum / validCitations.length);
    }

    evidenceBody.innerHTML = `
      <div id="evidence-details-container">
        <span class="panel-label">RETRIEVAL METRICS & VERIFICATION</span>
        <div class="settings-card" style="padding: 12px; margin-bottom: 10px;">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11px;">
            <div>Evidence Chunks: <strong>${validCitations.length}</strong></div>
            <div>Unique Files: <strong>${uniqueFileSet.size}</strong></div>
            <div>Avg Relevance: <strong>${validCitations.length > 0 ? avgScore + '%' : 'N/A'}</strong></div>
            <div>Verification: <strong style="color: var(--success);">${validCitations.length > 0 ? 'AST Grounded' : 'Awaiting Query'}</strong></div>
          </div>
        </div>

        <span class="panel-label secondary-label">CONTEXT & PROVENANCE</span>
        <div class="retrieval" style="margin-bottom: 12px;">
          <div><span>Repository</span><strong>${escapeHtml(repoName)}</strong></div>
          <div><span>Branch</span><strong>${escapeHtml(branchName)}</strong></div>
          <div><span>Indexed revision</span><code>${escapeHtml(rev)}</code></div>
          <div><span>Search strategy</span><strong>Hybrid (Vector + AST + Graph)</strong></div>
          <div><span>Graph depth</span><strong>3 hops</strong></div>
          <div><span>Vector dimension</span><strong>768 (pgvector)</strong></div>
        </div>

        ${validCitations.length === 0 ? `
          <div style="padding: 14px 8px; text-align: center; color: var(--muted); font-size: 11px;">
            Submit a question in the assistant to retrieve and verify AST source code evidence.
          </div>
        ` : ''}
      </div>
    `;
  }
}

function selectEvidenceCard(el) {
  document.querySelectorAll('.evidence-chunk-card.selected').forEach(c => c.classList.remove('selected'));
  if (el) el.classList.add('selected');
}

function populateEvidencePanel(citations, repo) {
  currentEvidenceCitations = Array.isArray(citations) ? citations : [];
  currentEvidenceRepo = repo;
  initEvidenceTabs();
  renderEvidencePanelContent();
}

// --- Change Impact Hydration ---
async function hydrateImpactAnalysisView() {
  const activeRepo = await getActiveRepository();
  if (!activeRepo) return;

  const componentNameEl = document.getElementById('impact-component-name');
  const componentPathEl = document.getElementById('impact-component-path');
  const targetCompInput = document.getElementById('impact-target-component');
  const clearBtn = document.getElementById('impact-component-clear');
  const toggleBtn = document.getElementById('impact-component-toggle');
  const dropdown = document.getElementById('impact-components-dropdown');
  const newAnalysisBtn = document.getElementById('btn-new-impact-analysis');
  const textarea = document.getElementById('proposed-change');
  const analyzeBtn = document.getElementById('btn-run-impact-analysis');
  const graphStatusEl = document.getElementById('impact-graph-status');

  if (componentNameEl) componentNameEl.textContent = activeRepo.name;
  if (componentPathEl) componentPathEl.textContent = `${activeRepo.full_name} (${activeRepo.default_branch || 'main'})`;

  let repoNodes = [];
  try {
    const graphData = await CodeMindAPI.getRepositoryGraph(activeRepo.id, 200);
    if (graphData && graphData.nodes) {
      repoNodes = graphData.nodes;
      if (graphStatusEl) {
        graphStatusEl.textContent = `${repoNodes.length} Graph Symbols Ready`;
      }
    }
  } catch (e) {
    console.warn('Failed to load repo graph for impact analysis:', e);
  }

  // Pre-select if URL query has ?component=
  const urlParams = new URLSearchParams(window.location.search);
  const compParam = urlParams.get('component');
  if (compParam && targetCompInput) {
    targetCompInput.value = compParam;
    if (clearBtn) clearBtn.style.display = 'block';
    if (newAnalysisBtn) newAnalysisBtn.style.display = 'inline-flex';
    const match = repoNodes.find(n => n.name === compParam);
    if (match && componentPathEl) {
      componentPathEl.textContent = `${match.file_path || 'AST Node'} · ${match.node_type}`;
    }
  }

  function renderDropdownOptions(filterText = '') {
    if (!dropdown) return;
    const filterLower = filterText.toLowerCase().trim();
    const filtered = filterLower ?
      repoNodes.filter(n => (n.name && n.name.toLowerCase().includes(filterLower)) || (n.file_path && n.file_path.toLowerCase().includes(filterLower))) :
      repoNodes;

    if (filtered.length === 0) {
      dropdown.innerHTML = `
        <div style="padding: 12px; text-align: center; color: var(--muted); font-size: 11px;">
          No matching components found in AST graph.
        </div>
      `;
    } else {
      dropdown.innerHTML = filtered.map(n => {
        const isSelected = targetCompInput && targetCompInput.value.trim() === n.name;
        return `
          <div class="combobox-option ${isSelected ? 'selected' : ''}" data-name="${escapeHtml(n.name)}" data-path="${escapeHtml(n.file_path || '')}" data-type="${escapeHtml(n.node_type || '')}" role="option">
            <div class="combobox-option-info">
              <strong>${escapeHtml(n.name)}</strong>
              <small>${escapeHtml(n.file_path || 'AST Node')}</small>
            </div>
            <span class="badge" style="font-size: 10px;">${escapeHtml(n.node_type)}</span>
          </div>
        `;
      }).join('');

      dropdown.querySelectorAll('.combobox-option').forEach(opt => {
        opt.onclick = (e) => {
          e.stopPropagation();
          const selectedName = opt.getAttribute('data-name');
          const selectedPath = opt.getAttribute('data-path');
          const selectedType = opt.getAttribute('data-type');

          if (targetCompInput) targetCompInput.value = selectedName;
          if (componentPathEl) componentPathEl.textContent = `${selectedPath || 'AST Node'} · ${selectedType}`;
          if (clearBtn) clearBtn.style.display = 'block';
          if (newAnalysisBtn) newAnalysisBtn.style.display = 'inline-flex';
          closeDropdown();
        };
      });
    }
  }

  function openDropdown(filter = '') {
    if (!dropdown) return;
    renderDropdownOptions(filter);
    dropdown.style.display = 'block';
  }

  function closeDropdown() {
    if (dropdown) dropdown.style.display = 'none';
  }

  if (targetCompInput) {
    targetCompInput.addEventListener('focus', () => {
      openDropdown('');
    });

    targetCompInput.addEventListener('input', () => {
      const val = targetCompInput.value.trim();
      if (clearBtn) clearBtn.style.display = val ? 'block' : 'none';
      if (newAnalysisBtn) newAnalysisBtn.style.display = val ? 'inline-flex' : 'none';

      const match = repoNodes.find(n => n.name === val);
      if (match && componentPathEl) {
        componentPathEl.textContent = `${match.file_path || 'AST Node'} · ${match.node_type}`;
      } else if (componentPathEl) {
        componentPathEl.textContent = val ? 'Custom target / unverified in graph' : '—';
      }
      openDropdown(val);
    });

    targetCompInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeDropdown();
      }
    });
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (dropdown && dropdown.style.display === 'block') {
        closeDropdown();
      } else {
        openDropdown('');
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (targetCompInput) targetCompInput.value = '';
      if (componentPathEl) componentPathEl.textContent = '—';
      clearBtn.style.display = 'none';
      if (newAnalysisBtn) newAnalysisBtn.style.display = 'none';
      openDropdown('');
    });
  }

  if (newAnalysisBtn) {
    newAnalysisBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (targetCompInput) {
        targetCompInput.value = '';
        targetCompInput.focus();
      }
      if (componentPathEl) componentPathEl.textContent = '—';
      if (clearBtn) clearBtn.style.display = 'none';
      newAnalysisBtn.style.display = 'none';
      openDropdown('');
    });
  }

  // Close dropdown on click outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.impact-selector-wrap')) {
      closeDropdown();
    }
  });

  if (analyzeBtn && textarea) {
    analyzeBtn.addEventListener('click', async () => {
      const targetComponent = targetCompInput ? targetCompInput.value.trim() : null;
      const changeText = textarea.value.trim();

      if (!targetComponent && !changeText) {
        alert('Please specify a target component/symbol or describe the proposed code change.');
        return;
      }

      analyzeBtn.disabled = true;
      const origHtml = analyzeBtn.innerHTML;
      analyzeBtn.innerHTML = `<span>Analyzing AST graph...</span>`;

      try {
        const res = await CodeMindAPI.analyzeChangeImpact(activeRepo.id, {
          component_name: targetComponent || null,
          proposed_change: changeText || null,
          max_depth: 3
        });

        if (newAnalysisBtn) newAnalysisBtn.style.display = 'inline-flex';
        if (clearBtn) clearBtn.style.display = 'block';

        // 1. Risk Score
        const scoreRingStrong = document.getElementById('impact-score-value');
        const riskBadge = document.getElementById('impact-risk-badge');
        const riskTitle = document.getElementById('impact-risk-title');
        const riskDesc = document.getElementById('impact-risk-desc');

        const score = res.risk_level === 'HIGH' ? Math.max(70, Math.min(95, 60 + res.total_affected * 3)) :
                      res.risk_level === 'MEDIUM' ? Math.max(35, Math.min(65, 30 + res.total_affected * 4)) :
                      res.total_affected > 0 ? Math.min(30, res.total_affected * 8) : 0;

        if (scoreRingStrong) scoreRingStrong.textContent = score;
        if (riskBadge) {
          riskBadge.className = `badge badge-${res.risk_level === 'HIGH' ? 'danger' : res.risk_level === 'MEDIUM' ? 'warning' : 'success'}`;
          riskBadge.textContent = `${res.risk_level} POTENTIAL IMPACT`;
        }
        if (riskTitle) {
          riskTitle.textContent = res.total_affected > 0 ? `${res.total_affected} component(s) potentially affected` : 'Minimal blast radius detected';
        }
        if (riskDesc) {
          riskDesc.textContent = res.explanation;
        }

        // 2. Metrics summary
        const directCountEl = document.getElementById('impact-direct-count');
        const transitiveCountEl = document.getElementById('impact-transitive-count');
        const filesCountEl = document.getElementById('impact-files-count');
        const riskLevelEl = document.getElementById('impact-risk-level');

        if (directCountEl) directCountEl.textContent = res.direct_count;
        if (transitiveCountEl) transitiveCountEl.textContent = res.transitive_count;
        if (filesCountEl) filesCountEl.textContent = res.affected_files ? res.affected_files.length : 0;
        if (riskLevelEl) riskLevelEl.textContent = res.risk_level;

        // 3. Affected Components List
        const affectedContainer = document.getElementById('impact-affected-container');
        if (affectedContainer) {
          if (!res.affected_components || res.affected_components.length === 0) {
            affectedContainer.innerHTML = `
              <div class="empty-state" style="padding: 2rem 1rem; text-align: center; color: var(--text-muted);">
                <p>No callers or dependent symbols found in the indexed AST graph for this target.</p>
              </div>
            `;
          } else {
            affectedContainer.innerHTML = res.affected_components.map(comp => `
              <div class="affected-row">
                <span class="rank ${comp.impact_level === 'DIRECT' ? 'rank-high' : 'rank-medium'}">
                  ${comp.impact_level === 'DIRECT' ? '!' : '–'}
                </span>
                <div class="affected-info">
                  <div>
                    <strong>${escapeHtml(comp.name)}</strong>
                    <span class="badge">${escapeHtml(comp.component_type)}</span>
                    <span class="badge badge-${comp.impact_level === 'DIRECT' ? 'danger' : 'warning'}">${escapeHtml(comp.impact_level)}</span>
                  </div>
                  <p>${escapeHtml(comp.evidence || (comp.file_path ? 'Declared in ' + comp.file_path : 'Repository AST node.'))}</p>
                  <small>
                    <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="6" cy="6" r="3" /><circle cx="18" cy="6" r="3" /><circle cx="12" cy="18" r="3" /><path d="m8.6 7.5 2.2 7M15.4 7.5l-2.2 7M9 6h6" /></svg>
                    ${comp.distance} hop${comp.distance > 1 ? 's' : ''} · ${escapeHtml(comp.component_type)}
                  </small>
                </div>
                <div class="confidence">
                  <strong>${Math.round(comp.confidence_score * 100)}%</strong>
                  <span>confidence</span>
                </div>
              </div>
            `).join('');
          }
        }

        // 4. Dependency Path Flow
        const pathFlowEl = document.getElementById('impact-path-flow');
        if (pathFlowEl) {
          if (res.dependency_paths && res.dependency_paths.length > 0) {
            pathFlowEl.innerHTML = `
              <div style="display: flex; flex-direction: column; gap: 8px; width: 100%; padding: 10px;">
                ${res.dependency_paths.slice(0, 6).map(p => `
                  <div style="font-size: 0.85rem; padding: 6px 10px; background: var(--bg-card); border-radius: 6px; border: 1px solid var(--border);">
                    <strong style="color: var(--accent);">${escapeHtml(p.source)}</strong>
                    <span style="color: var(--text-muted); font-size: 0.75rem;"> --[${escapeHtml(p.relationship)}]--> </span>
                    <span>${escapeHtml(p.target)}</span>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">${escapeHtml(p.source_file || '')}</div>
                  </div>
                `).join('')}
              </div>
            `;
          } else {
            pathFlowEl.innerHTML = `<div style="font-size: 0.85rem; color: var(--text-muted); text-align: center; padding: 1.5rem 0.5rem; width: 100%;">No multi-hop paths found.</div>`;
          }
        }

        // 5. Checklist
        const checklistEl = document.getElementById('impact-checklist-container');
        if (checklistEl) {
          if (res.affected_components && res.affected_components.length > 0) {
            checklistEl.innerHTML = res.affected_components.slice(0, 6).map(c => `
              <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 0.85rem; cursor: pointer;">
                <input type="checkbox" />
                <span>Verify callers in <code>${escapeHtml(c.name)}</code> (${escapeHtml(c.file_path ? c.file_path.split('/').pop() : c.component_type)})</span>
              </label>
            `).join('');
          } else {
            checklistEl.innerHTML = `<div style="font-size: 0.85rem; color: var(--text-muted); padding: 0.75rem 0;">No test items generated.</div>`;
          }
        }
      } catch (err) {
        alert(`Change impact analysis failed: ${err.message}`);
      } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.innerHTML = origHtml;
      }
    });
  }
}

// --- Dependency Explorer Hydration ---
async function hydrateDependenciesView() {
  const activeRepo = await getActiveRepository();
  if (!activeRepo) return;

  const repoNameEl = document.getElementById('dependencies-repo-name');
  if (repoNameEl) repoNameEl.textContent = activeRepo.name;

  const headerImpactBtn = document.querySelector('.page-header .header-actions a[href*="impact"]');
  if (headerImpactBtn) {
    headerImpactBtn.setAttribute('href', `/impact_analysis?repo=${activeRepo.id}`);
  }

  const entityCountEl = document.getElementById('graph-entity-count');
  const emptyState = document.getElementById('graph-empty-state');
  const canvasContainer = document.getElementById('graph-canvas-container');
  const tracePathBtn = document.getElementById('btn-trace-path');

  const depthBtn = document.getElementById('btn-filter-depth');
  const depthBadge = document.getElementById('filter-depth-badge');
  const typeBtn = document.getElementById('btn-filter-types');
  const typeBadge = document.getElementById('filter-type-badge');
  const relBtn = document.getElementById('btn-filter-rel');
  const relBadge = document.getElementById('filter-rel-badge');
  const searchInput = document.getElementById('graph-search-input');

  let currentDepth = 1;
  const depthOptions = [1, 2, 3];
  let depthIdx = 0;

  const typeOptions = ['All', 'class', 'function', 'service', 'component'];
  let typeIdx = 0;

  const relOptions = ['All', 'CALLS', 'IMPORTS', 'DEFINES', 'DEPENDS_ON'];
  let relIdx = 0;

  let allNodes = [];
  let allEdges = [];
  let selectedNode = null;

  async function loadAndRenderGraph() {
    try {
      const selectedType = typeOptions[typeIdx] === 'All' ? null : typeOptions[typeIdx];
      const selectedRel = relOptions[relIdx] === 'All' ? null : relOptions[relIdx];

      const graphData = await CodeMindAPI.getRepositoryGraph(activeRepo.id, 100, selectedType, selectedRel);
      if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
        if (emptyState) emptyState.style.display = 'block';
        if (entityCountEl) entityCountEl.textContent = '0 entities mapped';
        let oldSvg = canvasContainer.querySelector('svg.dynamic-dep-svg');
        if (oldSvg) oldSvg.remove();
        return;
      }

      if (emptyState) emptyState.style.display = 'none';
      allNodes = graphData.nodes;
      allEdges = graphData.edges || [];

      renderGraphWorkspace(allNodes, allEdges);
    } catch (err) {
      console.warn('Error loading graph:', err);
    }
  }

  let zoomScale = 1.0;
  let panX = 0;
  let panY = 0;
  let isPanning = false;
  let panStartX = 0;
  let panStartY = 0;

  const btnZoomIn = document.getElementById('btn-zoom-in');
  const btnZoomOut = document.getElementById('btn-zoom-out');
  const btnZoomFit = document.getElementById('btn-zoom-fit');

  function updateTransform() {
    const svg = canvasContainer.querySelector('svg.dynamic-dep-svg');
    const viewport = svg ? svg.querySelector('#graph-viewport') : null;
    if (viewport) {
      viewport.setAttribute('transform', `translate(${panX}, ${panY}) scale(${zoomScale})`);
    }
  }

  if (btnZoomIn) {
    btnZoomIn.onclick = () => {
      zoomScale = Math.min(3.0, zoomScale * 1.25);
      updateTransform();
    };
  }
  if (btnZoomOut) {
    btnZoomOut.onclick = () => {
      zoomScale = Math.max(0.35, zoomScale * 0.8);
      updateTransform();
    };
  }
  if (btnZoomFit) {
    btnZoomFit.onclick = () => {
      zoomScale = 1.0;
      panX = 0;
      panY = 0;
      updateTransform();
    };
  }

  function renderGraphWorkspace(nodesList, edgesList) {
    const query = (searchInput ? searchInput.value.trim().toLowerCase() : '');
    const filteredNodes = query ? nodesList.filter(n => n.name.toLowerCase().includes(query) || (n.file_path && n.file_path.toLowerCase().includes(query))) : nodesList;

    if (entityCountEl) {
      entityCountEl.textContent = `Showing ${filteredNodes.length} of ${nodesList.length} entities (Depth: ${currentDepth}-Hop)`;
    }

    let oldSvg = canvasContainer.querySelector('svg.dynamic-dep-svg');
    if (oldSvg) oldSvg.remove();

    if (filteredNodes.length === 0) {
      return;
    }

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'dynamic-dep-svg');
    svg.setAttribute('width', '100%');
    svg.setAttribute('height', '100%');
    svg.setAttribute('viewBox', '0 0 1100 700');
    svg.style.position = 'absolute';
    svg.style.top = '0';
    svg.style.left = '0';
    svg.style.width = '100%';
    svg.style.height = '100%';
    svg.style.cursor = 'grab';

    // Add SVG defs for directional arrows
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <marker id="dep-arrow" viewBox="0 0 10 10" refX="21" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="rgba(99, 102, 241, 0.45)"/>
      </marker>
      <marker id="dep-arrow-selected" viewBox="0 0 10 10" refX="21" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#4f46e5"/>
      </marker>
    `;
    svg.appendChild(defs);

    const viewportG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    viewportG.setAttribute('id', 'graph-viewport');
    viewportG.setAttribute('transform', `translate(${panX}, ${panY}) scale(${zoomScale})`);

    // Mouse drag pan listeners
    svg.addEventListener('mousedown', (e) => {
      if (e.target.closest('.nodes g')) return; // ignore clicks on nodes
      isPanning = true;
      panStartX = e.clientX - panX;
      panStartY = e.clientY - panY;
      svg.style.cursor = 'grabbing';
    });
    window.addEventListener('mousemove', (e) => {
      if (!isPanning) return;
      panX = e.clientX - panStartX;
      panY = e.clientY - panStartY;
      updateTransform();
    });
    window.addEventListener('mouseup', () => {
      if (isPanning) {
        isPanning = false;
        svg.style.cursor = 'grab';
      }
    });

    // Wheel zoom listener
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.12 : 0.89;
      zoomScale = Math.max(0.35, Math.min(3.0, zoomScale * factor));
      updateTransform();
    }, { passive: false });

    const displayNodes = filteredNodes.slice(0, 36);
    const nodeMap = new Map();
    const centerX = 550;
    const centerY = 350;
    const radiusX = 400;
    const radiusY = 250;

    // Initial placement on an elliptical spiral
    displayNodes.forEach((n, idx) => {
      const angle = (idx / displayNodes.length) * 2 * Math.PI;
      const wobble = (idx % 2 === 0 ? 1.0 : 0.75);
      const x = centerX + radiusX * wobble * Math.cos(angle);
      const y = centerY + radiusY * wobble * Math.sin(angle);
      nodeMap.set(n.id, { ...n, x, y });
    });

    // Force simulation for node spacing & label collision prevention
    for (let iter = 0; iter < 60; iter++) {
      // Repulsion between all node pairs
      for (let i = 0; i < displayNodes.length; i++) {
        const n1 = nodeMap.get(displayNodes[i].id);
        for (let j = i + 1; j < displayNodes.length; j++) {
          const n2 = nodeMap.get(displayNodes[j].id);
          const dx = n1.x - n2.x;
          const dy = n1.y - n2.y;
          // Apply horizontal clearance factor (1.8x) so wide text labels don't collide
          const distSq = (dx * dx) / 1.8 + (dy * dy);
          const dist = Math.sqrt(distSq) || 1;
          const targetMinDist = 115;
          if (dist < targetMinDist) {
            const force = ((targetMinDist - dist) / dist) * 0.35;
            const fx = dx * force * 1.35;
            const fy = dy * force;
            n1.x += fx;
            n1.y += fy;
            n2.x -= fx;
            n2.y -= fy;
          }
        }
      }

      // Spring attraction along edges
      edgesList.forEach(e => {
        const src = nodeMap.get(e.source_node_id);
        const tgt = nodeMap.get(e.target_node_id);
        if (src && tgt) {
          const dx = tgt.x - src.x;
          const dy = tgt.y - src.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const idealDist = 135;
          const force = (dist - idealDist) * 0.04;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          src.x += fx;
          src.y += fy;
          tgt.x -= fx;
          tgt.y -= fy;
        }
      });

      // Gentle centering gravity & boundary clamp
      displayNodes.forEach(n => {
        const node = nodeMap.get(n.id);
        node.x += (centerX - node.x) * 0.02;
        node.y += (centerY - node.y) * 0.02;
        node.x = Math.max(90, Math.min(1010, node.x));
        node.y = Math.max(60, Math.min(640, node.y));
      });
    }

    // Render edges with directional arrows
    const edgesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    edgesGroup.setAttribute('class', 'edges');
    edgesList.forEach(e => {
      const src = nodeMap.get(e.source_node_id);
      const tgt = nodeMap.get(e.target_node_id);
      if (src && tgt) {
        const isConnectedToSelected = selectedNode && (selectedNode.id === src.id || selectedNode.id === tgt.id);
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', src.x);
        line.setAttribute('y1', src.y);
        line.setAttribute('x2', tgt.x);
        line.setAttribute('y2', tgt.y);
        line.setAttribute('stroke', isConnectedToSelected ? '#4f46e5' : 'rgba(99, 102, 241, 0.28)');
        line.setAttribute('stroke-width', isConnectedToSelected ? '2.5' : '1.4');
        line.setAttribute('marker-end', isConnectedToSelected ? 'url(#dep-arrow-selected)' : 'url(#dep-arrow)');
        edgesGroup.appendChild(line);
      }
    });
    viewportG.appendChild(edgesGroup);

    // Select and display node details
    const selectNode = async (node) => {
      selectedNode = node;
      const badge = document.getElementById('node-panel-badge');
      const title = document.getElementById('node-panel-title');
      const file = document.getElementById('node-panel-file');
      const desc = document.getElementById('node-panel-desc');
      const inEl = document.getElementById('node-stat-incoming');
      const outEl = document.getElementById('node-stat-outgoing');
      const degEl = document.getElementById('node-stat-degree');
      const relsContainer = document.getElementById('node-relations-container');
      const viewInViewerBtn = document.getElementById('btn-view-in-code-viewer');
      const analyzeImpactBtn = document.getElementById('btn-analyze-impact');
      const askAiBtn = document.getElementById('btn-ask-ai');

      if (badge) badge.textContent = (node.node_type || 'SYMBOL').toUpperCase();
      if (title) {
        title.textContent = node.name;
        title.title = node.name;
      }
      if (file) {
        file.textContent = node.file_path || '—';
        file.title = node.file_path || 'Repository file path';
        file.style.wordBreak = 'break-all';
      }
      if (desc) desc.textContent = node.docstring || (node.file_path ? `Defined in ${node.file_path}` : 'Repository AST node.');

      // Update action links with active repository context
      if (viewInViewerBtn) {
        viewInViewerBtn.href = `/code_viewer?repo=${activeRepo.id}&file=${encodeURIComponent(node.file_path || '')}&start=${node.start_line || 1}`;
      }
      if (analyzeImpactBtn) {
        analyzeImpactBtn.href = `/impact_analysis?repo=${activeRepo.id}&component=${encodeURIComponent(node.name)}`;
      }
      if (askAiBtn) {
        askAiBtn.href = `/assistant?repo=${activeRepo.id}&question=${encodeURIComponent('Explain the architecture, responsibilities, and key dependencies of ' + node.name)}`;
      }

      // Fetch neighbors with current depth
      try {
        const neighborData = await CodeMindAPI.getNodeNeighbors(activeRepo.id, node.id, currentDepth);
        const direct = (neighborData && neighborData.direct_neighbors) ? neighborData.direct_neighbors : [];
        const transitive = (neighborData && neighborData.transitive_neighbors) ? neighborData.transitive_neighbors : [];

        const incomingCount = direct.filter(n => n.direction === 'incoming').length;
        const outgoingCount = direct.filter(n => n.direction === 'outgoing').length;

        if (inEl) inEl.textContent = incomingCount;
        if (outEl) outEl.textContent = outgoingCount;
        if (degEl) degEl.textContent = incomingCount + outgoingCount;

        if (relsContainer) {
          if (direct.length === 0 && transitive.length === 0) {
            relsContainer.innerHTML = '<p style="font-size: 11px; color: var(--muted); padding: 8px 0;">No graph edges recorded within selected depth.</p>';
          } else {
            let html = '';
            if (direct.length > 0) {
              html += `<div style="font-size:10px; font-weight:700; color:var(--muted); text-transform:uppercase; margin-bottom:4px;">Direct (${direct.length})</div>`;
              html += direct.slice(0, 10).map(r => `
                <div class="relation-row" data-neighbor-id="${r.node ? r.node.id : ''}" style="cursor: pointer; padding: 5px 4px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;">
                  <span style="font-family:monospace; font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:180px;" title="${escapeHtml(r.node ? r.node.name : 'symbol')}">
                    ${r.direction === 'incoming' ? '← ' : '→ '}${escapeHtml(r.node ? r.node.name : 'symbol')}
                  </span>
                  <span class="badge" style="font-size:9px; flex-shrink:0;">${escapeHtml(r.edge_type || '')}</span>
                </div>
              `).join('');
            }
            if (transitive.length > 0) {
              html += `<div style="font-size:10px; font-weight:700; color:var(--muted); text-transform:uppercase; margin-top:8px; margin-bottom:4px;">Transitive (${transitive.length})</div>`;
              html += transitive.slice(0, 8).map(r => `
                <div class="relation-row" data-neighbor-id="${r.node ? r.node.id : ''}" style="cursor: pointer; padding: 5px 4px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;">
                  <span style="font-family:monospace; font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:180px;" title="${escapeHtml(r.node ? r.node.name : 'symbol')}">
                    ${escapeHtml(r.node ? r.node.name : 'symbol')}
                  </span>
                  <span class="badge badge-neutral" style="font-size:9px; flex-shrink:0;">Hop ${r.depth}</span>
                </div>
              `).join('');
            }
            relsContainer.innerHTML = html;

            // Wire clicking on neighbor row to select that node
            relsContainer.querySelectorAll('.relation-row').forEach(row => {
              row.addEventListener('click', () => {
                const nId = parseInt(row.getAttribute('data-neighbor-id'));
                const targetNode = allNodes.find(x => x.id === nId);
                if (targetNode) {
                  selectNode(targetNode);
                  renderGraphWorkspace(nodesList, edgesList);
                }
              });
            });
          }
        }
      } catch (err) {
        console.warn('Error fetching node neighbors:', err);
      }
    };

    // Render nodes
    const nodesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    nodesGroup.setAttribute('class', 'nodes');

    nodeMap.forEach(n => {
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.style.cursor = 'pointer';

      // Tooltip for full name and path
      const titleEl = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      titleEl.textContent = `${n.name} (${n.file_path || 'AST Symbol'})\nType: ${n.node_type || 'symbol'}`;
      g.appendChild(titleEl);

      const isSelected = selectedNode && selectedNode.id === n.id;
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', n.x);
      circle.setAttribute('cy', n.y);
      circle.setAttribute('r', isSelected ? '18' : '14');
      const fillColor = n.node_type === 'class' ? '#8b5cf6' :
                        n.node_type === 'function' ? '#3b82f6' :
                        n.node_type === 'service' ? '#ea580c' :
                        n.node_type === 'component' ? '#10b981' : '#6366f1';
      circle.setAttribute('fill', fillColor);
      circle.setAttribute('stroke', isSelected ? '#1e293b' : '#ffffff');
      circle.setAttribute('stroke-width', isSelected ? '3.5' : '2');
      if (isSelected) {
        circle.setAttribute('filter', 'drop-shadow(0 0 6px rgba(79, 70, 229, 0.45))');
      }

      // Text background halo for crystal clear readability
      const halo = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      halo.setAttribute('x', n.x);
      halo.setAttribute('y', n.y + 24);
      halo.setAttribute('text-anchor', 'middle');
      halo.setAttribute('stroke', '#ffffff');
      halo.setAttribute('stroke-width', '4');
      halo.setAttribute('stroke-linejoin', 'round');
      halo.setAttribute('font-size', '11px');
      halo.setAttribute('font-weight', isSelected ? '700' : '500');
      halo.textContent = n.name.length > 18 ? n.name.substring(0, 16) + '…' : n.name;
      g.appendChild(halo);

      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      text.setAttribute('x', n.x);
      text.setAttribute('y', n.y + 24);
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('fill', isSelected ? '#4338ca' : 'var(--text-primary, #1e293b)');
      text.setAttribute('font-size', '11px');
      text.setAttribute('font-weight', isSelected ? '700' : '500');
      text.textContent = n.name.length > 18 ? n.name.substring(0, 16) + '…' : n.name;

      g.appendChild(circle);
      g.appendChild(text);

      g.addEventListener('click', (e) => {
        e.stopPropagation();
        selectNode(n);
        renderGraphWorkspace(nodesList, edgesList);
      });

      nodesGroup.appendChild(g);
    });

    viewportG.appendChild(nodesGroup);
    svg.appendChild(viewportG);
    canvasContainer.appendChild(svg);

    if (!selectedNode && displayNodes.length > 0) {
      selectNode(displayNodes[0]);
    }
  }

  // Bind Depth button
  if (depthBtn) {
    depthBtn.onclick = () => {
      depthIdx = (depthIdx + 1) % depthOptions.length;
      currentDepth = depthOptions[depthIdx];
      if (depthBadge) depthBadge.textContent = `${currentDepth}-Hop`;
      if (selectedNode) {
        renderGraphWorkspace(allNodes, allEdges);
      }
    };
  }

  // Bind Type button
  if (typeBtn) {
    typeBtn.onclick = () => {
      typeIdx = (typeIdx + 1) % typeOptions.length;
      if (typeBadge) typeBadge.textContent = typeOptions[typeIdx];
      loadAndRenderGraph();
    };
  }

  // Bind Relationship button
  if (relBtn) {
    relBtn.onclick = () => {
      relIdx = (relIdx + 1) % relOptions.length;
      if (relBadge) relBadge.textContent = relOptions[relIdx];
      loadAndRenderGraph();
    };
  }

  // Bind Search input
  if (searchInput) {
    searchInput.oninput = () => {
      renderGraphWorkspace(allNodes, allEdges);
    };
  }

  // Initial load
  await loadAndRenderGraph();

  if (tracePathBtn) {
    tracePathBtn.addEventListener('click', async () => {
      if (allNodes.length < 2) return;
      tracePathBtn.disabled = true;
      tracePathBtn.textContent = 'Tracing path...';
      try {
        const start = allNodes[0].id;
        const end = allNodes[Math.min(allNodes.length - 1, 3)].id;
        const pathRes = await CodeMindAPI.findGraphPath(activeRepo.id, start, end, 4);
        if (pathRes.path && pathRes.path.length > 0) {
          alert(`Dependency Path Found (${pathRes.path.length} hops):\n` + pathRes.path.map(p => `• --(${p.edge_type})--> ${p.target_name} (${p.target_type})`).join('\n'));
        } else {
          alert('No direct path found within depth limit between selected components.');
        }
      } catch (err) {
        alert(`Path search error: ${err.message}`);
      } finally {
        tracePathBtn.disabled = false;
        tracePathBtn.innerHTML = `<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/></svg><span>Trace path</span>`;
      }
    });
  }
}

// --- Code Viewer & Source Evidence Hydration ---
async function hydrateCodeViewerView() {
  let activeRepo = await getActiveRepository();

  const urlParams = new URLSearchParams(window.location.search);
  const repoParam = urlParams.get('repo');
  if (repoParam) {
    const targetRepoId = parseInt(repoParam);
    if (targetRepoId && (!activeRepo || activeRepo.id !== targetRepoId)) {
      try {
        const repos = await CodeMindAPI.getRepositories();
        const matched = (repos || []).find(r => r.id === targetRepoId);
        if (matched) {
          activeRepo = matched;
          localStorage.setItem('codemind_active_repo_id', String(matched.id));
        }
      } catch (e) {
        console.warn('Failed to switch repository from query param:', e);
      }
    }
  }

  if (!activeRepo) return;

  const targetFile = urlParams.get('file');
  const highlightStart = parseInt(urlParams.get('start') || '0');
  const highlightEnd = parseInt(urlParams.get('end') || '0');

  // Topbar and Repo Title
  const treeRepoNameEl = document.getElementById('tree-repo-name');
  if (treeRepoNameEl) treeRepoNameEl.textContent = activeRepo.name;

  const treeRepoEl = document.querySelector('.tree-repo');
  if (treeRepoEl && !treeRepoNameEl) {
    treeRepoEl.innerHTML = `<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg> ${escapeHtml(activeRepo.name)}`;
  }

  // Drawer Toggle Handlers for Mobile & Tablet
  const btnToggleExplorer = document.getElementById('btn-toggle-explorer');
  const btnToggleContext = document.getElementById('btn-toggle-context');
  const explorerSidebar = document.getElementById('file-tree-sidebar') || document.querySelector('.file-tree');
  const contextSidebar = document.getElementById('symbol-context-sidebar') || document.querySelector('.context-panel');

  if (btnToggleExplorer && explorerSidebar) {
    btnToggleExplorer.onclick = (e) => {
      e.stopPropagation();
      explorerSidebar.classList.toggle('open');
      if (contextSidebar) contextSidebar.classList.remove('open');
    };
  }

  if (btnToggleContext && contextSidebar) {
    btnToggleContext.onclick = (e) => {
      e.stopPropagation();
      contextSidebar.classList.toggle('open');
      if (explorerSidebar) explorerSidebar.classList.remove('open');
    };
  }

  // Close drawers when clicking in editor main on small screens
  const editorMain = document.querySelector('.editor-main');
  if (editorMain) {
    editorMain.addEventListener('click', () => {
      if (window.innerWidth <= 1100) {
        if (explorerSidebar) explorerSidebar.classList.remove('open');
        if (contextSidebar) contextSidebar.classList.remove('open');
      }
    });
  }

  let allFiles = [];
  let currentSelectedFile = targetFile;
  let activeSymbol = null;
  let cachedCallHierarchy = null;

  try {
    const rawFiles = await CodeMindAPI.getRepositoryFileTree(activeRepo.id);
    allFiles = rawFiles || [];

    const treeContainer = document.getElementById('file-tree-container') || document.querySelector('.file-tree');
    const countBadge = document.getElementById('explorer-count-badge');
    const searchInput = document.getElementById('explorer-search-input');

    if (countBadge) countBadge.textContent = `${allFiles.length} files`;

    if (!allFiles || allFiles.length === 0) {
      if (treeContainer) {
        treeContainer.innerHTML = `
          <div style="padding: 24px 12px; text-align: center; color: var(--muted); font-size: 11px;">
            <strong>No indexed files found</strong>
            <p style="margin-top: 4px;">Run repository indexing to populate files and symbols.</p>
          </div>
        `;
      }
      return;
    }

    // Determine initial active file
    if (!currentSelectedFile && allFiles.length > 0) {
      currentSelectedFile = allFiles[0].path;
    }

    // Build hierarchical tree data structure
    function buildHierarchy(fileList) {
      const root = { name: '', path: '', isDir: true, children: {} };

      fileList.forEach(f => {
        const parts = f.path.split('/');
        let current = root;
        let runningPath = '';

        for (let i = 0; i < parts.length; i++) {
          const part = parts[i];
          runningPath = runningPath ? `${runningPath}/${part}` : part;
          const isFile = (i === parts.length - 1);

          if (isFile) {
            current.children[part] = {
              name: part,
              path: f.path,
              isDir: false,
              fileData: f
            };
          } else {
            if (!current.children[part]) {
              current.children[part] = {
                name: part,
                path: runningPath,
                isDir: true,
                children: {}
              };
            }
            current = current.children[part];
          }
        }
      });

      return root;
    }

    // Set of open folders (default top-level and parents of selected file)
    const openFolders = new Set();
    if (currentSelectedFile) {
      const parts = currentSelectedFile.split('/');
      let p = '';
      for (let i = 0; i < parts.length - 1; i++) {
        p = p ? `${p}/${parts[i]}` : parts[i];
        openFolders.add(p);
      }
    }

    function renderTreeHTML(node, depth = 0, filterQuery = '') {
      const entries = Object.values(node.children || {});
      // Sort directories first, then alphabetical
      entries.sort((a, b) => {
        if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
        return a.name.localeCompare(b.name);
      });

      let html = '';
      entries.forEach(item => {
        if (item.isDir) {
          // If searching, check if any child matches
          const hasMatchingChild = filterQuery
            ? Object.values(item.children || {}).some(c => matchesSearch(c, filterQuery))
            : true;

          if (!hasMatchingChild) return;

          const isExpanded = filterQuery ? true : openFolders.has(item.path);
          const paddingLeft = depth * 14 + 6;

          html += `
            <div class="tree-item folder-item ${isExpanded ? 'expanded' : ''}" data-dir-path="${escapeHtml(item.path)}" style="padding-left: ${paddingLeft}px;" role="treeitem" aria-expanded="${isExpanded}">
              <span class="tree-arrow">
                <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m9 18 6-6-6-6"/></svg>
              </span>
              <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" style="color: #6366f1; flex-shrink: 0;"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>
              <span class="tree-name" style="font-weight: 500; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(item.name)}</span>
            </div>
            <div class="tree-children-container ${isExpanded ? 'open' : ''}" data-dir-children="${escapeHtml(item.path)}">
              ${renderTreeHTML(item, depth + 1, filterQuery)}
            </div>
          `;
        } else {
          // File node
          const matches = filterQuery
            ? (item.name.toLowerCase().includes(filterQuery) || item.path.toLowerCase().includes(filterQuery))
            : true;

          if (!matches) return;

          const isSelected = item.path === currentSelectedFile;
          const paddingLeft = depth * 14 + 20;

          html += `
            <div class="tree-item file-item ${isSelected ? 'selected' : ''}" data-file-path="${escapeHtml(item.path)}" style="padding-left: ${paddingLeft}px;" role="treeitem" title="${escapeHtml(item.path)}" aria-selected="${isSelected}">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false" style="color: var(--muted); flex-shrink: 0;"><path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/></svg>
              <span class="tree-name" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px;">${escapeHtml(item.name)}</span>
            </div>
          `;
        }
      });

      return html;
    }

    function matchesSearch(node, query) {
      if (!node.isDir) {
        return node.name.toLowerCase().includes(query) || node.path.toLowerCase().includes(query);
      }
      return Object.values(node.children || {}).some(child => matchesSearch(child, query));
    }

    function renderTree(filterQuery = '') {
      if (!treeContainer) return;

      const hierarchy = buildHierarchy(allFiles);
      const contentHtml = renderTreeHTML(hierarchy, 0, filterQuery.toLowerCase());

      if (!contentHtml.trim()) {
        treeContainer.innerHTML = `
          <div style="padding: 20px 12px; text-align: center; color: var(--muted); font-size: 11px;">
            No files match "${escapeHtml(filterQuery)}"
          </div>
        `;
        return;
      }

      treeContainer.innerHTML = contentHtml;
      bindTreeEvents();
    }

    function bindTreeEvents() {
      if (!treeContainer) return;

      // Folder click handler (expand/collapse)
      treeContainer.querySelectorAll('.folder-item').forEach(folderEl => {
        folderEl.onclick = (e) => {
          e.preventDefault();
          e.stopPropagation();
          const dirPath = folderEl.getAttribute('data-dir-path');
          const childrenContainer = treeContainer.querySelector(`[data-dir-children="${CSS.escape(dirPath)}"]`);

          if (folderEl.classList.contains('expanded')) {
            folderEl.classList.remove('expanded');
            folderEl.setAttribute('aria-expanded', 'false');
            if (childrenContainer) childrenContainer.classList.remove('open');
            openFolders.delete(dirPath);
          } else {
            folderEl.classList.add('expanded');
            folderEl.setAttribute('aria-expanded', 'true');
            if (childrenContainer) childrenContainer.classList.add('open');
            openFolders.add(dirPath);
          }
        };
      });

      // File click handler
      treeContainer.querySelectorAll('.file-item').forEach(fileEl => {
        fileEl.onclick = async (e) => {
          e.preventDefault();
          e.stopPropagation();
          const filePath = fileEl.getAttribute('data-file-path');
          if (!filePath) return;

          currentSelectedFile = filePath;

          // Update active highlight in tree
          treeContainer.querySelectorAll('.file-item').forEach(el => {
            el.classList.remove('selected');
            el.setAttribute('aria-selected', 'false');
          });
          fileEl.classList.add('selected');
          fileEl.setAttribute('aria-selected', 'true');

          // Close mobile drawer if open
          if (window.innerWidth <= 760 && explorerSidebar) {
            explorerSidebar.classList.remove('open');
          }

          // Update URL without full page reload
          const newUrl = new URL(window.location.href);
          if (activeRepo && activeRepo.id) {
            newUrl.searchParams.set('repo', activeRepo.id);
          }
          newUrl.searchParams.set('file', filePath);
          newUrl.searchParams.delete('start');
          newUrl.searchParams.delete('end');
          window.history.replaceState({}, '', newUrl.toString());

          await loadFileContent(filePath);
        };
      });
    }

    // Search filter event
    if (searchInput) {
      searchInput.oninput = (e) => {
        const query = e.target.value.trim();
        renderTree(query);
      };
    }

    renderTree('');

    // Load file content function
    async function loadFileContent(filePath, startLine = highlightStart, endLine = highlightEnd) {
      if (!filePath) return;

      const codeCanvasPre = document.getElementById('editor-code-pre') || document.querySelector('.code-canvas pre');
      const breadcrumbDir = document.getElementById('breadcrumb-dir-path');
      const breadcrumbStrong = document.getElementById('breadcrumb-filename') || document.querySelector('.breadcrumb strong');
      const fileTabName = document.getElementById('file-tab-name');
      const symbolBarText = document.getElementById('symbol-bar-text');
      const symbolBarCitation = document.getElementById('symbol-bar-citation-note');
      const citationText = document.getElementById('symbol-bar-citation-text');
      const askAiBtn = document.getElementById('editor-ask-ai-btn');
      const impactBtn = document.getElementById('editor-analyze-impact-btn');

      const parts = filePath.split('/');
      const fileName = parts.pop();
      const dirPath = parts.join('/') || 'root';

      if (breadcrumbDir) breadcrumbDir.textContent = dirPath;
      if (breadcrumbStrong) breadcrumbStrong.textContent = fileName;
      if (fileTabName) fileTabName.textContent = fileName;
      if (symbolBarText) symbolBarText.textContent = filePath;

      if (askAiBtn) {
        askAiBtn.href = `/assistant?repo=${activeRepo.id}&prompt=${encodeURIComponent(`Explain ${filePath}`)}`;
      }
      if (impactBtn) {
        impactBtn.href = `/impact_analysis?repo=${activeRepo.id}`;
      }

      if (codeCanvasPre) {
        codeCanvasPre.innerHTML = `
          <div style="padding: 24px 16px; color: var(--muted); font-size: 11px;">
            <svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 6px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
            Loading ${escapeHtml(fileName)}...
          </div>
        `;
      }

      try {
        const fileData = await CodeMindAPI.getFileContent(activeRepo.id, filePath, startLine, endLine);

        if (codeCanvasPre && fileData && fileData.content) {
          const lines = fileData.content.split('\n');
          codeCanvasPre.innerHTML = lines.map((line, idx) => {
            const ln = idx + 1;
            const isCited = (startLine && endLine && ln >= startLine && ln <= endLine);
            return `<div class="${isCited ? 'cited-line' : ''}" id="L${ln}"><span>${ln}</span><code>${escapeHtml(line)}</code></div>`;
          }).join('');

          if (startLine > 0) {
            const targetLineEl = document.getElementById(`L${startLine}`);
            if (targetLineEl) {
              setTimeout(() => {
                targetLineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }, 60);
            }
            if (symbolBarCitation) {
              symbolBarCitation.style.display = 'inline-flex';
              if (citationText) {
                citationText.textContent = `Cited in AI response · Lines ${startLine}–${endLine || startLine}`;
              }
            }
          } else if (symbolBarCitation) {
            symbolBarCitation.style.display = 'none';
          }
        } else if (codeCanvasPre) {
          codeCanvasPre.innerHTML = `
            <div style="padding: 32px 16px; text-align: center; color: var(--muted); font-size: 12px;">
              File is empty or contains non-text content.
            </div>
          `;
        }

        // Load Symbol Context for the current file
        await loadSymbolContextForFile(filePath, startLine, endLine);

      } catch (err) {
        if (codeCanvasPre) {
          codeCanvasPre.innerHTML = `
            <div style="padding: 24px 16px; color: var(--status-danger, #ef4444); font-size: 11px;">
              <strong>Error loading file content:</strong> ${escapeHtml(err.message || 'File not accessible')}
            </div>
          `;
        }
      }
    }

    // Load Symbol Context & Call Hierarchy
    async function loadSymbolContextForFile(filePath, startLine, endLine) {
      const symbolCard = document.getElementById('symbol-context-card') || document.querySelector('.symbol-card');
      const symbolTypeBadge = document.getElementById('symbol-type-badge');
      const symbolNameHeading = document.getElementById('symbol-name-heading');
      const symbolLinesCode = document.getElementById('symbol-lines-code');
      const contextContent = document.getElementById('context-content-body') || document.querySelector('.context-content');

      try {
        const symRes = await CodeMindAPI.searchSymbols(activeRepo.id, {
          filePath: filePath,
          limit: 50
        });

        const symbols = (symRes && symRes.symbols) ? symRes.symbols : [];

        if (symbols.length > 0) {
          activeSymbol = symbols.find(s => startLine && startLine >= s.start_line && startLine <= s.end_line) || symbols[0];

          if (symbolTypeBadge) symbolTypeBadge.textContent = (activeSymbol.symbol_type || 'SYMBOL').toUpperCase();
          if (symbolNameHeading) symbolNameHeading.textContent = activeSymbol.name;
          if (symbolLinesCode) symbolLinesCode.textContent = `Lines ${activeSymbol.start_line}–${activeSymbol.end_line}`;

          if (symbolCard) {
            const kindLower = (activeSymbol.symbol_type || 'symbol').toLowerCase();
            const typeIcon = symbolCard.querySelector('.type-icon');
            if (typeIcon) {
              typeIcon.className = `type-icon ${kindLower}`;
              typeIcon.textContent = (activeSymbol.symbol_type || 'S')[0].toUpperCase();
            }
          }

          // Fetch Call Hierarchy for active symbol
          cachedCallHierarchy = await CodeMindAPI.getCallHierarchy(activeRepo.id, activeSymbol.id, 2).catch(() => null);

        } else {
          activeSymbol = null;
          cachedCallHierarchy = null;
          if (symbolTypeBadge) symbolTypeBadge.textContent = 'FILE';
          if (symbolNameHeading) symbolNameHeading.textContent = filePath.split('/').pop();
          if (symbolLinesCode) symbolLinesCode.textContent = filePath;
        }

        renderCurrentContextTab();

      } catch (e) {
        console.warn('Could not populate symbol context:', e);
      }
    }

    // Context Tabs: Dependencies vs History
    let activeContextTab = 'dependencies';
    const tabDependencies = document.getElementById('context-tab-dependencies');
    const tabHistory = document.getElementById('context-tab-history');

    function renderCurrentContextTab() {
      const contextContent = document.getElementById('context-content-body') || document.querySelector('.context-content');
      if (!contextContent) return;

      if (activeContextTab === 'dependencies') {
        if (!activeSymbol) {
          contextContent.innerHTML = `
            <div style="font-size: 11px; color: var(--muted); padding: 16px 8px; text-align: center;">
              No symbol selected. Select a file containing parsed classes or functions.
            </div>
          `;
          return;
        }

        const hierarchyRes = cachedCallHierarchy;
        const callers = (hierarchyRes && hierarchyRes.callers) ? hierarchyRes.callers : [];
        const callees = (hierarchyRes && hierarchyRes.callees) ? hierarchyRes.callees : [];

        let chHtml = '';
        if (hierarchyRes && hierarchyRes.is_ambiguous) {
          chHtml += `<div style="font-size:10px; color:#d97706; background:rgba(245,158,11,0.1); padding:5px 8px; border-radius:4px; margin-bottom:8px;">⚠️ Multiple symbols with this name found across modules</div>`;
        }

        chHtml += `<span class="panel-label" style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:6px; letter-spacing:0.5px;">INCOMING CALLERS · ${callers.length}</span>`;
        if (callers.length === 0) {
          chHtml += `<p style="font-size: 11px; color: var(--muted); padding: 4px 0 10px;">No verified callers found in static index.</p>`;
        } else {
          chHtml += callers.slice(0, 6).map(c => `
            <a href="/code_viewer?repo=${activeRepo.id}&file=${encodeURIComponent(c.caller_file_path)}&start=${c.call_site_line || c.caller_start_line}" class="dep-link-btn" style="display:flex; align-items:center; gap:8px; text-decoration:none; padding:6px 0; border-bottom:1px solid var(--border); color:inherit;">
              <span class="dep-icon" style="font-weight:700; color:#4f46e5;">ƒ</span>
              <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                <strong style="font-size:11.5px; display:block; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(c.caller_name)}</strong>
                <small style="color:var(--muted); font-size:9.5px; overflow:hidden; text-overflow:ellipsis; display:block;">${escapeHtml(c.caller_file_path)}:L${c.call_site_line || c.caller_start_line}</small>
              </span>
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m9 18 6-6-6-6"/></svg>
            </a>
          `).join('');
        }

        chHtml += `<span class="panel-label" style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin:12px 0 6px; letter-spacing:0.5px;">OUTGOING CALLEES · ${callees.length}</span>`;
        if (callees.length === 0) {
          chHtml += `<p style="font-size: 11px; color: var(--muted); padding: 4px 0 10px;">No verified callees found in static index.</p>`;
        } else {
          chHtml += callees.slice(0, 6).map(c => `
            <a href="/code_viewer?repo=${activeRepo.id}&file=${encodeURIComponent(c.callee_file_path)}&start=${c.callee_start_line}" class="dep-link-btn" style="display:flex; align-items:center; gap:8px; text-decoration:none; padding:6px 0; border-bottom:1px solid var(--border); color:inherit;">
              <span class="dep-icon out" style="font-weight:700; color:#ea580c;">ƒ</span>
              <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                <strong style="font-size:11.5px; display:block; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(c.callee_name)}</strong>
                <small style="color:var(--muted); font-size:9.5px; overflow:hidden; text-overflow:ellipsis; display:block;">${escapeHtml(c.callee_file_path)}:L${c.callee_start_line}</small>
              </span>
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m9 18 6-6-6-6"/></svg>
            </a>
          `).join('');
        }

        contextContent.innerHTML = chHtml;

      } else if (activeContextTab === 'history') {
        renderCommitHistoryTab(contextContent);
      }
    }

    async function renderCommitHistoryTab(container) {
      container.innerHTML = `
        <div style="padding: 16px 8px; text-align: center; color: var(--muted); font-size: 11px;">
          <svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
          Fetching recent commits...
        </div>
      `;

      try {
        const res = await CodeMindAPI.getCommits(activeRepo.id, { perPage: 8 });
        const commits = (res && res.commits) ? res.commits : [];

        if (commits.length === 0) {
          container.innerHTML = `
            <div style="font-size: 11px; color: var(--muted); padding: 16px 8px; text-align: center;">
              No commits recorded on branch ${escapeHtml(activeRepo.default_branch || 'main')}.
            </div>
          `;
          return;
        }

        container.innerHTML = `
          <span class="panel-label" style="display:block; font-size:10px; font-weight:700; color:var(--muted); margin-bottom:8px; letter-spacing:0.5px;">RECENT COMMITS (${commits.length})</span>
          ${commits.map(c => `
            <a href="/git_history?sha=${encodeURIComponent(c.sha)}" style="display:block; text-decoration:none; color:inherit; padding:8px 0; border-bottom:1px solid var(--border); font-size:11px;">
              <strong style="display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-bottom:2px;">${escapeHtml(c.message)}</strong>
              <div style="display:flex; justify-content:space-between; align-items:center; color:var(--muted); font-size:10px;">
                <span>${escapeHtml(c.author_name || 'Author')} · ${escapeHtml(c.time_ago || '')}</span>
                <code style="background:var(--surface-subtle); padding:1px 4px; border-radius:3px;">${escapeHtml(c.short_sha)}</code>
              </div>
            </a>
          `).join('')}
        `;
      } catch (err) {
        container.innerHTML = `
          <div style="font-size: 11px; color: var(--muted); padding: 16px 8px; text-align: center;">
            Commit history unavailable.
          </div>
        `;
      }
    }

    if (tabDependencies) {
      tabDependencies.onclick = () => {
        activeContextTab = 'dependencies';
        tabDependencies.classList.add('active');
        tabDependencies.setAttribute('aria-selected', 'true');
        if (tabHistory) {
          tabHistory.classList.remove('active');
          tabHistory.setAttribute('aria-selected', 'false');
        }
        renderCurrentContextTab();
      };
    }

    if (tabHistory) {
      tabHistory.onclick = () => {
        activeContextTab = 'history';
        tabHistory.classList.add('active');
        tabHistory.setAttribute('aria-selected', 'true');
        if (tabDependencies) {
          tabDependencies.classList.remove('active');
          tabDependencies.setAttribute('aria-selected', 'false');
        }
        renderCurrentContextTab();
      };
    }

    // Initial file load
    if (currentSelectedFile) {
      await loadFileContent(currentSelectedFile, highlightStart, highlightEnd);
    }

  } catch (err) {
    console.warn('Error hydrating code viewer:', err);
  }
}
// --- Global Topbar & Navigation Hydration ---
async function hydrateGlobalTopbar(activeRepo) {
  const topbarRepo = document.querySelector('.repo-selector strong');
  const topbarBranch = document.getElementById('topbar-branch-text');
  const repoSelector = document.querySelector('.repo-selector');
  const notificationBtn = document.querySelector('.icon-btn.notification');
  const searchTrigger = document.querySelector('.search-trigger');

  if (activeRepo) {
    if (topbarRepo) topbarRepo.textContent = activeRepo.name;
    if (topbarBranch) topbarBranch.textContent = activeRepo.default_branch || 'main';
  } else {
    if (topbarRepo) topbarRepo.textContent = 'No repository';
    if (topbarBranch) topbarBranch.textContent = 'main';
  }

  // Hook up interactive repository switcher dropdown
  if (repoSelector) {
    // Ensure parent has relative positioning for dropdown alignment
    let wrapper = repoSelector.parentElement;
    if (!wrapper.classList.contains('repo-selector-wrapper')) {
      const newWrapper = document.createElement('div');
      newWrapper.className = 'repo-selector-wrapper';
      repoSelector.parentNode.insertBefore(newWrapper, repoSelector);
      newWrapper.appendChild(repoSelector);
      wrapper = newWrapper;
    }

    // Remove existing dropdown if any
    const existingMenu = wrapper.querySelector('.repo-dropdown-menu');
    if (existingMenu) existingMenu.remove();

    repoSelector.onclick = async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const existingDropdown = wrapper.querySelector('.repo-dropdown-menu');
      if (existingDropdown) {
        existingDropdown.remove();
        return;
      }

      // Close any other open dropdowns
      document.querySelectorAll('.repo-dropdown-menu').forEach(m => m.remove());

      try {
        const repos = await CodeMindAPI.getRepositories();
        if (!repos || repos.length === 0) {
          window.location.href = '/repositories_modal';
          return;
        }

        const currentActive = await getActiveRepository();
        const currentActiveId = currentActive ? currentActive.id : null;

        const dropdown = document.createElement('div');
        dropdown.className = 'repo-dropdown-menu';
        dropdown.id = 'codemind-repo-dropdown';

        dropdown.innerHTML = `
          <div class="repo-dropdown-header">
            <small>Connected Repositories</small>
            <span class="badge badge-neutral">${repos.length} total</span>
          </div>
          ${repos.length > 3 ? `
            <div class="repo-dropdown-search-wrap">
              <input type="text" class="repo-dropdown-search" placeholder="Filter repositories..." id="repo-dropdown-filter" autocomplete="off" />
            </div>
          ` : ''}
          <div class="repo-dropdown-list" id="repo-dropdown-items-list">
            ${repos.map(r => {
              const isActive = r.id === currentActiveId;
              const isReady = r.status === 'ready';
              const isIndexing = r.status === 'indexing';
              const dotClass = isReady ? 'status-dot' : isIndexing ? 'status-dot warning' : 'status-dot danger';
              return `
                <button type="button" class="repo-dropdown-item ${isActive ? 'active' : ''}" data-repo-id="${r.id}" data-repo-name="${escapeHtml((r.name || '').toLowerCase())}">
                  <span class="repo-dropdown-icon">
                    <svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>
                    </svg>
                  </span>
                  <div class="repo-dropdown-info">
                    <span class="repo-dropdown-name">${escapeHtml(r.full_name || r.name)}</span>
                    <span class="repo-dropdown-meta">
                      <span class="${dotClass}" style="width:6px; height:6px;"></span>
                      <span class="repo-dropdown-branch">${escapeHtml(r.default_branch || 'main')}</span>
                      <span>${formatNumber(r.files_count || 0)} files</span>
                    </span>
                  </div>
                  ${isActive ? `
                    <span class="repo-dropdown-check">
                      <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                        <polyline points="20 6 9 17 4 12"></polyline>
                      </svg>
                    </span>
                  ` : ''}
                </button>
              `;
            }).join('')}
          </div>
          <div class="repo-dropdown-footer">
            <a href="/repositories">Manage repositories →</a>
            <a href="/repositories_modal">+ Connect repo</a>
          </div>
        `;

        wrapper.appendChild(dropdown);

        // Bind filter input
        const filterInput = dropdown.querySelector('#repo-dropdown-filter');
        if (filterInput) {
          filterInput.focus();
          filterInput.onclick = (e) => e.stopPropagation();
          filterInput.oninput = (e) => {
            const query = e.target.value.trim().toLowerCase();
            dropdown.querySelectorAll('.repo-dropdown-item').forEach(btn => {
              const name = btn.getAttribute('data-repo-name') || '';
              btn.style.display = (!query || name.includes(query)) ? 'flex' : 'none';
            });
          };
        }

        // Bind item click
        dropdown.querySelectorAll('.repo-dropdown-item').forEach(btn => {
          btn.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const chosenId = parseInt(btn.getAttribute('data-repo-id'));
            dropdown.remove();
            await window.switchActiveRepository(chosenId);
          };
        });

        // Close on escape or outside click
        const closeDropdownHandler = (e) => {
          if (!wrapper.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeDropdownHandler);
            document.removeEventListener('keydown', keydownHandler);
          }
        };
        const keydownHandler = (e) => {
          if (e.key === 'Escape') {
            dropdown.remove();
            document.removeEventListener('click', closeDropdownHandler);
            document.removeEventListener('keydown', keydownHandler);
          }
        };
        setTimeout(() => {
          document.addEventListener('click', closeDropdownHandler);
          document.addEventListener('keydown', keydownHandler);
        }, 10);

      } catch (err) {
        console.warn('Failed to load repositories for dropdown:', err);
      }
    };
  }

  // Hook up Notifications badge and modal
  if (notificationBtn) {
    try {
      const notifData = await CodeMindAPI.getNotifications();
      const countEl = notificationBtn.querySelector('span');
      const unreadCount = notifData.unread_count || 0;
      if (countEl) {
        countEl.style.display = unreadCount > 0 ? 'block' : 'none';
      }
      notificationBtn.onclick = (e) => {
        e.preventDefault();
        const items = notifData.notifications || [];
        if (items.length === 0) {
          alert('Notifications: No pending jobs or security alerts.');
        } else {
          const list = items.map(n => `• [${n.severity.toUpperCase()}] ${n.title}: ${n.message}`).join('\n\n');
          alert(`Application Notifications (${items.length}):\n\n${list}`);
        }
      };
    } catch (err) {
      // Graceful
    }
  }

  // Hook up Global Symbol Search (⌘K / Ctrl+K and search trigger)
  function openGlobalSearchModal() {
    if (!activeRepo) {
      alert('Connect and index a repository to search files and code symbols.');
      return;
    }

    let modalBackdrop = document.getElementById('cm-symbol-search-modal');
    if (modalBackdrop) {
      modalBackdrop.remove();
    }

    modalBackdrop = document.createElement('div');
    modalBackdrop.className = 'cm-search-modal-backdrop';
    modalBackdrop.id = 'cm-symbol-search-modal';

    modalBackdrop.innerHTML = `
      <div class="cm-palette-box" role="dialog" aria-modal="true" aria-label="Symbol Search">
        <div class="cm-palette-header">
          <div class="cm-palette-input-wrap">
            <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false">
              <circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>
            </svg>
            <input type="text" class="cm-palette-input" id="cm-palette-search-input" placeholder="Search symbols, functions, classes, methods in ${escapeHtml(activeRepo.name)}..." autocomplete="off" />
            <span class="cm-palette-repo-badge">${escapeHtml(activeRepo.name)}</span>
          </div>
          <div class="cm-palette-filters" id="cm-palette-filter-bar">
            <button class="cm-filter-chip active" data-type="">All</button>
            <button class="cm-filter-chip" data-type="function">Functions</button>
            <button class="cm-filter-chip" data-type="class">Classes</button>
            <button class="cm-filter-chip" data-type="method">Methods</button>
            <button class="cm-filter-chip" data-type="variable">Variables</button>
            <button class="cm-filter-chip" data-type="type">Types</button>
          </div>
        </div>
        <div class="cm-palette-results" id="cm-palette-results-list">
          <div class="cm-palette-empty">Type a symbol name to search across ${escapeHtml(activeRepo.name)}...</div>
        </div>
        <div class="cm-palette-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span>
          <span><kbd>↵</kbd> View in Code Viewer</span>
          <span><kbd>esc</kbd> Close</span>
        </div>
      </div>
    `;

    document.body.appendChild(modalBackdrop);

    const input = document.getElementById('cm-palette-search-input');
    const resultsContainer = document.getElementById('cm-palette-results-list');
    const filterBar = document.getElementById('cm-palette-filter-bar');

    let currentResults = [];
    let selectedIndex = -1;
    let currentFilterType = '';
    let debounceTimer = null;

    if (input) {
      input.focus();
    }

    const closeModal = () => {
      modalBackdrop.remove();
    };

    modalBackdrop.addEventListener('click', (e) => {
      if (e.target === modalBackdrop) {
        closeModal();
      }
    });

    const renderResults = () => {
      if (!currentResults || currentResults.length === 0) {
        resultsContainer.innerHTML = `<div class="cm-palette-empty">No symbols found matching "${escapeHtml(input.value)}".</div>`;
        return;
      }

      resultsContainer.innerHTML = currentResults.map((sym, idx) => {
        const isSelected = idx === selectedIndex;
        const kindLower = (sym.symbol_type || 'symbol').toLowerCase();
        const rId = sym.repository_id || (activeRepo ? activeRepo.id : '');
        return `
          <a class="cm-palette-item ${isSelected ? 'selected' : ''}" data-index="${idx}" href="/code_viewer?repo=${rId}&file=${encodeURIComponent(sym.file_path)}&start=${sym.start_line}&end=${sym.end_line}">
            <div class="cm-palette-item-head">
              <div class="cm-palette-item-title-wrap">
                <span class="cm-palette-kind-badge ${kindLower}">${escapeHtml(sym.symbol_type || 'symbol')}</span>
                <span class="cm-palette-symbol-name">${escapeHtml(sym.name)}</span>
              </div>
              <span class="cm-palette-file-path">${escapeHtml(sym.file_path)} : L${sym.start_line}–${sym.end_line}</span>
            </div>
            ${sym.snippet ? `<div class="cm-palette-snippet">${escapeHtml(sym.snippet)}</div>` : ''}
          </a>
        `;
      }).join('');

      // Click binding
      resultsContainer.querySelectorAll('.cm-palette-item').forEach(el => {
        el.addEventListener('click', (e) => {
          e.preventDefault();
          const idx = parseInt(el.getAttribute('data-index'));
          const item = currentResults[idx];
          if (item) {
            const rId = item.repository_id || (activeRepo ? activeRepo.id : '');
            window.location.href = `/code_viewer?repo=${rId}&file=${encodeURIComponent(item.file_path)}&start=${item.start_line}&end=${item.end_line}`;
          }
        });
      });

      const selectedEl = resultsContainer.querySelector('.cm-palette-item.selected');
      if (selectedEl) {
        selectedEl.scrollIntoView({ block: 'nearest' });
      }
    };

    const executeSearch = async () => {
      const q = input.value.trim();
      if (!q) {
        currentResults = [];
        selectedIndex = -1;
        resultsContainer.innerHTML = `<div class="cm-palette-empty">Type a symbol name to search across ${escapeHtml(activeRepo.name)}...</div>`;
        return;
      }

      resultsContainer.innerHTML = `<div class="cm-palette-empty">Searching symbols in ${escapeHtml(activeRepo.name)}...</div>`;

      try {
        const res = await CodeMindAPI.searchSymbols(activeRepo.id, {
          query: q,
          symbol_type: currentFilterType || undefined,
          limit: 30
        });

        currentResults = (res && res.symbols) ? res.symbols : [];
        selectedIndex = currentResults.length > 0 ? 0 : -1;
        renderResults();
      } catch (err) {
        resultsContainer.innerHTML = `<div class="cm-palette-empty" style="color: #ef4444;">Search failed: ${escapeHtml(err.message)}</div>`;
      }
    };

    input.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(executeSearch, 220);
    });

    filterBar.querySelectorAll('.cm-filter-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        filterBar.querySelectorAll('.cm-filter-chip').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilterType = btn.getAttribute('data-type');
        executeSearch();
      });
    });

    modalBackdrop.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (currentResults.length > 0) {
          selectedIndex = (selectedIndex + 1) % currentResults.length;
          renderResults();
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (currentResults.length > 0) {
          selectedIndex = (selectedIndex - 1 + currentResults.length) % currentResults.length;
          renderResults();
        }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (selectedIndex >= 0 && currentResults[selectedIndex]) {
          const item = currentResults[selectedIndex];
          const rId = item.repository_id || (activeRepo ? activeRepo.id : '');
          window.location.href = `/code_viewer?repo=${rId}&file=${encodeURIComponent(item.file_path)}&start=${item.start_line}&end=${item.end_line}`;
        }
      }
    });
  }

  if (searchTrigger) {
    searchTrigger.onclick = (e) => {
      e.preventDefault();
      openGlobalSearchModal();
    };
  }

  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      openGlobalSearchModal();
    }
  });
}

// --- Git History & Diff Viewer Hydration ---
async function hydrateGitHistoryView() {
  const activeRepo = await getActiveRepository();
  const commitListContainer = document.getElementById('commit-list-container');
  const commitDetailContainer = document.getElementById('commit-detail-container');
  const branchText = document.getElementById('git-branch-name');
  const commitCountBadge = document.getElementById('commit-count-badge');
  const searchInput = document.getElementById('commit-search-input');
  const dateBtn = document.getElementById('commit-date-btn');
  const dateLabel = document.getElementById('commit-date-label');
  const askChangeBtn = document.getElementById('ask-change-btn');

  if (!activeRepo) {
    if (commitListContainer) {
      commitListContainer.innerHTML = `
        <div class="list-empty" style="padding: 32px 16px;">
          <svg class="icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
            <circle cx="6" cy="5" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="6" cy="19" r="2"/><path d="M6 7v10M8 7c4 0 4 6 8 6h2M18 9v8"/>
          </svg>
          <strong>No repository connected</strong>
          <p>Connect a GitHub repository to browse commit history and diffs.</p>
          <a href="/repositories_modal" class="btn btn-primary" style="margin-top: 12px;">Connect repository</a>
        </div>
      `;
    }
    if (commitDetailContainer) {
      commitDetailContainer.innerHTML = `
        <div class="empty-state" style="padding: 48px 24px; text-align: center;">
          <h3 class="empty-state-title">No Commit Selected</h3>
          <p class="empty-state-desc">Select a connected repository and commit to inspect file diffs and evidence-backed AI analysis.</p>
        </div>
      `;
    }
    if (commitCountBadge) commitCountBadge.textContent = '0 commits';
    return;
  }

  const targetBranch = activeRepo.default_branch || 'main';
  if (branchText) branchText.textContent = targetBranch;

  let currentCommits = [];
  let selectedCommitSha = null;
  let activeSearch = '';
  let activeSince = null;

  async function fetchAndRenderCommits() {
    if (commitListContainer) {
      commitListContainer.innerHTML = `
        <div class="list-empty">
          <strong>Fetching commit log...</strong>
          <p>Querying verified commits for branch ${escapeHtml(targetBranch)}.</p>
        </div>
      `;
    }

    try {
      const res = await CodeMindAPI.getCommits(activeRepo.id, {
        branch: targetBranch,
        search: activeSearch || null,
        since: activeSince || null,
        perPage: 30
      });

      currentCommits = res.commits || [];
      if (commitCountBadge) commitCountBadge.textContent = `${currentCommits.length} commits`;

      if (currentCommits.length === 0) {
        if (commitListContainer) {
          commitListContainer.innerHTML = `
            <div class="list-empty">
              <strong>No commits found</strong>
              <p>${activeSearch ? `No commits match "${escapeHtml(activeSearch)}"` : `No commits available on branch ${escapeHtml(targetBranch)}.`}</p>
            </div>
          `;
        }
        if (commitDetailContainer) {
          commitDetailContainer.innerHTML = `
            <div style="padding: 36px; text-align: center; color: var(--muted); font-size: 11px;">
              No commit details available.
            </div>
          `;
        }
        return;
      }

      // Check URL param or keep selected or default to first
      const urlParams = new URLSearchParams(window.location.search);
      const urlSha = urlParams.get('sha');
      const commitToSelect = currentCommits.find(c => c.sha === urlSha || c.short_sha === urlSha) || currentCommits[0];
      selectedCommitSha = commitToSelect.sha;

      renderCommitList();
      await loadCommitDetail(selectedCommitSha);

    } catch (err) {
      if (commitListContainer) {
        commitListContainer.innerHTML = `
          <div class="list-empty" style="color: var(--status-danger);">
            <strong>Error loading commits</strong>
            <p>${escapeHtml(err.message || 'Unable to fetch commits')}</p>
          </div>
        `;
      }
    }
  }

  function renderCommitList() {
    if (!commitListContainer) return;
    commitListContainer.innerHTML = currentCommits.map(commit => {
      const isSelected = commit.sha === selectedCommitSha;
      return `
        <button class="commit-item ${isSelected ? 'selected' : ''}" data-sha="${escapeHtml(commit.sha)}">
          <span class="timeline-dot"></span>
          <span>
            <strong>${escapeHtml(commit.message)}</strong>
            <small>${escapeHtml(commit.author_name)} · ${escapeHtml(commit.time_ago)}</small>
            <code>${escapeHtml(commit.short_sha)}</code>
          </span>
          <span class="diff-stat"><b>+${commit.additions || 0}</b><i>−${commit.deletions || 0}</i></span>
        </button>
      `;
    }).join('');

    // Attach click listeners to every commit item
    commitListContainer.querySelectorAll('.commit-item').forEach(btn => {
      btn.addEventListener('click', async () => {
        const sha = btn.getAttribute('data-sha');
        if (!sha || sha === selectedCommitSha) return;

        selectedCommitSha = sha;
        commitListContainer.querySelectorAll('.commit-item').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');

        await loadCommitDetail(sha);
      });
    });
  }

  async function loadCommitDetail(sha) {
    if (!commitDetailContainer) return;

    // Loading indicator inside detail view
    commitDetailContainer.innerHTML = `
      <div style="padding: 48px; text-align: center;">
        <span class="ai-orb" style="margin: 0 auto 12px; display: inline-grid;">
          <svg class="icon animate-spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
        </span>
        <h3 style="font-size: 13px; margin: 0 0 4px;">Loading commit details...</h3>
        <p style="color: var(--muted); font-size: 10px;">Fetching file patches, statistics, and AI change impact analysis.</p>
      </div>
    `;

    try {
      const detail = await CodeMindAPI.getCommitDetail(activeRepo.id, sha, targetBranch);

      // Render changed files and diffs
      let filesDiffHtml = '';
      if (detail.files && detail.files.length > 0) {
        filesDiffHtml = detail.files.map(file => {
          let diffLinesHtml = '';
          if (file.patch) {
            const rawLines = file.patch.split('\n');
            let oldLn = 1;
            let newLn = 1;
            diffLinesHtml = rawLines.map(line => {
              if (line.startsWith('@@')) {
                const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
                if (match) {
                  oldLn = parseInt(match[1]);
                  newLn = parseInt(match[2]);
                }
                return `<div style="background: var(--surface-subtle); color: var(--muted); font-size: 8px;"><span></span><span></span><code>${escapeHtml(line)}</code></div>`;
              } else if (line.startsWith('+') && !line.startsWith('+++')) {
                const out = `<div class="added"><span> </span><span>${newLn}</span><code>${escapeHtml(line)}</code></div>`;
                newLn++;
                return out;
              } else if (line.startsWith('-') && !line.startsWith('---')) {
                const out = `<div class="removed"><span>${oldLn}</span><span> </span><code>${escapeHtml(line)}</code></div>`;
                oldLn++;
                return out;
              } else {
                const out = `<div><span>${oldLn}</span><span>${newLn}</span><code>${escapeHtml(line)}</code></div>`;
                oldLn++;
                newLn++;
                return out;
              }
            }).join('');
          } else {
            diffLinesHtml = `<div style="padding: 14px 18px; color: var(--muted); font-size: 9.5px;">Binary, large, or unmodified file — raw patch unavailable.</div>`;
          }

          return `
            <div class="file-change-head">
              <strong><svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/></svg> ${escapeHtml(file.filename)}</strong>
              <span><b>+${file.additions}</b><i>−${file.deletions}</i></span>
            </div>
            <div class="diff-view">
              ${diffLinesHtml}
            </div>
          `;
        }).join('');
      } else {
        filesDiffHtml = `<div style="padding: 24px; text-align: center; color: var(--muted); font-size: 10px;">No file modifications recorded in this commit.</div>`;
      }

      // Render AI Evidence Explanation
      let explanationHtml = '';
      if (detail.ai_explanation) {
        const citationsHtml = (detail.ai_explanation.sources || []).map(s => `
          <button class="citation" onclick="window.location.href='/code_viewer?repo=${activeRepo ? activeRepo.id : ''}&file=${encodeURIComponent(s.file_path || '')}'">
            <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/></svg>
            ${escapeHtml(s.label || s.file_path)}
          </button>
        `).join('');

        explanationHtml = `
          <div class="history-explanation">
            <div class="ai-message-head">
              <span class="ai-orb">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m12 3-1.7 4.3L6 9l4.3 1.7L12 15l1.7-4.3L18 9l-4.3-1.7L12 3Z"/><path d="m5 15-.8 2.2L2 18l2.2.8L5 21l.8-2.2L8 18l-2.2-.8L5 15Z"/></svg>
              </span>
              <div>
                <strong>Evidence-based explanation</strong>
                <span class="badge badge-success">${(detail.ai_explanation.sources || []).length} sources verified</span>
              </div>
            </div>
            <p><strong>Confirmed:</strong> ${escapeHtml(detail.ai_explanation.confirmed || 'Change inspects repository modification.')}</p>
            <p><strong>Inference:</strong> ${escapeHtml(detail.ai_explanation.inference || 'No speculative intent inferred.')}</p>
            ${citationsHtml ? `<div>${citationsHtml}</div>` : ''}
          </div>
        `;
      }

      const initials = (detail.author_name || 'Git').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();

      commitDetailContainer.innerHTML = `
        <div class="commit-detail-head">
          <div>
            <code>${escapeHtml(detail.short_sha)}</code>
            <h2>${escapeHtml(detail.message)}</h2>
            <p><span class="avatar avatar-small">${escapeHtml(initials)}</span> ${escapeHtml(detail.author_name)} committed ${escapeHtml(detail.time_ago)}</p>
          </div>
          <div>
            <button class="btn btn-secondary" id="copy-hash-btn" data-sha="${escapeHtml(detail.sha)}">Copy hash</button>
          </div>
        </div>
        <div class="commit-metadata">
          <span><strong>${detail.total_files}</strong> files changed</span>
          <span class="added">+${detail.additions} additions</span>
          <span class="deleted">−${detail.deletions} deletions</span>
          <span><svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="6" cy="5" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="6" cy="19" r="2"/><path d="M6 7v10M8 7c5 0 4-2 8-2"/></svg> ${escapeHtml(detail.branch || targetBranch)}</span>
          ${detail.parent_sha ? `<span>Parent: <code>${escapeHtml(detail.parent_sha.substring(0, 7))}</code></span>` : ''}
        </div>

        ${filesDiffHtml}
        ${explanationHtml}
      `;

      // Copy Hash Button Interaction
      const copyBtn = document.getElementById('copy-hash-btn');
      if (copyBtn) {
        copyBtn.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(detail.sha);
            copyBtn.textContent = 'Copied!';
            copyBtn.style.color = 'var(--success)';
            setTimeout(() => {
              copyBtn.textContent = 'Copy hash';
              copyBtn.style.color = '';
            }, 2000);
          } catch (e) {
            alert(`Commit Hash: ${detail.sha}`);
          }
        });
      }

      // Ask About This Change Interaction
      if (askChangeBtn) {
        askChangeBtn.onclick = () => {
          const prompt = `Explain commit ${detail.short_sha} (${detail.message}) and its architectural impact on the repository.`;
          window.location.href = `/assistant?q=${encodeURIComponent(prompt)}`;
        };
      }

    } catch (err) {
      commitDetailContainer.innerHTML = `
        <div style="padding: 36px; text-align: center; color: var(--status-danger);">
          <h3 style="font-size: 13px;">Error loading commit details</h3>
          <p style="font-size: 10px;">${escapeHtml(err.message || 'Unable to retrieve commit details')}</p>
        </div>
      `;
    }
  }

  // Hook up search filter
  let searchTimer = null;
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        activeSearch = e.target.value.trim();
        fetchAndRenderCommits();
      }, 300);
    });
  }

  // Hook up date filter
  if (dateBtn) {
    const dateOptions = [
      { label: 'Any date', since: null },
      { label: 'Today', since: new Date(Date.now() - 24 * 3600 * 1000).toISOString() },
      { label: 'Past 7 days', since: new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString() },
      { label: 'Past 30 days', since: new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString() }
    ];
    let dateIdx = 0;
    dateBtn.addEventListener('click', () => {
      dateIdx = (dateIdx + 1) % dateOptions.length;
      activeSince = dateOptions[dateIdx].since;
      if (dateLabel) dateLabel.textContent = dateOptions[dateIdx].label;
      fetchAndRenderCommits();
    });
  }

  // Initial fetch
  await fetchAndRenderCommits();
}

// --- Security Insights Hydration ---
async function hydrateSecurityInsightsView() {
  const activeRepo = await getActiveRepository();
  const findingsContainer = document.getElementById('security-findings-container');
  const detailContainer = document.getElementById('security-detail-container');
  const highCountEl = document.getElementById('security-high-count');
  const medCountEl = document.getElementById('security-medium-count');
  const reviewedCountEl = document.getElementById('security-reviewed-count');
  const runScanBtn = document.getElementById('run-scan-btn');
  const filterBtn = document.getElementById('security-filter-btn');
  const filterLabel = document.getElementById('security-filter-label');

  if (!activeRepo) {
    if (findingsContainer) {
      findingsContainer.innerHTML = `
        <div class="list-empty" style="padding: 32px 16px;">
          <svg class="icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>
          </svg>
          <strong>No repository connected</strong>
          <p>Connect a GitHub repository to inspect code security findings and secret exposure.</p>
          <a href="/repositories_modal" class="btn btn-primary" style="margin-top: 12px;">Connect repository</a>
        </div>
      `;
    }
    if (detailContainer) {
      detailContainer.innerHTML = `
        <div style="padding: 48px; text-align: center; color: var(--muted); font-size: 11px;">
          No security findings to display.
        </div>
      `;
    }
    return;
  }

  // Update topbar repo and branch display
  const topbarRepo = document.querySelector('.repo-selector strong');
  const topbarBranch = document.getElementById('topbar-branch-text');
  if (topbarRepo) topbarRepo.textContent = activeRepo.name;
  if (topbarBranch) topbarBranch.textContent = activeRepo.default_branch || 'main';

  const activeBranch = activeRepo.default_branch || 'main';
  let allFindings = [];
  let selectedFindingId = null;
  let severityFilter = 'ALL';
  let latestSummary = null;

  async function loadFindings(summaryOverride = null) {
    if (!summaryOverride && findingsContainer) {
      findingsContainer.innerHTML = `
        <div class="list-empty">
          <strong>Scanning security findings...</strong>
          <p>Querying verified static security analysis for ${escapeHtml(activeRepo.name)}.</p>
        </div>
      `;
    }

    try {
      const summary = summaryOverride || await CodeMindAPI.getSecurityFindings(activeRepo.id, activeBranch);
      latestSummary = summary;
      if (highCountEl) highCountEl.textContent = summary.high_count ?? summary.high_severity ?? 0;
      if (medCountEl) medCountEl.textContent = summary.medium_count ?? summary.medium_severity ?? 0;
      if (reviewedCountEl) reviewedCountEl.textContent = summary.reviewed_count ?? summary.reviewed ?? 0;

      allFindings = summary.findings || [];
      renderFindingsList();

      if (allFindings.length > 0) {
        selectedFindingId = allFindings[0].id;
        renderFindingDetail(allFindings[0]);
      } else {
        if (detailContainer) {
          let emptyDetailMsg = 'Scan completed: No security findings detected for this repository.';
          if (summary.status === 'indexing_in_progress') {
            emptyDetailMsg = 'Repository indexing is currently in progress. Complete results will be displayed once indexing finishes.';
          } else if (summary.total_files === 0) {
            emptyDetailMsg = 'Repository has not been indexed yet. Please index the repository to run security analysis.';
          } else if (summary.files_scanned === 0) {
            emptyDetailMsg = 'No supported source code files detected for security analysis.';
          }
          detailContainer.innerHTML = `
            <div style="padding: 36px; text-align: center; color: var(--muted); font-size: 11px;">
              ${escapeHtml(emptyDetailMsg)}
            </div>
          `;
        }
      }
      await updateSecuritySidebarBadge(activeRepo.id);
    } catch (err) {
      if (findingsContainer) {
        findingsContainer.innerHTML = `
          <div class="list-empty" style="color: var(--status-danger);">
            <strong>Error loading findings</strong>
            <p>${escapeHtml(err.message || 'Server error')}</p>
          </div>
        `;
      }
    }
  }

  function renderFindingsList() {
    if (!findingsContainer) return;

    // Handle distinct repository states when findings list is empty
    if (allFindings.length === 0) {
      if (latestSummary && latestSummary.status === 'indexing_in_progress') {
        findingsContainer.innerHTML = `
          <div class="list-empty" style="padding: 32px 16px;">
            <svg class="icon animate-spin" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
              <circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/>
            </svg>
            <strong>Repository indexing in progress</strong>
            <p>${escapeHtml(latestSummary.message || 'Indexing is in progress. Findings will update automatically once indexing completes.')}</p>
          </div>
        `;
        return;
      }

      if (latestSummary && latestSummary.total_files === 0) {
        findingsContainer.innerHTML = `
          <div class="list-empty" style="padding: 32px 16px;">
            <svg class="icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>
            </svg>
            <strong>Repository not indexed</strong>
            <p>${escapeHtml(latestSummary.message || 'No source files have been indexed for this repository yet.')}</p>
            <a href="/repositories" class="btn btn-primary" style="margin-top: 12px;">Go to Repositories</a>
          </div>
        `;
        return;
      }

      if (latestSummary && latestSummary.files_scanned === 0 && latestSummary.total_files > 0) {
        findingsContainer.innerHTML = `
          <div class="list-empty" style="padding: 32px 16px;">
            <svg class="icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
              <circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
            </svg>
            <strong>No supported source files</strong>
            <p>${escapeHtml(latestSummary.message || 'No supported source code files detected in this repository.')}</p>
          </div>
        `;
        return;
      }

      findingsContainer.innerHTML = `
        <div class="list-empty" style="padding: 32px 16px;">
          <svg class="icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>
          </svg>
          <strong>Scan completed: 0 findings</strong>
          <p>${escapeHtml((latestSummary && latestSummary.message) ? latestSummary.message : 'Static security analysis completed successfully with zero security findings detected.')}</p>
        </div>
      `;
      return;
    }

    const filtered = severityFilter === 'ALL' 
      ? allFindings 
      : allFindings.filter(f => f.severity.toUpperCase() === severityFilter);

    if (filtered.length === 0) {
      findingsContainer.innerHTML = `
        <div class="list-empty">
          <strong>No matching findings</strong>
          <p>No security findings match the active severity filter (${escapeHtml(severityFilter)}).</p>
        </div>
      `;
      return;
    }

    let warningBanner = '';
    if (latestSummary && latestSummary.status === 'indexing_in_progress') {
      warningBanner = `
        <div style="padding: 10px 14px; margin-bottom: 12px; border-radius: 6px; background: rgba(234, 179, 8, 0.12); border: 1px solid rgba(234, 179, 8, 0.3); font-size: 11px; color: #eab308; display: flex; align-items: center; gap: 8px;">
          <span>⚠️</span>
          <span><strong>Indexing in progress:</strong> Partial results shown. Codebase security cannot be certified until indexing finishes.</span>
        </div>
      `;
    }

    const rowsHtml = filtered.map((f, idx) => {
      const isSelected = f.id === selectedFindingId;
      const isHigh = f.severity.toUpperCase() === 'HIGH' || f.severity.toUpperCase() === 'CRITICAL';
      const badgeClass = isHigh ? 'badge-danger' : 'badge-warning';
      const iconClass = isHigh ? 's-0' : 's-2';

      return `
        <button class="finding-row ${isSelected ? 'selected' : ''}" data-id="${escapeHtml(f.id)}">
          <span class="severity-icon ${iconClass}">!</span>
          <span>
            <strong>${escapeHtml(f.title)}</strong>
            <small><svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/></svg> ${escapeHtml(f.file_path)}:${f.line_number || 1}</small>
          </span>
          <span class="badge ${badgeClass}">${escapeHtml(f.severity.toUpperCase())}</span>
          <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m9 18 6-6-6-6"/></svg>
        </button>
      `;
    }).join('');

    findingsContainer.innerHTML = warningBanner + rowsHtml;

    findingsContainer.querySelectorAll('.finding-row').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        const f = allFindings.find(x => x.id === id);
        if (f) {
          selectedFindingId = id;
          findingsContainer.querySelectorAll('.finding-row').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          renderFindingDetail(f);
        }
      });
    });
  }

  function renderFindingDetail(f) {
    if (!detailContainer || !f) return;
    const isHigh = f.severity.toUpperCase() === 'HIGH' || f.severity.toUpperCase() === 'CRITICAL';
    const badgeClass = isHigh ? 'badge-danger' : 'badge-warning';

    // Format snippet lines
    let snippetHtml = '';
    const rawSnippet = f.snippet || f.evidence_snippet;
    if (rawSnippet) {
      const lines = rawSnippet.split('\n');
      const startLn = Math.max(1, (f.line_number || 1) - 1);
      snippetHtml = lines.map((line, idx) => {
        const ln = startLn + idx;
        const isVuln = ln === f.line_number;
        return `
          <div class="${isVuln ? 'vulnerable' : ''}">
            <span>${ln}</span>
            <code>${escapeHtml(line)}</code>
          </div>
        `;
      }).join('');
    }

    const steps = Array.isArray(f.remediation_steps) ? f.remediation_steps : [];
    const remHtml = steps.map(step => `
      <span>
        <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg>
        ${escapeHtml(step)}
      </span>
    `).join('');

    const descText = f.why_it_matters || f.description || 'Verified security issue in repository source code.';
    const remText = f.remediation || (steps.length > 0 ? '' : 'Review the affected code and remove insecure patterns.');

    detailContainer.innerHTML = `
      <div class="finding-title">
        <div>
          <span class="badge ${badgeClass}">${escapeHtml(f.severity.toUpperCase())}</span>
          <span class="badge">${escapeHtml(f.cwe || 'CWE-Unknown')}</span>
          <span class="badge">${escapeHtml(f.category || 'Security')}</span>
        </div>
        <h2>${escapeHtml(f.title)}</h2>
        <span class="citation">
          <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/></svg>
          <a href="/code_viewer?repo=${activeRepo ? activeRepo.id : ''}&file=${encodeURIComponent(f.file_path)}&start=${f.line_number || 1}&end=${(f.line_number || 1) + 2}" style="color: inherit; text-decoration: none;">
            ${escapeHtml(f.file_path)}:${f.line_number || 1}
          </a>
        </span>
      </div>

      ${snippetHtml ? `<div class="evidence-code">${snippetHtml}</div>` : ''}

      <div class="finding-section">
        <h3>Why this matters</h3>
        <p>${escapeHtml(descText)}</p>
      </div>

      <div class="finding-section">
        <h3>Recommended remediation</h3>
        <p>${escapeHtml(remText)}</p>
        ${remHtml ? `<div class="remediation">${remHtml}</div>` : ''}
      </div>

      <div class="finding-confidence">
        <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>
        <span>
          <strong>Evidence verified: ${escapeHtml((f.status || 'OPEN').toUpperCase())}</strong>
          <small>Detected from verified repository AST chunk inspection.</small>
        </span>
      </div>

      <div class="finding-actions">
        <button class="btn btn-secondary" id="btn-dismiss-finding" ${(f.status || '').toLowerCase() === 'dismissed' ? 'disabled' : ''}>Dismiss</button>
        <button class="btn btn-secondary" id="btn-ack-finding" ${(f.status || '').toLowerCase() === 'acknowledged' ? 'disabled' : ''}>Acknowledge</button>
        <button class="btn btn-primary" id="btn-review-finding" ${(f.status || '').toLowerCase() === 'reviewed' ? 'disabled' : ''}>Mark reviewed</button>
      </div>
    `;

    // Action button listeners
    const dismissBtn = document.getElementById('btn-dismiss-finding');
    const ackBtn = document.getElementById('btn-ack-finding');
    const reviewBtn = document.getElementById('btn-review-finding');

    async function handleStatusUpdate(newStatus) {
      try {
        await CodeMindAPI.updateSecurityFindingStatus(activeRepo.id, f.id, newStatus);
        f.status = newStatus;
        await loadFindings();
        await updateSecuritySidebarBadge(activeRepo.id);
      } catch (err) {
        alert(`Failed to update finding status: ${err.message}`);
      }
    }

    if (dismissBtn) dismissBtn.addEventListener('click', () => handleStatusUpdate('dismissed'));
    if (ackBtn) ackBtn.addEventListener('click', () => handleStatusUpdate('acknowledged'));
    if (reviewBtn) reviewBtn.addEventListener('click', () => handleStatusUpdate('reviewed'));
  }

  // Scan Button Interaction
  if (runScanBtn) {
    runScanBtn.addEventListener('click', async () => {
      runScanBtn.disabled = true;
      runScanBtn.innerHTML = `
        <svg class="icon animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
        <span>Scanning repository...</span>
      `;
      try {
        const summary = await CodeMindAPI.runSecurityScan(activeRepo.id, activeBranch);
        await loadFindings(summary);
        await updateSecuritySidebarBadge(activeRepo.id);
      } catch (err) {
        alert(`Scan failed: ${err.message}`);
      } finally {
        runScanBtn.disabled = false;
        runScanBtn.innerHTML = `
          <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>
          <span>Run security scan</span>
        `;
      }
    });
  }

  // Severity filter toggle
  if (filterBtn) {
    const severities = ['ALL', 'HIGH', 'MEDIUM'];
    let sevIdx = 0;
    filterBtn.addEventListener('click', () => {
      sevIdx = (sevIdx + 1) % severities.length;
      severityFilter = severities[sevIdx];
      if (filterLabel) filterLabel.textContent = severityFilter === 'ALL' ? 'All severity' : `${severityFilter} only`;
      renderFindingsList();
    });
  }

  await loadFindings();
}

// --- Documentation Explorer Hydration ---
async function hydrateDocsView() {
  const activeRepo = await getActiveRepository();
  const modulesContainer = document.getElementById('docs-modules-container');
  const sectionSubtitle = document.getElementById('docs-section-subtitle');
  const searchInput = document.getElementById('docs-search-input');
  const headerDesc = document.getElementById('docs-header-desc');

  if (!activeRepo) {
    if (modulesContainer) {
      modulesContainer.innerHTML = `
        <div class="list-empty" style="padding: 32px 16px;">
          <strong>No repository connected</strong>
          <p>Connect a repository to automatically generate architecture, API catalog, and module docs.</p>
          <a href="/repositories_modal" class="btn btn-primary" style="margin-top: 12px;">Connect repository</a>
        </div>
      `;
    }
    return;
  }

  try {
    const docs = await CodeMindAPI.getRepositoryDocs(activeRepo.id);
    if (headerDesc) headerDesc.textContent = docs.overview;
    if (sectionSubtitle) sectionSubtitle.textContent = `${activeRepo.full_name} · ${docs.total_files} indexed files · ${docs.total_symbols} symbols`;

    let allModules = docs.modules || [];

    function renderModules(filter = '') {
      if (!modulesContainer) return;
      const filtered = filter 
        ? allModules.filter(m => m.name.toLowerCase().includes(filter.toLowerCase()) || m.file_path.toLowerCase().includes(filter.toLowerCase()))
        : allModules;

      if (filtered.length === 0) {
        modulesContainer.innerHTML = `
          <div class="list-empty">
            <strong>No documentation modules found</strong>
            <p>${filter ? `No modules match "${escapeHtml(filter)}"` : 'Index this repository to generate architectural documentation.'}</p>
          </div>
        `;
        return;
      }

      modulesContainer.innerHTML = filtered.map(m => `
        <button class="support-row" onclick="window.location.href='/code_viewer?repo=${activeRepo ? activeRepo.id : ''}&file=${encodeURIComponent(m.file_path)}'">
          <span class="support-icon">
            <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5"/></svg>
          </span>
          <span>
            <strong>${escapeHtml(m.name)}</strong>
            <small>${escapeHtml(m.file_path)} · ${m.symbols_count} symbols · ${m.lines_count} lines (${escapeHtml(m.language)})</small>
          </span>
          <svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m9 18 6-6-6-6"/></svg>
        </button>
      `).join('');
    }

    renderModules();

    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        renderModules(e.target.value.trim());
      });
    }

  } catch (err) {
    if (modulesContainer) {
      modulesContainer.innerHTML = `
        <div class="list-empty" style="color: var(--status-danger);">
          <strong>Error loading documentation</strong>
          <p>${escapeHtml(err.message || 'Server error')}</p>
        </div>
      `;
    }
  }
}

// --- Workspace Settings Hydration ---
async function hydrateSettingsView() {
  const container = document.getElementById('settings-form-container');
  if (!container) return;

  const tabProfile = document.getElementById('tab-profile-settings');
  const tabAi = document.getElementById('tab-ai-settings');
  const sectionTitle = document.getElementById('settings-section-title');
  const sectionSubtitle = document.getElementById('settings-section-subtitle');

  let activeTab = 'profile';

  // Check URL hash or query param
  const urlParams = new URLSearchParams(window.location.search);
  const hash = window.location.hash.toLowerCase();
  if (urlParams.get('tab') === 'ai' || urlParams.get('tab') === 'ai-settings' || hash === '#ai-settings' || hash === '#ai') {
    activeTab = 'ai';
  }

  function updateTabUI() {
    if (activeTab === 'profile') {
      if (tabProfile) {
        tabProfile.classList.add('active');
        tabProfile.setAttribute('aria-selected', 'true');
      }
      if (tabAi) {
        tabAi.classList.remove('active');
        tabAi.setAttribute('aria-selected', 'false');
      }
      if (sectionTitle) sectionTitle.textContent = 'Profile & Preferences';
      if (sectionSubtitle) sectionSubtitle.textContent = 'Persisted in CodeMind database';
    } else {
      if (tabAi) {
        tabAi.classList.add('active');
        tabAi.setAttribute('aria-selected', 'true');
      }
      if (tabProfile) {
        tabProfile.classList.remove('active');
        tabProfile.setAttribute('aria-selected', 'false');
      }
      if (sectionTitle) sectionTitle.textContent = 'AI & Embeddings Configuration';
      if (sectionSubtitle) sectionSubtitle.textContent = 'Active runtime configuration & pgvector vector space status';
    }
  }

  // Keyboard navigation for settings tabs
  [tabProfile, tabAi].forEach((tabBtn, idx, arr) => {
    if (!tabBtn) return;
    tabBtn.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault();
        const next = arr[(idx + 1) % arr.length];
        if (next) { next.focus(); next.click(); }
      } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const prev = arr[(idx - 1 + arr.length) % arr.length];
        if (prev) { prev.focus(); prev.click(); }
      }
    });
  });

  try {
    const settings = await CodeMindAPI.getSettings();
    const user = settings.user;

    function renderActiveTab() {
      updateTabUI();

      if (activeTab === 'profile') {
        container.innerHTML = `
          <form id="settings-profile-form" style="display: flex; flex-direction: column; gap: 16px; max-width: 620px;">
            <div>
              <label for="setting-full-name" style="display: block; font-size: 11px; font-weight: 600; margin-bottom: 6px;">Full Name</label>
              <input type="text" id="setting-full-name" value="${escapeHtml(user.full_name || '')}" style="width: 100%; height: 38px; padding: 0 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;" required />
            </div>
            <div>
              <label for="setting-email" style="display: block; font-size: 11px; font-weight: 600; margin-bottom: 6px;">Email Address</label>
              <input type="email" id="setting-email" value="${escapeHtml(user.email || '')}" style="width: 100%; height: 38px; padding: 0 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; background: var(--surface-subtle); color: var(--muted); cursor: not-allowed;" disabled />
              <small style="color: var(--muted); font-size: 10px; margin-top: 4px; display: block;">Account email is managed by OAuth.</small>
            </div>
            <div>
              <label for="setting-workspace-name" style="display: block; font-size: 11px; font-weight: 600; margin-bottom: 6px;">Workspace Name</label>
              <input type="text" id="setting-workspace-name" value="${escapeHtml(user.workspace_name || '')}" style="width: 100%; height: 38px; padding: 0 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;" required />
            </div>

            <div style="margin-top: 8px; padding: 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-subtle);">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <strong style="font-size: 11px;">Active Environment Summary</strong>
                <a href="#ai-settings" id="link-switch-to-ai" style="font-size: 10.5px; color: var(--primary); text-decoration: none; font-weight: 600;">View AI details →</a>
              </div>
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 10.5px; color: var(--muted);">
                <div>Provider: <strong style="color: var(--text);">${escapeHtml(settings.ai_provider)}</strong></div>
                <div>LLM Model: <strong style="color: var(--text);">${escapeHtml(settings.llm_model)}</strong></div>
                <div>Embedding: <strong style="color: var(--text);">${escapeHtml(settings.embedding_model)}</strong></div>
                <div>Dimension: <strong style="color: var(--text);">${settings.embedding_dimension} (pgvector 0.8.7)</strong></div>
              </div>
            </div>

            <div style="display: flex; gap: 12px; align-items: center; margin-top: 10px;">
              <button type="submit" class="btn btn-primary" id="save-settings-btn" style="min-width: 120px;">Save Changes</button>
              <span id="settings-status-msg" style="font-size: 11.5px; color: var(--status-success, #10b981); display: none; font-weight: 500;">✓ Profile saved successfully!</span>
            </div>
          </form>

          <!-- Section: Session & Security -->
          <div class="session-security-card" style="max-width: 680px; margin-top: 24px;">
            <div class="session-security-header">
              <div>
                <h3 class="session-security-title">Session & Security</h3>
                <p class="session-security-subtitle">Configure session lifetime and automatic inactivity logout</p>
              </div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 12px; margin-top: 8px;">
              <div>
                <label for="setting-session-timeout" style="display: block; font-size: 11px; font-weight: 600; margin-bottom: 6px;">Automatic logout after</label>
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                  <select id="setting-session-timeout" style="height: 38px; padding: 0 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; background: #ffffff; color: var(--text); min-width: 180px;">
                    <option value="30" ${(user.session_timeout_minutes || 30) === 30 ? 'selected' : ''}>30 minutes</option>
                    <option value="60" ${(user.session_timeout_minutes) === 60 ? 'selected' : ''}>1 hour</option>
                    <option value="240" ${(user.session_timeout_minutes) === 240 ? 'selected' : ''}>4 hours</option>
                    <option value="480" ${(user.session_timeout_minutes) === 480 ? 'selected' : ''}>8 hours</option>
                  </select>
                  <button type="button" class="btn btn-primary" id="save-session-timeout-btn" style="min-width: 120px;">Save Changes</button>
                  <span id="session-timeout-status-msg" style="font-size: 11.5px; color: var(--status-success, #10b981); display: none; font-weight: 500;">✓ Timeout preference saved!</span>
                </div>
                <small style="color: var(--muted); font-size: 10px; margin-top: 6px; display: block;">Default is 30 minutes. Absolute session lifetime is enforced securely by the server.</small>
              </div>

              <!-- Active Sessions Action Row -->
              <div class="active-sessions-action-row" style="margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
                <div>
                  <strong style="font-size: 11.5px; display: block; color: var(--text);">Active Sessions</strong>
                  <small style="color: var(--muted); font-size: 10px;">Persistent session tracking across devices, browsers, and IP addresses</small>
                </div>
                <button type="button" class="btn btn-secondary" id="btn-toggle-active-sessions" onclick="openActiveSessionsModal()" aria-haspopup="dialog" aria-controls="active-sessions-modal" style="display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; padding: 6px 12px; cursor: pointer;">
                  <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>
                  <span>Active Sessions</span>
                </button>
              </div>
            </div>
          </div>
        `;

        const linkSwitch = document.getElementById('link-switch-to-ai');
        if (linkSwitch) {
          linkSwitch.onclick = (e) => {
            e.preventDefault();
            switchTab('ai');
          };
        }

        const form = document.getElementById('settings-profile-form');
        if (form) {
          form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const saveBtn = document.getElementById('save-settings-btn');
            const statusMsg = document.getElementById('settings-status-msg');
            const newName = document.getElementById('setting-full-name').value.trim();
            const newWorkspace = document.getElementById('setting-workspace-name').value.trim();

            if (!newName || !newWorkspace) {
              alert('Please provide both Full Name and Workspace Name.');
              return;
            }

            saveBtn.disabled = true;
            saveBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Saving...`;

            try {
              const updated = await CodeMindAPI.updateSettings({
                full_name: newName,
                workspace_name: newWorkspace
              });

              user.full_name = updated.user.full_name;
              user.workspace_name = updated.user.workspace_name;

              await hydrateUserProfile();
              if (statusMsg) {
                statusMsg.style.display = 'inline';
                setTimeout(() => { statusMsg.style.display = 'none'; }, 3500);
              }
            } catch (err) {
              alert(`Failed to save settings: ${err.message}`);
            } finally {
              saveBtn.disabled = false;
              saveBtn.textContent = 'Save Changes';
            }
          });
        }

        // --- Session Timeout Preference Handler ---
        const timeoutBtn = document.getElementById('save-session-timeout-btn');
        const timeoutSelect = document.getElementById('setting-session-timeout');
        const timeoutStatusMsg = document.getElementById('session-timeout-status-msg');

        if (timeoutBtn && timeoutSelect) {
          timeoutBtn.addEventListener('click', async () => {
            const chosen = parseInt(timeoutSelect.value, 10);
            timeoutBtn.disabled = true;
            timeoutBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Saving...`;

            try {
              const res = await CodeMindAPI.updateSessionTimeout(chosen);
              user.session_timeout_minutes = res.timeout_minutes;
              if (timeoutStatusMsg) {
                timeoutStatusMsg.style.display = 'inline';
                setTimeout(() => { timeoutStatusMsg.style.display = 'none'; }, 3500);
              }
              // Refresh active sessions list if modal is open to reflect updated expiration
              const sessModal = document.getElementById('active-sessions-modal');
              if (sessModal && !sessModal.classList.contains('hidden')) {
                if (typeof window.loadActiveSessions === 'function') {
                  await window.loadActiveSessions();
                }
              }
            } catch (err) {
              alert(`Failed to save session timeout: ${err.message}`);
            } finally {
              timeoutBtn.disabled = false;
              timeoutBtn.textContent = 'Save Changes';
            }
          });
        }

        // --- Active Sessions Modal Trigger, Loader & Revocation Handlers ---
        const toggleBtn = document.getElementById('btn-toggle-active-sessions');
        if (toggleBtn) {
          toggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if (typeof window.openActiveSessionsModal === 'function') {
              window.openActiveSessionsModal();
            }
          });
        }

        window.loadActiveSessions = async function loadActiveSessions() {
          const sessionsContainer = document.getElementById('active-sessions-list-container');
          const revokeOthersBtn = document.getElementById('btn-revoke-other-sessions');
          if (!sessionsContainer) return;

          sessionsContainer.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--muted); font-size: 11.5px;">Loading sessions...</div>';

          // Bind Revoke Other Sessions button once
          if (revokeOthersBtn && !revokeOthersBtn.dataset.bound) {
            revokeOthersBtn.dataset.bound = 'true';
            revokeOthersBtn.addEventListener('click', async (e) => {
              e.preventDefault();
              const confirmed = confirm('Are you sure you want to revoke all other active sessions across other devices and browsers?');
              if (!confirmed) return;

              revokeOthersBtn.disabled = true;
              revokeOthersBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Revoking...`;

              try {
                const res = await CodeMindAPI.revokeOtherSessions();
                alert(res.message || 'Other active sessions revoked successfully.');
                await window.loadActiveSessions();
              } catch (err) {
                alert(`Failed to revoke other sessions: ${err.message}`);
              } finally {
                revokeOthersBtn.disabled = false;
                revokeOthersBtn.innerHTML = `
                  <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
                  <span>Revoke other sessions</span>
                `;
              }
            });
          }

          try {
            const data = await CodeMindAPI.getSessions();
            const sessions = data.sessions || [];

            if (sessions.length === 0) {
              sessionsContainer.innerHTML = `
                <div class="list-empty" style="padding: 28px;">
                  <strong>No session history found</strong>
                  <p>Session records will appear here upon login.</p>
                </div>
              `;
              if (revokeOthersBtn) revokeOthersBtn.disabled = true;
              return;
            }

            const otherActiveCount = sessions.filter(s => s.status === 'active' && !s.is_current).length;
            if (revokeOthersBtn) {
              revokeOthersBtn.disabled = otherActiveCount === 0;
            }

            sessionsContainer.innerHTML = sessions.map(s => {
              const isCurrent = Boolean(s.is_current);
              let statusBadgeHtml = '';
              if (isCurrent) {
                statusBadgeHtml = '<span class="session-badge session-badge-current">Active — This device</span>';
              } else if (s.status === 'active') {
                statusBadgeHtml = '<span class="session-badge session-badge-active">Active</span>';
              } else if (s.status === 'expired') {
                statusBadgeHtml = '<span class="session-badge session-badge-expired">Expired</span>';
              } else if (s.status === 'logged_out') {
                statusBadgeHtml = '<span class="session-badge session-badge-revoked">Logged out</span>';
              } else {
                statusBadgeHtml = '<span class="session-badge session-badge-revoked">Revoked</span>';
              }

              let actionHtml = '';
              if (s.status === 'active') {
                if (isCurrent) {
                  actionHtml = `<span style="font-size: 10px; color: var(--primary); font-weight: 600;">Current Device</span>`;
                } else {
                  actionHtml = `<button type="button" class="btn btn-secondary btn-sm btn-revoke-session" data-session-id="${s.id}" style="color: #ef4444; border-color: rgba(239, 68, 68, 0.35);">Revoke session</button>`;
                }
              } else {
                actionHtml = `<span style="font-size: 10px; color: var(--muted);">Ended ${s.logout_at ? formatTimeAgo(s.logout_at) : ''}</span>`;
              }

              return `
                <div class="session-card-item ${isCurrent ? 'is-current' : ''}">
                  <div class="session-card-header">
                    <div class="session-device-wrap">
                      <span class="session-device-icon">
                        <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>
                      </span>
                      <div>
                        <strong class="session-device-title">${escapeHtml(s.device_label || 'Web Device')}</strong>
                        <div style="font-size: 10px; color: var(--muted); margin-top: 2px;">
                          ${escapeHtml(s.user_name || '')} (${escapeHtml(s.user_email || '')})
                        </div>
                      </div>
                    </div>
                    <div class="session-badges-wrap">
                      ${statusBadgeHtml}
                      ${actionHtml}
                    </div>
                  </div>

                  <div class="session-details-grid">
                    <div>IP address: <strong>${escapeHtml(s.ip_address || '—')}</strong></div>
                    <div>Login time: <strong>${formatDateTime(s.login_at)}</strong></div>
                    <div>Last activity: <strong>${formatDateTime(s.last_activity_at)}</strong></div>
                    <div>Expires at: <strong>${formatDateTime(s.expires_at)}</strong></div>
                    <div>Last accessed page: <strong><code>${escapeHtml(s.last_accessed_path || '/dashboard')}</code></strong></div>
                    <div>Browser: <strong>${escapeHtml(s.browser || '—')}</strong></div>
                    <div>Operating system: <strong>${escapeHtml(s.os || '—')}</strong></div>
                    <div>Ended: <strong>${s.logout_at ? formatDateTime(s.logout_at) : '—'}</strong></div>
                  </div>
                </div>
              `;
            }).join('');

            // Attach event listeners to individual revoke buttons
            const revokeBtns = sessionsContainer.querySelectorAll('.btn-revoke-session');
            revokeBtns.forEach(btn => {
              btn.addEventListener('click', async (e) => {
                e.preventDefault();
                const sid = btn.dataset.sessionId;
                if (!sid) return;

                const confirmed = confirm('Are you sure you want to revoke this session? The device will immediately lose access and be signed out.');
                if (!confirmed) return;

                btn.disabled = true;
                btn.textContent = 'Revoking...';
                try {
                  const res = await CodeMindAPI.revokeSession(sid);
                  if (res && res.is_current) {
                    localStorage.removeItem('codemind_auth_token');
                    sessionStorage.clear();
                    window.location.href = '/login?expired=true';
                  } else {
                    await window.loadActiveSessions();
                  }
                } catch (err) {
                  alert(`Failed to revoke session: ${err.message}`);
                  btn.disabled = false;
                  btn.textContent = 'Revoke session';
                }
              });
            });

          } catch (err) {
            sessionsContainer.innerHTML = `
              <div class="list-empty" style="color: var(--status-danger);">
                <strong>Error loading active sessions</strong>
                <p>${escapeHtml(err.message || 'Server error')}</p>
              </div>
            `;
          }
        };

        // Active Sessions modal is closed by default and opened on-demand via openActiveSessionsModal()

      } else {
        // AI & Embeddings tab
        container.innerHTML = `
          <div style="display: flex; flex-direction: column; gap: 18px; max-width: 680px;">
            <!-- Card 1: Runtime AI & Models Configuration -->
            <div class="settings-card">
              <div class="settings-card-header">
                <div>
                  <strong style="font-size: 12px; display: block;">Local AI & Inference Engine</strong>
                  <small style="color: var(--muted); font-size: 10.5px;">Configured in backend/.env · Ollama Local Inference</small>
                </div>
                <span class="settings-badge badge-ready" id="ai-conn-badge">
                  <span class="status-dot" style="width: 6px; height: 6px;"></span>
                  ${escapeHtml(settings.ai_provider).toUpperCase()} Active
                </span>
              </div>

              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 10px; font-size: 11px;">
                <div style="padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-subtle);">
                  <span style="color: var(--muted); font-size: 10px; display: block; margin-bottom: 2px;">AI PROVIDER</span>
                  <strong style="font-size: 12px; color: var(--text);">${escapeHtml(settings.ai_provider)}</strong>
                  <span style="display: block; color: var(--muted); font-size: 9.5px; margin-top: 2px;">Local REST API (port 11434)</span>
                </div>

                <div style="padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-subtle);">
                  <span style="color: var(--muted); font-size: 10px; display: block; margin-bottom: 2px;">LLM MODEL</span>
                  <strong style="font-size: 12px; color: var(--text);">${escapeHtml(settings.llm_model)}</strong>
                  <span style="display: block; color: var(--muted); font-size: 9.5px; margin-top: 2px;">3B parameter quantized instruct</span>
                </div>

                <div style="padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-subtle);">
                  <span style="color: var(--muted); font-size: 10px; display: block; margin-bottom: 2px;">EMBEDDING MODEL</span>
                  <strong style="font-size: 12px; color: var(--text);">${escapeHtml(settings.embedding_model)}</strong>
                  <span style="display: block; color: var(--muted); font-size: 9.5px; margin-top: 2px;">Dense code representation</span>
                </div>

                <div style="padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-subtle);">
                  <span style="color: var(--muted); font-size: 10px; display: block; margin-bottom: 2px;">VECTOR DIMENSION</span>
                  <strong style="font-size: 12px; color: var(--text);">${settings.embedding_dimension} dimensions</strong>
                  <span style="display: block; color: var(--muted); font-size: 9.5px; margin-top: 2px;">PostgreSQL pgvector 0.8.7</span>
                </div>
              </div>

              <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div style="font-size: 10px; color: var(--muted);">
                  Model selection is managed via environment variables to guarantee inference reproducibility.
                </div>
                <button type="button" class="btn btn-secondary btn-sm" id="btn-test-ai-connectivity">
                  <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                  <span>Test AI Connectivity</span>
                </button>
              </div>
              <div id="ai-test-result-box" style="margin-top: 10px; font-size: 11px; display: none;"></div>
            </div>

            <!-- Card 2: Embedding Compatibility Notice -->
            <div class="settings-card" style="border-left: 4px solid #6366f1;">
              <div style="display: flex; gap: 10px; align-items: flex-start;">
                <svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4f46e5" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                <div>
                  <strong style="font-size: 11.5px; color: #1e1b4b; display: block; margin-bottom: 4px;">Embedding Compatibility & pgvector Vector Space</strong>
                  <p style="font-size: 10.5px; line-height: 1.5; color: #4338ca; margin: 0 0 8px;">
                    All code chunks, AST symbols, and repository knowledge graphs are indexed in PostgreSQL using <strong>${settings.embedding_dimension}-dimensional vectors</strong> via the <code>${escapeHtml(settings.embedding_model)}</code> model.
                  </p>
                  <p style="font-size: 10px; line-height: 1.45; color: #6366f1; margin: 0;">
                    • <strong>Re-indexing Notice:</strong> If the embedding model or dimension is modified in <code>backend/.env</code>, all repositories must be re-indexed to rebuild compatible vector embeddings. Existing embeddings are preserved safely and are not invalidated merely by visiting settings.
                  </p>
                </div>
              </div>
            </div>

            <!-- Card 3: GitHub & Integrations -->
            <div class="settings-card">
              <strong style="font-size: 12px; display: block; margin-bottom: 10px;">Connected Developer Services</strong>
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 11px;">
                <div style="padding: 10px; border: 1px solid var(--border); border-radius: 6px;">
                  <span style="color: var(--muted); font-size: 10px; display: block;">GITHUB OAUTH APP</span>
                  <strong style="color: ${settings.github_configured ? 'var(--status-success, #10b981)' : 'var(--status-warning, #f59e0b)'}; font-size: 11.5px;">
                    ${settings.github_configured ? '✓ Configured' : '⚠ Not Configured'}
                  </strong>
                </div>
                <div style="padding: 10px; border: 1px solid var(--border); border-radius: 6px;">
                  <span style="color: var(--muted); font-size: 10px; display: block;">USER CONNECTION</span>
                  <strong style="color: var(--text); font-size: 11.5px;">
                    ${escapeHtml(settings.github_username || 'Not connected')}
                  </strong>
                </div>
              </div>
            </div>
          </div>
        `;

        // Connectivity Test Button Handler
        const testBtn = document.getElementById('btn-test-ai-connectivity');
        const resultBox = document.getElementById('ai-test-result-box');
        if (testBtn) {
          testBtn.onclick = async () => {
            testBtn.disabled = true;
            testBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Testing engine...`;
            if (resultBox) {
              resultBox.style.display = 'block';
              resultBox.innerHTML = `<div style="padding: 8px 12px; background: var(--surface-subtle); border-radius: 6px; color: var(--muted);">Checking Ollama models and pgvector readiness...</div>`;
            }

            try {
              const ready = await CodeMindAPI.getReady();
              if (ready && ready.status === 'ready') {
                resultBox.innerHTML = `
                  <div style="padding: 10px 12px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 6px; color: #065f46;">
                    <strong>✓ AI & Database Operational</strong>
                    <div style="font-size: 10px; margin-top: 4px;">
                      Database: ${escapeHtml(ready.dialect || 'PostgreSQL')} (pgvector ready) ·
                      LLM: ${ready.llm_model_available ? 'Available' : 'Online'} ·
                      Embedding: ${ready.embedding_model_available ? 'Available' : 'Online'}
                    </div>
                  </div>
                `;
              } else {
                resultBox.innerHTML = `
                  <div style="padding: 10px 12px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; color: #92400e;">
                    <strong>⚠ Service Partially Available:</strong> ${escapeHtml(ready.detail || 'Service reporting degraded state.')}
                  </div>
                `;
              }
            } catch (err) {
              resultBox.innerHTML = `
                <div style="padding: 10px 12px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; color: #991b1b;">
                  <strong>✕ AI Connectivity Error:</strong> ${escapeHtml(err.message || 'Could not reach local AI service.')}
                </div>
              `;
            } finally {
              testBtn.disabled = false;
              testBtn.innerHTML = `<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg> <span>Test AI Connectivity</span>`;
            }
          };
        }
      }
    }

    function switchTab(newTab) {
      activeTab = newTab;
      window.location.hash = newTab === 'ai' ? 'ai-settings' : 'profile';
      renderActiveTab();
    }

    if (tabProfile) {
      tabProfile.onclick = (e) => {
        e.preventDefault();
        switchTab('profile');
      };
    }

    if (tabAi) {
      tabAi.onclick = (e) => {
        e.preventDefault();
        switchTab('ai');
      };
    }

    // Initial render
    renderActiveTab();

  } catch (err) {
    container.innerHTML = `
      <div class="list-empty" style="color: var(--status-danger);">
        <strong>Error loading settings</strong>
        <p>${escapeHtml(err.message || 'Server error')}</p>
      </div>
    `;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatNumber(num) {
  if (num === 0) return '0';
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'k';
  return num.toLocaleString();
}

function formatTimeAgo(isoDate) {
  if (!isoDate) return 'Never';
  const diff = Date.now() - new Date(isoDate).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatDateTime(isoDate) {
  if (!isoDate) return '—';
  try {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return isoDate;
    return d.toLocaleString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
  } catch (e) {
    return isoDate;
  }
}

window.CodeMindAPI = CodeMindAPI;
