/**
 * Browser Roblox OAuth (PKCE) — no local auth server required.
 * Shared by roblox_account.js and oauth_callback.html.
 */
(function (global) {
  const ACCOUNT_KEY = 'lunix_roblox_account_v1';
  const ACCESS_KEY = 'lunix_roblox_access_v1';
  const PKCE_KEY = 'lunix_roblox_pkce_v1';
  const CONFIG_URL = 'auth_public.json';

  const AUTHORIZE_URL = 'https://apis.roblox.com/oauth/v1/authorize';
  const TOKEN_URL = 'https://apis.roblox.com/oauth/v1/token';
  const USERINFO_URL = 'https://apis.roblox.com/oauth/v1/userinfo';

  function b64url(buf) {
    const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : buf;
    let str = '';
    for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
    return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  function randomVerifier() {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    return b64url(bytes);
  }

  async function challengeFromVerifier(verifier) {
    const hash = await crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(verifier)
    );
    return b64url(hash);
  }

  async function loadConfig() {
    const defaults = {
      clientId: '',
      redirectUri: '',
      scopes: 'openid profile',
      authApiBase: '',
      enableUsernameLink: true,
    };
    try {
      const res = await fetch(CONFIG_URL, { cache: 'no-store' });
      if (!res.ok) return defaults;
      const data = await res.json();
      return { ...defaults, ...(data && typeof data === 'object' ? data : {}) };
    } catch (_) {
      return defaults;
    }
  }

  function defaultRedirectUri() {
    try {
      return new URL('oauth_callback.html', window.location.href).toString();
    } catch (_) {
      return 'https://lunixical-hash.github.io/trade-calculator/oauth_callback.html';
    }
  }

  function resolveRedirectUri(config) {
    return String(config.redirectUri || '').trim() || defaultRedirectUri();
  }

  function readAccount() {
    try {
      const raw = localStorage.getItem(ACCOUNT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function writeAccount(user, accessToken) {
    if (user) localStorage.setItem(ACCOUNT_KEY, JSON.stringify(user));
    else localStorage.removeItem(ACCOUNT_KEY);
    if (accessToken) localStorage.setItem(ACCESS_KEY, accessToken);
    else localStorage.removeItem(ACCESS_KEY);
  }

  function clearAccount() {
    localStorage.removeItem(ACCOUNT_KEY);
    localStorage.removeItem(ACCESS_KEY);
    // legacy key from auth_server sessions
    localStorage.removeItem('lunix_roblox_session_v1');
  }

  async function beginLogin(config) {
    const clientId = String(config.clientId || '').trim();
    if (!clientId) {
      throw new Error(
        'Roblox OAuth Client ID is not configured yet. The site owner must add it once in auth_public.json.'
      );
    }
    const verifier = randomVerifier();
    const challenge = await challengeFromVerifier(verifier);
    const state = randomVerifier();
    const redirectUri = resolveRedirectUri(config);
    sessionStorage.setItem(
      PKCE_KEY,
      JSON.stringify({
        verifier,
        state,
        redirectUri,
        clientId,
        returnTo: new URL('trade_calculator.html', window.location.href).toString(),
      })
    );
    // Do not send `prompt`. Specifying only select_account/login causes
    // "Consent prompt is required" / "Account selection prompt is required"
    // for third-party apps. Omitting it lets Roblox show the required screens.
    const qs = new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      scope: String(config.scopes || 'openid profile'),
      response_type: 'code',
      state,
      code_challenge: challenge,
      code_challenge_method: 'S256',
    });
    window.location.href = AUTHORIZE_URL + '?' + qs.toString();
  }

  async function exchangeCode(code, pkce) {
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: pkce.redirectUri,
      client_id: pkce.clientId,
      code_verifier: pkce.verifier,
    });
    const res = await fetch(TOKEN_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Accept: 'application/json',
      },
      body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(
        data.error_description || data.error || 'Token exchange failed (' + res.status + ')'
      );
    }
    if (!data.access_token) throw new Error('No access_token returned by Roblox');
    return data;
  }

  async function fetchUserInfo(accessToken) {
    const res = await fetch(USERINFO_URL, {
      headers: {
        Authorization: 'Bearer ' + accessToken,
        Accept: 'application/json',
      },
    });
    const info = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(
        info.error_description || info.error || 'userinfo failed (' + res.status + ')'
      );
    }
    if (!info.sub) throw new Error('Roblox userinfo missing sub');
    const userId = String(info.sub);
    const username = String(
      info.preferred_username || info.nickname || info.name || userId
    );
    const displayName = String(info.name || info.nickname || username);
    return {
      id: /^\d+$/.test(userId) ? Number(userId) : userId,
      username,
      displayName,
      profile:
        info.profile || 'https://www.roblox.com/users/' + userId + '/profile',
      picture:
        info.picture ||
        'https://www.roblox.com/headshot-thumbnail/image?userId=' +
          encodeURIComponent(userId) +
          '&width=150&height=150&format=png',
      authMethod: 'oauth',
    };
  }

  async function finishLoginFromRedirect() {
    const params = new URLSearchParams(window.location.search);
    const err = params.get('error');
    if (err) {
      throw new Error(params.get('error_description') || err);
    }
    const code = params.get('code');
    const state = params.get('state');
    if (!code) throw new Error('Missing OAuth code from Roblox');

    const raw = sessionStorage.getItem(PKCE_KEY);
    if (!raw) throw new Error('Login session expired — start Sign in again');
    const pkce = JSON.parse(raw);
    if (!pkce || pkce.state !== state) {
      throw new Error('OAuth state mismatch — try Sign in again');
    }

    const tokens = await exchangeCode(code, pkce);
    const user = await fetchUserInfo(tokens.access_token);
    writeAccount(user, tokens.access_token);
    sessionStorage.removeItem(PKCE_KEY);
    return { user, returnTo: pkce.returnTo || 'trade_calculator.html' };
  }

  global.LunixRobloxOAuth = {
    ACCOUNT_KEY,
    ACCESS_KEY,
    loadConfig,
    resolveRedirectUri,
    defaultRedirectUri,
    readAccount,
    writeAccount,
    clearAccount,
    beginLogin,
    finishLoginFromRedirect,
    fetchUserInfo,
  };
})(window);
