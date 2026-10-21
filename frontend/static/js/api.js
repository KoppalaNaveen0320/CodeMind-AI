/**
 * CodeMind AI - Centralized Frontend API Client
 * Connects UI views to backend REST endpoints and manages dynamic state.
 */

const CodeMindAPI = {
  baseUrl: '',

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    try {
      const response = await fetch(url, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          ...options.headers,
        },
        ...options,
      });

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

  // User Profile
  async getCurrentUser() {
    try {
      return await this.request('/api/v1/auth/me');
    } catch (e) {
      return await this.request('/api/v1/me');
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
    const url = repositoryId ? `/api/v1/dashboard/overview?repository_id=${repositoryId}` : '/api/v1/dashboard/overview';
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

  async getAssistantConversations({ repositoryId = null, search = null, limit = 50, offset = 0 } = {}) {
    let url = `/api/v1/assistant/conversations?limit=${limit}&offset=${offset}`;
    if (repositoryId) url += `&repository_id=${repositoryId}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    return this.request(url);
  },

  async createAssistantConversation({ title = null, repositoryId = null, branch = null } = {}) {
    return this.request('/api/v1/assistant/conversations', {
      method: 'POST',
      body: JSON.stringify({ title, repository_id: repositoryId, branch })
    });
  },

  async getAssistantConversation(conversationId) {
    return this.request(`/api/v1/assistant/conversations/${conversationId}`);
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
    const onMeta = isCallbackFn ? (d) => callbacks('meta', d) : callbacks.onMeta;
    const onStatus = isCallbackFn ? (d) => callbacks('status', d) : callbacks.onStatus;
    const onCitation = isCallbackFn ? (d) => callbacks('citation', d) : callbacks.onCitation;
    const onToken = isCallbackFn ? (d) => callbacks('token', d) : callbacks.onToken;
    const onDone = isCallbackFn ? (d) => callbacks('done', d) : callbacks.onDone;
    const onError = isCallbackFn ? (d) => callbacks('error', d) : callbacks.onError;
    const onGeneral = isCallbackFn ? callbacks : callbacks.onEvent;

    const res = await fetch(url, {
      ...options,
      signal: options.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      }
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
      if (onError) onError({ error: 'HTTP Error', detail: errDetail, status: 'failed' });
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

        for (let i = 0; i < lines.length; i++) {
          const line = lines[i].trim();
          if (!line) {
            currentEvent = 'message';
            continue;
          }
          if (line.startsWith('event:')) {
            currentEvent = line.substring(6).trim();
          } else if (line.startsWith('data:')) {
            const dataStr = line.substring(5).trim();
            try {
              const data = JSON.parse(dataStr);
              if (onGeneral) onGeneral(currentEvent, data);
              if (currentEvent === 'meta' && onMeta) onMeta(data);
              else if (currentEvent === 'status' && onStatus) onStatus(data);
              else if (currentEvent === 'citation' && onCitation) onCitation(data);
              else if (currentEvent === 'token' && onToken) onToken(data);
              else if (currentEvent === 'done' && onDone) onDone(data);
              else if (currentEvent === 'error' && onError) onError(data);
              else if (onToken && data.token) onToken(data);
            } catch (jsonErr) {
              // ignore partial json
            }
          }
        }
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
  async getSecurityFindings(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}/security/findings`);
  },

  async runSecurityScan(repositoryId) {
    return this.request(`/api/v1/repositories/${repositoryId}/security/scan`, { method: 'POST' });
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
        quickSecuritySub.textContent = 'All security checks passed';
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
  const isDocs = path.includes('docs') || document.getElementById('view-docs');
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
            <a href="/docs" class="btn btn-secondary">
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

function renderRepositoriesTable(repos) {
  const container = document.getElementById('repositories-container') || document.querySelector('.table-card');
  if (!container) return;

  const headHtml = `
    <section class="card table-card" id="repo-table-card">
      <div class="table-head">
        <span>Repository</span>
        <span>Language</span>
        <span>Status</span>
        <span>Files & Symbols</span>
        <span style="text-align: right;">Actions</span>
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

      const langDotClass = idx % 3 === 0 ? 'lang-0' : idx % 3 === 1 ? 'lang-1' : 'lang-2';

      return `
        <div class="table-row" data-repo-id="${repo.id}" data-repo-name="${escapeHtml((repo.name || '').toLowerCase())}" data-repo-full="${escapeHtml((repo.full_name || '').toLowerCase())}" data-repo-status="${escapeHtml((repo.status || 'pending').toLowerCase())}" data-repo-lang="${escapeHtml((repo.primary_language || '').toLowerCase())}">
          <span>
            <a href="/dashboard?repo=${repo.id}" class="repo-title-link" onclick="localStorage.setItem('codemind_active_repo_id', ${repo.id})" style="display:inline-flex; align-items:center; gap:9px; text-decoration:none; color:inherit;" title="Open dashboard for ${escapeHtml(repo.name || '')}">
              <span class="repo-logo small">
                <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>
                </svg>
              </span>
              <span>
                <strong>${escapeHtml(repo.full_name || repo.name)}</strong>
                <small>${escapeHtml(repo.default_branch || 'main')} · ${repo.is_private ? 'Private' : 'Public'} · GitHub</small>
              </span>
            </a>
          </span>
          <span><i class="lang-dot ${langDotClass}"></i>${escapeHtml(repo.primary_language || 'Polyglot')}</span>
          <span>${statusBadge}</span>
          <span>${formatNumber(repo.files_count || 0)} files · ${formatNumber(repo.symbols_count || 0)} symbols</span>
          <span class="repo-actions-cell">
            <button type="button" class="btn btn-ghost" onclick="triggerRepoIndex(${repo.id}, '${escapeHtml(repo.name || '')}')" title="Index or re-index">Index</button>
            <a href="/dashboard?repo=${repo.id}" class="btn btn-ghost" onclick="localStorage.setItem('codemind_active_repo_id', ${repo.id})" title="View Dashboard Overview">Overview</a>
            <a href="/git_history?repo=${repo.id}" class="btn btn-ghost" title="Browse commits">Browse</a>
            <a href="/code_viewer?repo=${repo.id}" class="btn btn-ghost" title="Explore code">Explore</a>
            <button type="button" class="btn btn-ghost" onclick="deleteRepo(${repo.id}, '${escapeHtml(repo.full_name || repo.name || '')}', this)" style="color: var(--danger);" title="Disconnect repository">Disconnect</button>
          </span>
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
    const nameMatch = !query ||
      (repo.name && repo.name.toLowerCase().includes(query)) ||
      (repo.full_name && repo.full_name.toLowerCase().includes(query)) ||
      (repo.default_branch && repo.default_branch.toLowerCase().includes(query)) ||
      (repo.primary_language && repo.primary_language.toLowerCase().includes(query));

    const statusMatch = selectedStatus === 'all' || (repo.status || 'pending').toLowerCase() === selectedStatus;
    return nameMatch && statusMatch;
  });

  renderRepositoriesTable(filtered);
}

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
      <p style="margin-top: 8px; font-size: 11px;">Checking connection status...</p>
    </div>
  `;

  try {
    cachedAuthStatus = await CodeMindAPI.getGitHubAuthStatus();
  } catch (e) {
    cachedAuthStatus = { configured: false, connected: false };
  }

  let oauthSectionHtml = '';
  if (cachedAuthStatus && cachedAuthStatus.connected) {
    oauthSectionHtml = `
      <div class="auth-card" style="margin-top: 14px;">
        <div class="auth-status-row">
          <div>
            <span class="badge badge-success" style="margin-bottom: 4px;">Connected</span>
            <div style="font-size: 12px; font-weight: 600; color: var(--text);">GitHub Account: @${escapeHtml(cachedAuthStatus.username || 'user')}</div>
          </div>
          <button type="button" class="btn btn-secondary btn-sm" id="btn-disconnect-gh" style="color: var(--danger);">Disconnect</button>
        </div>
      </div>
      <button type="button" class="btn btn-secondary full-btn" id="btn-proceed-select" style="margin-top: 8px;">
        <span>Browse Authorized Private/Org Repositories →</span>
      </button>
    `;
  } else if (cachedAuthStatus && cachedAuthStatus.configured) {
    oauthSectionHtml = `
      <div style="margin-top: 16px; padding: 12px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius);">
        <strong style="font-size: 11.5px; display: block; margin-bottom: 4px;">Private & Organization Repositories</strong>
        <p style="font-size: 11px; color: var(--muted); margin: 0 0 10px;">Authorize CodeMind to access your private repositories with secure server-side token storage.</p>
        <button type="button" class="btn btn-secondary full-btn" id="btn-start-oauth">
          <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
            <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>
            <path d="M9 18c-4.51 2-5-2-7-2"/>
          </svg>
          <span>Authorize GitHub OAuth</span>
        </button>
      </div>
    `;
  } else {
    oauthSectionHtml = `
      <div style="margin-top: 16px; padding: 10px 12px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius); font-size: 11px; color: var(--muted);">
        <div style="display: flex; gap: 8px; align-items: flex-start;">
          <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="color: var(--muted); flex-shrink: 0; margin-top: 1px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <div>
            <strong style="color: var(--text); font-size: 11px;">GitHub OAuth Unconfigured</strong>
            <p style="margin: 2px 0 0; color: var(--muted); font-size: 10.5px;">To enable private repository OAuth, set <code>GITHUB_CLIENT_ID</code> and <code>GITHUB_CLIENT_SECRET</code> in <code>backend/.env</code>. Public repositories and folder uploads work directly without credentials.</p>
          </div>
        </div>
      </div>
    `;
  }

  body.innerHTML = `
    <!-- Method A: Public GitHub Repository -->
    <div>
      <h2 style="font-size: 13.5px; font-weight: 600; margin-bottom: 4px;">Connect a Public GitHub Repository</h2>
      <p style="font-size: 11px; color: var(--muted); margin-bottom: 10px;">
        Accepts repository paths (e.g. <code>pallets/flask</code>) or full URLs (e.g. <code>https://github.com/fastapi/fastapi</code>).
      </p>

      <div id="public-repo-error" class="inline-error" style="display: none; color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; padding: 8px 12px; border-radius: 6px; font-size: 11px; margin-bottom: 10px;"></div>

      <form id="form-direct-repo" class="direct-connect-form" style="display: flex; flex-direction: column; gap: 8px;">
        <div>
          <label for="input-direct-repo" style="display: block; font-size: 11px; font-weight: 600; margin-bottom: 5px; color: var(--text);">Repository URL or Path</label>
          <div style="display: flex; gap: 8px;">
            <input type="text" id="input-direct-repo" placeholder="owner/repo or https://github.com/owner/repo" required style="flex: 1;" autocomplete="off" spellcheck="false" />
            <button type="submit" class="btn btn-primary" id="btn-direct-submit" style="white-space: nowrap;">Connect & Index</button>
          </div>
        </div>
      </form>
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

    <!-- Method B: GitHub OAuth -->
    <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border);">
      ${oauthSectionHtml}
    </div>
  `;

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

  const disconnectGhBtn = document.getElementById('btn-disconnect-gh');
  if (disconnectGhBtn) {
    disconnectGhBtn.addEventListener('click', async () => {
      if (!confirm('Disconnect your GitHub account? Any existing indexed repositories in CodeMind will remain safe.')) return;
      try {
        await CodeMindAPI.disconnectGitHub();
        renderModalStep1();
      } catch (err) {
        alert(`Failed to disconnect: ${err.message}`);
      }
    });
  }

  const directForm = document.getElementById('form-direct-repo');
  if (directForm) {
    directForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = document.getElementById('input-direct-repo');
      const submitBtn = document.getElementById('btn-direct-submit');
      const errBox = document.getElementById('public-repo-error');
      if (errBox) errBox.style.display = 'none';

      const fullRepo = (input ? input.value : '').trim();
      if (!fullRepo) {
        if (errBox) {
          errBox.textContent = 'Please enter a repository path (e.g. pallets/flask) or full GitHub URL.';
          errBox.style.display = 'block';
        }
        if (input) input.focus();
        return;
      }

      // Check format
      const isUrl = fullRepo.startsWith('http://') || fullRepo.startsWith('https://');
      const isPath = fullRepo.includes('/') && !fullRepo.includes(' ') && fullRepo.split('/').filter(Boolean).length >= 2;
      if (!isUrl && !isPath) {
        if (errBox) {
          errBox.textContent = 'Invalid format. Please enter "owner/repo" or a full GitHub URL (e.g. "pallets/flask").';
          errBox.style.display = 'block';
        }
        if (input) input.focus();
        return;
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<svg class="icon animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Connecting...`;

      try {
        const repo = await CodeMindAPI.connectPublicRepository(fullRepo, true);
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

async function renderModalStep2() {
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
    const ghRepos = await CodeMindAPI.getGitHubRepositories();

    if (!ghRepos || ghRepos.length === 0) {
      body.innerHTML = `
        <div class="empty-state" style="padding: 24px; text-align: center;">
          <h3>No Repositories Found</h3>
          <p style="color: var(--muted); font-size: 11px; margin: 8px 0 16px;">We could not find any accessible repositories on your GitHub account.</p>
          <button type="button" class="btn btn-secondary" onclick="renderModalStep1()">Back to Step 1</button>
        </div>
      `;
      return;
    }

    body.innerHTML = `
      <h2>Select a repository</h2>
      <p>Choose an accessible repository to register and index with CodeMind AI.</p>
      
      <div class="modal-search">
        <svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
        <input type="text" id="modal-repo-search-input" placeholder="Search your repositories..." />
      </div>

      <div id="modal-repo-options-list" style="max-height: 280px; overflow-y: auto; margin-bottom: 16px;">
        ${ghRepos.map((repo, idx) => `
          <div class="repo-option ${idx === 0 ? 'selected' : ''}" data-full-name="${escapeHtml(repo.full_name)}" data-name="${escapeHtml(repo.name)}" data-branch="${escapeHtml(repo.default_branch || 'main')}" data-private="${repo.is_private}" data-lang="${escapeHtml(repo.primary_language || '')}" data-id="${repo.id}">
            <span class="radio-dot"></span>
            <span class="repo-logo small"><svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg></span>
            <span>
              <strong>${escapeHtml(repo.full_name)}</strong>
              <small>${escapeHtml(repo.default_branch || 'main')} · ${repo.is_private ? 'Private' : 'Public'} · ${escapeHtml(repo.primary_language || 'Polyglot')}</small>
            </span>
            ${repo.is_connected ? '<span class="badge badge-neutral">Already Connected</span>' : ''}
          </div>
        `).join('')}
      </div>

      <div class="modal-actions" style="justify-content: space-between;">
        <button type="button" class="btn btn-secondary" onclick="renderModalStep1()">Back</button>
        <button type="button" class="btn btn-primary" id="btn-modal-confirm-select">Continue to Indexing →</button>
      </div>
    `;

    selectedGitHubRepo = ghRepos[0];
    const options = body.querySelectorAll('.repo-option');
    options.forEach(opt => {
      opt.addEventListener('click', () => {
        options.forEach(o => o.classList.remove('selected'));
        opt.classList.add('selected');
        const fullName = opt.getAttribute('data-full-name');
        selectedGitHubRepo = ghRepos.find(r => r.full_name === fullName) || {
          name: opt.getAttribute('data-name'),
          full_name: fullName,
          default_branch: opt.getAttribute('data-branch'),
          is_private: opt.getAttribute('data-private') === 'true',
          primary_language: opt.getAttribute('data-lang'),
          id: parseInt(opt.getAttribute('data-id'))
        };
      });
    });

    const searchInput = document.getElementById('modal-repo-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        const q = searchInput.value.trim().toLowerCase();
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
            github_repo_id: selectedGitHubRepo.id
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
      <div class="empty-state" style="padding: 24px; text-align: center;">
        <h3 style="color: var(--danger);">Failed to Fetch Repositories</h3>
        <p style="color: var(--muted); font-size: 11px; margin: 8px 0 16px;">${escapeHtml(err.message || 'Error communicating with GitHub API.')}</p>
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
    const commitsContainer = document.getElementById('dashboard-recent-commits');
    const questionsContainer = document.getElementById('dashboard-recent-questions');
    const greetingHeader = document.querySelector('.page-header h1');
    const lastIndexedBtn = document.querySelector('.header-actions .btn-secondary span');
    const askCodeMindBtn = document.querySelector('.header-actions .btn-primary');

    // 1. Immediately clear stale data and show loading indicators
    metricValues.forEach(el => { el.textContent = '—'; });

    if (activeRepo) {
      if (topbarRepo) topbarRepo.textContent = activeRepo.name;
      if (topbarBranch) topbarBranch.textContent = activeRepo.default_branch || 'main';
      if (bannerRepo) bannerRepo.textContent = activeRepo.full_name;
      if (bannerDesc) bannerDesc.textContent = `${activeRepo.description || 'Repository'} · ${activeRepo.primary_language || 'Polyglot'}`;
      if (healthText) healthText.textContent = 'Loading repository metrics...';
      if (healthSub) healthSub.textContent = `Fetching indexed status on ${activeRepo.default_branch || 'main'}`;
      if (healthDot) healthDot.className = 'status-dot';
      if (askCodeMindBtn) askCodeMindBtn.href = `/assistant?repo=${activeRepo.id}`;
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
    }

    // Fetch repository dashboard overview
    const data = await CodeMindAPI.getDashboardOverview(activeRepo ? activeRepo.id : null);
    
    // Prevent slower responses from a previous repository selection from overwriting the latest selection
    if (requestId !== currentDashboardRequestId) {
      return;
    }
    if (!data) return;

    if (greetingHeader && data.greeting) {
      greetingHeader.textContent = data.greeting;
    }

    if (data.active_repository) {
      const repo = data.active_repository;
      if (topbarRepo) topbarRepo.textContent = repo.name;
      if (topbarBranch) topbarBranch.textContent = repo.default_branch || 'main';
      if (bannerRepo) bannerRepo.textContent = repo.full_name;
      if (bannerDesc) bannerDesc.textContent = `${repo.description || 'Repository'} · ${repo.primary_language || 'Polyglot'}`;

      const isReady = repo.status === 'ready';
      const isIndexing = repo.status === 'indexing';
      const isFailed = repo.status === 'failed';
      const isPending = repo.status === 'pending';

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
        metricValues[0].textContent = formatNumber(data.files_indexed || 0);
        metricValues[1].textContent = formatNumber(data.functions_classes || 0);
        metricValues[2].textContent = formatNumber(data.apis_detected || 0);
        metricValues[3].textContent = formatNumber(data.dependencies_mapped || 0);
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

      // Hydrate Recent Commits for the selected repository
      if (commitsContainer) {
        try {
          const commitsRes = await CodeMindAPI.getCommits(repo.id, { perPage: 3 });
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
                <a href="/git_history?repo=${repo.id}&sha=${encodeURIComponent(c.commit_sha || c.sha || '')}" class="commit-row" title="${fullMsg}">
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
          commitsContainer.innerHTML = `
            <div style="padding: 24px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem;">
              Could not load commits (${escapeHtml(e.message)}).
            </div>
          `;
        }
      }

      // Hydrate Architecture Overview for the selected repository
      if (archContainer) {
        try {
          const graphRes = await CodeMindAPI.getRepositoryGraph(repo.id, 12);
          if (requestId !== currentDashboardRequestId) return;
          if (graphRes && graphRes.nodes && graphRes.nodes.length > 0) {
            const displayNodes = graphRes.nodes.slice(0, 6);
            archContainer.innerHTML = `
              <div class="architecture-grid">
                ${displayNodes.map(n => {
                  const nodeType = (n.node_type || 'Component').toLowerCase();
                  const typeBadgeClass = nodeType === 'class' ? 'badge-primary' :
                                         nodeType === 'function' ? 'badge-info' :
                                         nodeType === 'service' ? 'badge-warning' : 'badge-neutral';
                  const fullName = escapeHtml(n.name || 'Component');
                  const fullPath = escapeHtml(n.file_path || 'AST Symbol');
                  return `
                    <a href="/dependencies?repo=${repo.id}&node=${encodeURIComponent(n.name)}" class="arch-card-item" title="${fullName} (${fullPath})">
                      <div class="arch-card-header">
                        <span class="badge ${typeBadgeClass}" style="font-size: 0.68rem; text-transform: uppercase;">${escapeHtml(n.node_type || 'Component')}</span>
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
                  <a href="/dependencies?repo=${repo.id}" style="font-size: 0.78rem; font-weight: 600; color: var(--primary); text-decoration: none;">
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
          archContainer.innerHTML = `
            <div style="padding: 28px 16px; text-align: center; color: var(--text-muted); font-size: 0.82rem; width: 100%;">
              Architecture overview available after indexing.
            </div>
          `;
        }
      }
    } else {
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
    }

    if (questionsContainer) {
      if (!data.recent_questions || data.recent_questions.length === 0) {
        const repoParam = activeRepo ? `?repo=${activeRepo.id}` : '';
        questionsContainer.innerHTML = `
          <div class="empty-state" style="padding: 18px 12px; text-align: center;">
            <p class="empty-state-desc" style="margin: 0 0 10px; font-size: 0.82rem; color: var(--text-muted);">No AI questions asked yet for this repository.</p>
            <a href="/assistant${repoParam}" class="btn btn-secondary btn-sm" style="text-decoration:none;"><span>Ask your first question</span></a>
          </div>
        `;
      } else {
        questionsContainer.innerHTML = data.recent_questions.map(q => `
          <a href="/assistant?conversation_id=${encodeURIComponent(q.conversation_id)}" class="activity-item" style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; border-bottom:1px solid var(--border); text-decoration:none; color:inherit; border-radius:6px; transition:background 0.2s;" onmouseover="this.style.background='var(--surface-subtle, rgba(255,255,255,0.03))'" onmouseout="this.style.background='transparent'">
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
      window.history.pushState({}, '', url);
      await hydrateDashboardView(target.id);
    } else {
      const url = new URL(window.location);
      url.searchParams.set('repo', target.id);
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
    if (/^<(h[1-4]|ul|ol|blockquote|div|hr|table)/i.test(trimmed) || /^@@CM_CODE_BLOCK_\d+@@$/.test(trimmed)) {
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

  // 16. Final safety sweep: strip any orphan placeholders before content reaches visible DOM
  text = text.replace(/@@CM_[A-Za-z0-9_]+@@/g, '');

  return text;
}

async function hydrateAssistantView() {
  let activeRepo = await getActiveRepository();
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

  // --- Open Conversation ---
  async function openConversation(convId) {
    if (currentStreamAbortController) {
      currentStreamAbortController.abort();
      currentStreamAbortController = null;
    }
    isSending = false;
    activeLoadingConvId = convId;
    currentConversationId = convId;
    sessionStorage.setItem('codemind_active_conversation_id', String(convId));

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

    // Hide empty starter prompt
    const emptyPrompt = document.getElementById('assistant-empty-prompt');
    if (emptyPrompt) emptyPrompt.style.display = 'none';

    // Reset center panel scroll position immediately when switching conversations
    if (messagesContainer) messagesContainer.scrollTop = 0;

    // Show loading in messages container
    messagesContainer.innerHTML = `
      <div style="padding: 40px; text-align: center; color: var(--muted);">
        <svg class="icon animate-spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="margin-bottom:8px;" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
        <p style="font-size:12px;">Loading conversation history...</p>
      </div>
    `;

    try {
      const conv = await CodeMindAPI.getAssistantConversation(convId);
      if (activeLoadingConvId !== convId) return;

      if (conv.repository_id) {
        if (!activeRepo || activeRepo.id !== conv.repository_id) {
          activeRepo = allLoadedRepos.find(r => r.id === conv.repository_id) || {
            id: conv.repository_id,
            name: conv.repository_name,
            default_branch: conv.branch || 'main'
          };
          localStorage.setItem('codemind_active_repo_id', String(conv.repository_id));
        }
      }

      if (titleEl) titleEl.textContent = conv.title || 'AI Code Assistant';
      updateHeaderContext(conv.repository_name, conv.branch);

      messagesContainer.innerHTML = '';

      if (!conv.messages || conv.messages.length === 0) {
        if (emptyPrompt) {
          messagesContainer.appendChild(emptyPrompt);
          emptyPrompt.style.display = 'block';
        }
        return;
      }

      let lastCitations = [];

      conv.messages.forEach(msg => {
        if (msg.role === 'user') {
          const userHtml = `
            <div class="user-message">
              <span class="avatar">You</span>
              <div>
                <span>You</span>
                <p>${escapeHtml(msg.content)}</p>
              </div>
            </div>
          `;
          messagesContainer.insertAdjacentHTML('beforeend', userHtml);
        } else if (msg.role === 'assistant') {
          const isFailed = msg.status === 'failed';
          const citations = msg.citations || [];
          if (citations.length > 0) lastCitations = citations;

          let citationsBadge = citations.length > 0
            ? `<span class="badge badge-success"><svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg> <span class="badge-text">${citations.length} sources verified</span></span>`
            : `<span class="badge badge-neutral">No source matches</span>`;

          if (isFailed) {
            citationsBadge = `<span class="badge badge-danger">Generation Error</span>`;
          }

          let metadata = msg.evidence_metadata || {};
          let relatedHtml = '';
          if (metadata.related_components && metadata.related_components.length > 0) {
            relatedHtml = `
              <div style="margin-top:14px;">
                <h3 style="font-size:11.5px; margin:0 0 6px;">Related components</h3>
                <div class="related-grid">
                  ${metadata.related_components.map(c => `
                    <a href="/code_viewer?file=${encodeURIComponent(c.file_path || '')}" style="text-decoration:none;">
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
          if (isFailed) {
            retryHtml = `
              <div style="margin-top:10px;">
                <button type="button" class="btn btn-secondary btn-sm retry-msg-btn">
                  <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                  <span>Retry response</span>
                </button>
              </div>
            `;
          }

          const renderedLead = renderMarkdown(msg.content, citations);

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
      window.history.pushState({}, '', url);

    } catch (err) {
      if (activeLoadingConvId !== convId) return;
      messagesContainer.innerHTML = `
        <div class="assistant-error">
          <svg class="icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
          <h2>Unable to open conversation</h2>
          <p>${escapeHtml(err.message || 'Conversation could not be loaded.')}</p>
          <div>
            <button type="button" class="btn btn-secondary" onclick="window.location.reload()">Reload</button>
            <button type="button" class="btn btn-primary" id="error-new-conv">Start new conversation</button>
          </div>
        </div>
      `;
      const errNewBtn = document.getElementById('error-new-conv');
      if (errNewBtn) errNewBtn.addEventListener('click', startNewConversation);
    }
  }

  // --- Start New Conversation ---
  async function startNewConversation() {
    if (currentStreamAbortController) {
      currentStreamAbortController.abort();
      currentStreamAbortController = null;
    }
    isSending = false;
    currentConversationId = null;
    sessionStorage.removeItem('codemind_active_conversation_id');
    activeRepo = await getActiveRepository();
    if (titleEl) titleEl.textContent = 'AI Code Assistant';
    updateHeaderContext(activeRepo ? activeRepo.name : null, activeRepo ? activeRepo.default_branch : 'main');

    messagesContainer.innerHTML = '';
    const emptyPrompt = document.getElementById('assistant-empty-prompt');
    if (emptyPrompt) {
      messagesContainer.appendChild(emptyPrompt);
      emptyPrompt.style.display = 'block';
    }

    populateEvidencePanel([], activeRepo);

    // Unselect sidebar items
    if (historyListEl) {
      historyListEl.querySelectorAll('.history-item').forEach(el => el.classList.remove('active'));
    }

    // Clean URL
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

    // Create streaming AI message container
    const aiMsgId = 'ai-stream-' + Date.now();
    const aiMsgHtml = `
      <div class="ai-message" id="${aiMsgId}">
        <div class="ai-message-head">
          <span class="ai-orb">
            <svg class="icon animate-spin" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>
          </span>
          <div class="ai-title-wrap">
            <strong class="brand-title">CodeMind</strong>
            <span class="badge badge-neutral stream-status-badge"><span class="badge-text">Retrieving evidence & reasoning...</span></span>
          </div>
        </div>
        <div class="answer">
          <div class="answer-lead markdown-body live-token-body"></div>
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
    const statusBadge = aiMsgEl ? aiMsgEl.querySelector('.stream-status-badge') : null;
    const statusBadgeText = statusBadge ? statusBadge.querySelector('.badge-text') : null;

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
          currentStreamAbortController.abort();
        }
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
          if (data.conversation_id && !currentConversationId) {
            currentConversationId = data.conversation_id;
            requestConvId = currentConversationId;
            sessionStorage.setItem('codemind_active_conversation_id', String(currentConversationId));
            const url = new URL(window.location);
            url.searchParams.set('conversation_id', currentConversationId);
            window.history.pushState({}, '', url);
          }
        } else if (event === 'status') {
          if (statusBadgeText) {
            statusBadgeText.textContent = data.message || 'Thinking...';
          }
        } else if (event === 'citation') {
          if (Array.isArray(data.citations) && data.citations.length > 0) {
            streamCitations = data.citations;
            populateEvidencePanel(streamCitations, activeRepo);
            if (statusBadge) {
              statusBadge.className = 'badge badge-success stream-status-badge';
              statusBadge.innerHTML = `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg> <span class="badge-text">${streamCitations.length} sources verified</span>`;
            }
          }
        } else if (event === 'token') {
          accumulatedTokens += data.token || '';
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
          const finalAnswer = data.answer || accumulatedTokens;
          const finalCitations = data.citations || streamCitations;
          if (liveTokenBody) {
            liveTokenBody.innerHTML = renderMarkdown(finalAnswer, finalCitations);
          }

          // Convert orb back to normal
          const orb = aiMsgEl ? aiMsgEl.querySelector('.ai-orb') : null;
          if (orb) {
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
          if (factsEl) {
            factsEl.style.display = 'flex';
            factsEl.innerHTML = `
              <span><i class="fact-dot confirmed"></i>Confirmed facts <b>${data.facts?.confirmed || 0}</b></span>
              <span><i class="fact-dot inference"></i>Inferences <b>${data.facts?.inferences || 0}</b></span>
              <span><i class="fact-dot unknown"></i>Unknowns <b>${data.facts?.unknowns || 0}</b></span>
            `;
          }

          // Related components
          if (data.related_components && data.related_components.length > 0) {
            const relContainer = aiMsgEl ? aiMsgEl.querySelector('.related-container') : null;
            if (relContainer) {
              relContainer.innerHTML = `
                <div style="margin-top:14px;">
                  <h3 style="font-size:11.5px; margin:0 0 6px;">Related components</h3>
                  <div class="related-grid">
                    ${data.related_components.map(c => `
                      <a href="/code_viewer?file=${encodeURIComponent(c.file_path || '')}" style="text-decoration:none;">
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
          if (data.risk_callout && data.risk_callout.summary) {
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
          if (aiMsgEl) aiMsgEl.classList.add('ai-failed');
          if (statusBadge) {
            statusBadge.className = 'badge badge-danger';
            statusBadge.innerHTML = `<span class="badge-text">Generation Error</span>`;
          }
          if (liveTokenBody) {
            liveTokenBody.innerHTML = `
              <p style="color:var(--status-danger);"><strong>Error querying assistant:</strong> ${escapeHtml(data.message || 'Server error')}</p>
              <div style="margin-top:8px;">
                <button type="button" class="btn btn-secondary btn-sm retry-btn-action">
                  <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                  <span>Retry</span>
                </button>
              </div>
            `;
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
      if (isAborted) {
        // User cancelled or switched conversation - NEVER show an error banner
        if (aiMsgEl && document.body.contains(aiMsgEl)) {
          const orb = aiMsgEl.querySelector('.ai-orb');
          if (orb) {
            orb.innerHTML = `<svg class="icon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m12 3-1.7 4.3L6 9l4.3 1.7L12 15l1.7-4.3L18 9l-4.3-1.7L12 3Z"/></svg>`;
          }
          if (statusBadge) {
            statusBadge.className = 'badge badge-neutral stream-status-badge';
            statusBadge.innerHTML = `<span class="badge-text">Generation stopped</span>`;
          }
          if (liveTokenBody) {
            if (accumulatedTokens && accumulatedTokens.trim()) {
              liveTokenBody.innerHTML = renderMarkdown(accumulatedTokens, streamCitations) + `
                <div class="generation-stopped-notice" style="margin-top:10px; display:inline-flex; align-items:center; gap:6px; font-size:11.5px; color:var(--text-muted); padding:4px 8px; background:var(--surface-subtle); border-radius:4px; border:1px solid var(--border);">
                  <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true" focusable="false"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
                  <span>Generation stopped</span>
                </div>
              `;
            } else {
              liveTokenBody.innerHTML = `
                <div class="generation-stopped-notice" style="display:inline-flex; align-items:center; gap:6px; font-size:11.5px; color:var(--text-muted); padding:4px 8px; background:var(--surface-subtle); border-radius:4px; border:1px solid var(--border);">
                  <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true" focusable="false"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
                  <span>Generation stopped</span>
                </div>
              `;
            }
          }
        }
        return;
      }

      if (requestConvId !== null && currentConversationId !== requestConvId) {
        return;
      }

      if (aiMsgEl) aiMsgEl.classList.add('ai-failed');
      if (liveTokenBody) {
        liveTokenBody.innerHTML = `
          <p style="color:var(--status-danger);"><strong>Error querying assistant:</strong> ${escapeHtml(err.message || 'Server error')}</p>
          <div style="margin-top:8px;">
            <button type="button" class="btn btn-secondary btn-sm retry-btn-action">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
              <span>Retry</span>
            </button>
          </div>
        `;
      }
    } finally {
      isSending = false;
      currentStreamAbortController = null;
      window.currentStreamAbortController = null;
      if (stopBtn) stopBtn.style.display = 'none';
      if (sendBtn) {
        sendBtn.style.display = 'grid';
        sendBtn.disabled = !textarea?.value?.trim();
      }
      if (textarea) {
        textarea.disabled = false;
        textarea.focus();
      }
    }
  }

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
      if (!isNaN(parsedStored) && conversationsCache.some(c => c.id === parsedStored)) {
        openConversation(parsedStored);
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
        return `
          <a class="cm-palette-item ${isSelected ? 'selected' : ''}" data-index="${idx}" href="/code_viewer?file=${encodeURIComponent(sym.file_path)}&start=${sym.start_line}&end=${sym.end_line}">
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
            window.location.href = `/code_viewer?file=${encodeURIComponent(item.file_path)}&start=${item.start_line}&end=${item.end_line}`;
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
          window.location.href = `/code_viewer?file=${encodeURIComponent(item.file_path)}&start=${item.start_line}&end=${item.end_line}`;
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
          <button class="citation" onclick="window.location.href='/code_viewer?file=${encodeURIComponent(s.file_path || '')}'">
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

  let allFindings = [];
  let selectedFindingId = null;
  let severityFilter = 'ALL';

  async function loadFindings() {
    if (findingsContainer) {
      findingsContainer.innerHTML = `
        <div class="list-empty">
          <strong>Scanning security findings...</strong>
          <p>Querying verified static security analysis.</p>
        </div>
      `;
    }

    try {
      const summary = await CodeMindAPI.getSecurityFindings(activeRepo.id);
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
          detailContainer.innerHTML = `
            <div style="padding: 36px; text-align: center; color: var(--muted); font-size: 11px;">
              No security findings detected for this repository.
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
    const filtered = severityFilter === 'ALL' 
      ? allFindings 
      : allFindings.filter(f => f.severity.toUpperCase() === severityFilter);

    if (filtered.length === 0) {
      findingsContainer.innerHTML = `
        <div class="list-empty">
          <strong>No open findings</strong>
          <p>No security findings match the active severity filter (${escapeHtml(severityFilter)}).</p>
        </div>
      `;
      return;
    }

    findingsContainer.innerHTML = filtered.map((f, idx) => {
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
          <a href="/code_viewer?file=${encodeURIComponent(f.file_path)}&start=${f.line_number || 1}&end=${(f.line_number || 1) + 2}" style="color: inherit; text-decoration: none;">
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
        await CodeMindAPI.runSecurityScan(activeRepo.id);
        await loadFindings();
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
        <button class="support-row" onclick="window.location.href='/code_viewer?file=${encodeURIComponent(m.file_path)}'">
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

window.CodeMindAPI = CodeMindAPI;
