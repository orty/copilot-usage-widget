'use strict';

/**
 * Authentication for the Copilot widget.
 *
 * The upstream Claude widget captures a `sessionKey` cookie from an embedded login
 * BrowserWindow. GitHub instead uses a real bearer token, so we offer two paths that
 * mirror the same two-step UX (auto-detect, then manual paste):
 *
 *   1. detectToken()  — runs `gh auth token` (GitHub CLI). If the user is logged in
 *                       to the CLI, we lift their token transparently.
 *   2. manual paste   — the user pastes a GitHub token; we validate it against the API.
 *
 * Device-flow OAuth is intentionally omitted: it requires shipping a registered
 * OAuth client_id, which an unsigned open-source build can't keep secret.
 */

const { execFile } = require('child_process');
const { fetchUsage } = require('./copilot-api');

/**
 * Try to read a token from the GitHub CLI (`gh auth token`).
 * @returns {Promise<string|null>} the token, or null if gh is missing / not logged in.
 */
function detectToken() {
  return new Promise((resolve) => {
    execFile('gh', ['auth', 'token'], { timeout: 10000 }, (err, stdout) => {
      if (err) return resolve(null);
      const token = (stdout || '').trim();
      resolve(token || null);
    });
  });
}

/**
 * Validate a token by attempting a real usage fetch.
 * @returns {Promise<{ valid: boolean, error?: string }>}
 */
async function validateToken(token) {
  if (!token || !token.trim()) return { valid: false, error: 'Empty token' };
  try {
    await fetchUsage(token.trim());
    return { valid: true };
  } catch (err) {
    return { valid: false, error: err.message };
  }
}

module.exports = { detectToken, validateToken };
