/**
 * Roblox account connect UI for Lunix's AI Trade Assistant.
 * Talks to auth_server.py when authApiBase is set in auth_public.json.
 */
(function () {
  const ACCOUNT_KEY = 'lunix_roblox_account_v1';
  const TOKEN_KEY = 'lunix_roblox_session_v1';
  const CONFIG_URL = 'auth_public.json';

  /** @type {{ authApiBase?: string, enableUsernameLink?: boolean }} */
  let config = { authApiBase: '', enableUsernameLink: true };
  /** @type {null | { id: number|string, username: string, displayName: string, picture?: string, profile?: string, authMethod?: string }} */
  let account = null;
  let token = null;
  let oauthReady = false;

  function $(id) {
    return document.getElementById(id);
  }

  function loadLocal() {
    try {
      const raw = localStorage.getItem(ACCOUNT_KEY);
      account = raw ? JSON.parse(raw) : null;
      token = localStorage.getItem(TOKEN_KEY);
    } catch (_) {
      account = null;
      token = null;
    }
  }

  function saveLocal() {
    try {
      if (account) localStorage.setItem(ACCOUNT_KEY, JSON.stringify(account));
      else localStorage.removeItem(ACCOUNT_KEY);
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (_) {}
  }

  function apiBase() {
    return String(config.authApiBase || '').replace(/\/$/, '');
  }

  function avatarUrl(user) {
    if (user && user.picture) return user.picture;
    if (user && user.id != null) {
      return (
        'https://www.roblox.com/headshot-thumbnail/image?userId=' +
        encodeURIComponent(String(user.id)) +
        '&width=150&height=150&format=png'
      );
    }
    return '';
  }

  function emitChange() {
    try {
      window.dispatchEvent(
        new CustomEvent('lunix-account-changed', {
          detail: { account: account ? { ...account } : null },
        })
      );
    } catch (_) {}
    if (typeof window.LunixOnAccountChange === 'function') {
      try {
        window.LunixOnAccountChange(account ? { ...account } : null);
      } catch (_) {}
    }
  }

  function setAccount(next, nextToken) {
    const prevId = account && account.id;
    account = next;
    token = nextToken || null;
    saveLocal();
    renderChip();
    if ((account && account.id) !== prevId) emitChange();
  }

  async function probeLocalAuth() {
    try {
      const ctrl = typeof AbortSignal !== 'undefined' && AbortSignal.timeout
        ? AbortSignal.timeout(900)
        : undefined;
      const res = await fetch('http://127.0.0.1:8787/health', {
        cache: 'no-store',
        signal: ctrl,
      });
      if (res.ok) return 'http://127.0.0.1:8787';
    } catch (_) {}
    return '';
  }

  async function fetchConfig() {
    try {
      const res = await fetch(CONFIG_URL, { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        if (data && typeof data === 'object') config = { ...config, ...data };
      }
    } catch (_) {}

    if (!apiBase()) {
      const local = await probeLocalAuth();
      if (local) config.authApiBase = local;
    }

    const base = apiBase();
    if (!base) {
      oauthReady = false;
      return;
    }
    try {
      const res = await fetch(base + '/api/config', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        oauthReady = !!data.oauthReady;
        if (data.usernameLink === false) config.enableUsernameLink = false;
      }
    } catch (_) {
      oauthReady = false;
    }
  }

  async function refreshSession() {
    const base = apiBase();
    if (!base || !token) return;
    try {
      const res = await fetch(base + '/api/me', {
        headers: { Authorization: 'Bearer ' + token },
        cache: 'no-store',
      });
      if (!res.ok) {
        if (res.status === 401) setAccount(null, null);
        return;
      }
      const data = await res.json();
      if (data && data.user) setAccount(data.user, token);
    } catch (_) {}
  }

  function consumeHashToken() {
    const hash = (location.hash || '').replace(/^#/, '');
    if (!hash) return;
    const params = new URLSearchParams(hash);
    const t = params.get('roblox_token');
    const err = params.get('roblox_error');
    if (!t && !err) return;
    // Clear sensitive hash from the address bar
    history.replaceState(null, '', location.pathname + location.search);
    if (err) {
      showStatus(err, true);
      openModal();
      return;
    }
    if (t) {
      token = t;
      saveLocal();
      refreshSession().then(() => {
        if (account) showStatus('Signed in as ' + (account.displayName || account.username));
      });
    }
  }

  function renderChip() {
    const root = $('robloxAccount');
    if (!root) return;
    if (account && account.id != null) {
      const name = account.displayName || account.username || 'Player';
      const handle = account.username ? '@' + account.username : '';
      const img = avatarUrl(account);
      root.innerHTML =
        '<button type="button" class="rbx-chip" id="rbxChipBtn" title="Roblox account">' +
        (img
          ? '<img class="rbx-avatar" src="' +
            img.replace(/"/g, '') +
            '" alt="" width="28" height="28" />'
          : '<span class="rbx-avatar rbx-avatar-fallback" aria-hidden="true"></span>') +
        '<span class="rbx-meta"><span class="rbx-name"></span><span class="rbx-handle"></span></span>' +
        '</button>';
      const nameEl = root.querySelector('.rbx-name');
      const handleEl = root.querySelector('.rbx-handle');
      if (nameEl) nameEl.textContent = name;
      if (handleEl) handleEl.textContent = handle;
      const btn = $('rbxChipBtn');
      if (btn) btn.addEventListener('click', openModal);
    } else {
      root.innerHTML =
        '<button type="button" class="rbx-login-btn" id="rbxLoginBtn">Connect Roblox</button>';
      const btn = $('rbxLoginBtn');
      if (btn) btn.addEventListener('click', openModal);
    }
  }

  function showStatus(msg, isError) {
    const el = $('rbxStatus');
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || '';
    el.classList.toggle('error', !!isError);
  }

  function openModal() {
    const modal = $('rbxModal');
    if (!modal) return;
    modal.hidden = false;
    showStatus('');
    updateModalBody();
    const input = $('rbxUsername');
    if (input) setTimeout(() => input.focus(), 50);
  }

  function closeModal() {
    const modal = $('rbxModal');
    if (modal) modal.hidden = true;
  }

  function updateModalBody() {
    const signed = $('rbxSignedIn');
    const guest = $('rbxGuest');
    const oauthBtn = $('rbxOAuthBtn');
    const userForm = $('rbxUserForm');
    const setup = $('rbxSetupHint');
    const base = apiBase();

    if (signed) signed.hidden = !(account && account.id != null);
    if (guest) guest.hidden = !!(account && account.id != null);

    if (account && account.id != null && signed) {
      const img = signed.querySelector('.rbx-modal-avatar');
      const name = signed.querySelector('.rbx-modal-name');
      const handle = signed.querySelector('.rbx-modal-handle');
      const method = signed.querySelector('.rbx-modal-method');
      if (img) {
        const url = avatarUrl(account);
        img.hidden = !url;
        if (url) img.src = url;
      }
      if (name) name.textContent = account.displayName || account.username || '';
      if (handle) handle.textContent = account.username ? '@' + account.username : '';
      if (method) {
        method.textContent =
          account.authMethod === 'oauth'
            ? 'Signed in with Roblox OAuth'
            : 'Linked by username';
      }
      const link = $('rbxProfileLink');
      if (link) {
        if (account.profile) {
          link.href = account.profile;
          link.hidden = false;
        } else {
          link.hidden = true;
        }
      }
    }

    if (oauthBtn) {
      oauthBtn.hidden = !base || !oauthReady;
      oauthBtn.disabled = !base || !oauthReady;
    }
    if (userForm) {
      const allow = config.enableUsernameLink !== false;
      userForm.hidden = !allow;
    }
    if (setup) {
      setup.hidden = !!base;
    }
  }

  function startOAuth() {
    const base = apiBase();
    if (!base) {
      showStatus('Auth server URL is not configured (auth_public.json).', true);
      return;
    }
    window.location.href = base + '/auth/login';
  }

  async function linkUsername(ev) {
    if (ev) ev.preventDefault();
    const input = $('rbxUsername');
    const username = (input && input.value ? input.value : '').trim();
    if (!username) {
      showStatus('Enter your Roblox username.', true);
      return;
    }
    const base = apiBase();
    if (!base) {
      showStatus(
        'Start auth_server.py and set authApiBase in auth_public.json to link an account.',
        true
      );
      return;
    }
    const btn = $('rbxLinkBtn');
    if (btn) btn.disabled = true;
    showStatus('Looking up ' + username + '…');
    try {
      const res = await fetch(base + '/api/resolve-user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Lookup failed');
      setAccount(data.user, data.token);
      showStatus('Connected as ' + (data.user.displayName || data.user.username));
      updateModalBody();
      setTimeout(closeModal, 600);
    } catch (e) {
      showStatus(e && e.message ? e.message : String(e), true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function disconnect() {
    const base = apiBase();
    if (base && token) {
      try {
        await fetch(base + '/api/logout', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token },
        });
      } catch (_) {}
    }
    setAccount(null, null);
    updateModalBody();
    showStatus('Disconnected');
    setTimeout(closeModal, 400);
  }

  function ensureStyles() {
    if ($('rbxAccountStyles')) return;
    const style = document.createElement('style');
    style.id = 'rbxAccountStyles';
    style.textContent = `
      .rbx-account-slot { display:flex; align-items:center; }
      .rbx-login-btn, .rbx-chip {
        display:inline-flex; align-items:center; gap:8px;
        border:1px solid var(--line-strong, #3b3352);
        background: var(--card, #12101a);
        color: var(--text, #f4efff);
        border-radius: 999px;
        padding: 7px 12px;
        font: inherit; font-size: 13px; font-weight: 600;
        cursor: pointer;
        box-shadow: var(--shadow, none);
      }
      .rbx-login-btn:hover, .rbx-chip:hover {
        border-color: var(--purple, #a855f7);
      }
      .rbx-login-btn {
        background: linear-gradient(135deg, rgba(var(--purple-rgb,168,85,247),0.25), rgba(0,0,0,0.2));
      }
      .rbx-avatar {
        width:28px; height:28px; border-radius:50%; object-fit:cover;
        background:#2a2438;
      }
      .rbx-avatar-fallback {
        display:inline-block; background:#3b3352;
      }
      .rbx-meta { display:flex; flex-direction:column; align-items:flex-start; line-height:1.15; }
      .rbx-name { font-size:12px; font-weight:700; }
      .rbx-handle { font-size:10px; color: var(--muted, #9a90b3); font-weight:500; }
      .rbx-modal {
        position:fixed; inset:0; z-index:80;
        display:flex; align-items:center; justify-content:center;
        padding:20px; background:rgba(4,3,10,0.72);
        backdrop-filter: blur(6px);
      }
      .rbx-modal[hidden] { display:none !important; }
      .rbx-dialog {
        width:min(420px, 100%);
        background: var(--card, #12101a);
        border:1px solid var(--line-strong, #3b3352);
        border-radius:18px;
        padding:20px 20px 16px;
        box-shadow: 0 24px 60px rgba(0,0,0,0.45);
        color: var(--text, #f4efff);
      }
      .rbx-dialog h2 {
        margin:0 0 6px; font-size:18px; font-weight:800;
        font-family: Syne, Outfit, sans-serif;
      }
      .rbx-dialog p.rbx-lead {
        margin:0 0 16px; color: var(--muted, #9a90b3); font-size:13px; line-height:1.4;
      }
      .rbx-actions { display:flex; flex-direction:column; gap:10px; }
      .rbx-actions button.primary, .rbx-dialog button.primary {
        border:0; border-radius:12px; padding:11px 14px;
        font:inherit; font-weight:700; cursor:pointer;
        color:#fff; background: var(--purple, #a855f7);
      }
      .rbx-actions button.primary:disabled { opacity:0.45; cursor:not-allowed; }
      .rbx-actions button.ghost, .rbx-dialog button.ghost {
        border:1px solid var(--line-strong, #3b3352);
        background:transparent; color:var(--text,#f4efff);
        border-radius:12px; padding:10px 14px;
        font:inherit; font-weight:600; cursor:pointer;
      }
      .rbx-divider {
        display:flex; align-items:center; gap:10px;
        color: var(--muted,#9a90b3); font-size:11px; text-transform:uppercase;
        letter-spacing:0.06em; margin:4px 0;
      }
      .rbx-divider::before, .rbx-divider::after {
        content:""; flex:1; height:1px; background: var(--line, #2a2438);
      }
      .rbx-user-row { display:flex; gap:8px; }
      .rbx-user-row input {
        flex:1; border:1px solid var(--line-strong,#3b3352); border-radius:12px;
        padding:10px 12px; background:#0c0a12; color:var(--text,#f4efff);
        font:inherit; font-size:14px;
      }
      .rbx-user-row input:focus {
        outline:none; border-color: var(--purple,#a855f7);
      }
      .rbx-status {
        margin:12px 0 0; font-size:12px; color: var(--muted,#9a90b3); min-height:1.2em;
      }
      .rbx-status.error { color:#fb7185; }
      .rbx-setup {
        margin-top:12px; padding:10px 12px; border-radius:12px;
        background:rgba(168,85,247,0.08); border:1px solid var(--line,#2a2438);
        font-size:12px; color:var(--muted,#9a90b3); line-height:1.45;
      }
      .rbx-setup code {
        font-size:11px; color:var(--purple-bright,#c084fc);
      }
      .rbx-signed {
        display:flex; gap:12px; align-items:center; margin-bottom:14px;
      }
      .rbx-modal-avatar {
        width:56px; height:56px; border-radius:50%; object-fit:cover; background:#2a2438;
      }
      .rbx-modal-name { font-weight:800; font-size:16px; }
      .rbx-modal-handle { color:var(--muted,#9a90b3); font-size:12px; }
      .rbx-modal-method { color:var(--muted,#9a90b3); font-size:11px; margin-top:4px; }
      .rbx-modal-close {
        position:absolute; top:10px; right:12px;
        border:0; background:transparent; color:var(--muted,#9a90b3);
        font-size:20px; cursor:pointer; line-height:1;
      }
      .rbx-dialog-wrap { position:relative; }
      @media (max-width: 720px) {
        .wrap-head .rbx-account-slot { order: 3; width:100%; justify-content:center; }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureDom() {
    ensureStyles();
    let slot = $('robloxAccount');
    if (!slot) {
      const head = document.querySelector('.wrap-head');
      slot = document.createElement('div');
      slot.id = 'robloxAccount';
      slot.className = 'rbx-account-slot';
      if (head) head.appendChild(slot);
      else document.body.prepend(slot);
    }

    if (!$('rbxModal')) {
      const modal = document.createElement('div');
      modal.id = 'rbxModal';
      modal.className = 'rbx-modal';
      modal.hidden = true;
      modal.innerHTML = `
        <div class="rbx-dialog-wrap">
          <div class="rbx-dialog" role="dialog" aria-modal="true" aria-labelledby="rbxModalTitle">
            <button type="button" class="rbx-modal-close" id="rbxCloseBtn" aria-label="Close">×</button>
            <h2 id="rbxModalTitle">Roblox account</h2>
            <p class="rbx-lead">Connect your Roblox account so this calculator remembers you on this device.</p>

            <div id="rbxSignedIn" hidden>
              <div class="rbx-signed">
                <img class="rbx-modal-avatar" alt="" width="56" height="56" />
                <div>
                  <div class="rbx-modal-name"></div>
                  <div class="rbx-modal-handle"></div>
                  <div class="rbx-modal-method"></div>
                </div>
              </div>
              <div class="rbx-actions">
                <a class="ghost" id="rbxProfileLink" href="#" target="_blank" rel="noopener" style="text-align:center;text-decoration:none;display:block;border:1px solid var(--line-strong);border-radius:12px;padding:10px 14px;font-weight:600;color:inherit;">Open Roblox profile</a>
                <button type="button" class="ghost" id="rbxDisconnectBtn">Disconnect</button>
              </div>
            </div>

            <div id="rbxGuest">
              <div class="rbx-actions">
                <button type="button" class="primary" id="rbxOAuthBtn" hidden>Sign in with Roblox</button>
                <div class="rbx-divider" id="rbxDivider">or</div>
                <form id="rbxUserForm">
                  <div class="rbx-user-row">
                    <input id="rbxUsername" type="text" maxlength="20" placeholder="Roblox username" autocomplete="username" />
                    <button type="submit" class="primary" id="rbxLinkBtn">Link</button>
                  </div>
                </form>
              </div>
              <div class="rbx-setup" id="rbxSetupHint" hidden>
                To enable connecting on this site, run <code>python auth_server.py</code>
                and set <code>authApiBase</code> in <code>auth_public.json</code> to that server’s URL.
                For full Roblox OAuth, add your app credentials to <code>.env</code> (see <code>.env.example</code>).
              </div>
            </div>
            <p class="rbx-status" id="rbxStatus" hidden></p>
          </div>
        </div>
      `;
      document.body.appendChild(modal);

      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
      });
      $('rbxCloseBtn').addEventListener('click', closeModal);
      $('rbxOAuthBtn').addEventListener('click', startOAuth);
      $('rbxUserForm').addEventListener('submit', linkUsername);
      $('rbxDisconnectBtn').addEventListener('click', disconnect);
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !$('rbxModal').hidden) closeModal();
      });
    }

    // Keep profile link fresh
    const observer = () => {
      const link = $('rbxProfileLink');
      if (link && account && account.profile) {
        link.href = account.profile;
        link.hidden = false;
      } else if (link) {
        link.hidden = true;
      }
    };
    const _set = setAccount;
    // wrap after definition — update profile link on render instead
    const prevRender = renderChip;
    // no-op; updateModalBody handles profile link
    void prevRender;
    void observer;
  }

  async function init() {
    ensureDom();
    loadLocal();
    renderChip();
    await fetchConfig();
    consumeHashToken();
    await refreshSession();
    renderChip();
    updateModalBody();
    // profile link
    const link = $('rbxProfileLink');
    if (link) {
      if (account && account.profile) {
        link.href = account.profile;
        link.hidden = false;
      }
    }
    window.LunixRoblox = {
      getAccount: () => (account ? { ...account } : null),
      getToken: () => token,
      open: openModal,
      disconnect,
      refresh: refreshSession,
    };
    emitChange();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
