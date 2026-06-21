'use strict';

/**
 * Copilot usage data layer.
 *
 * GitHub exposes the signed-in user's Copilot quota at a real authenticated REST
 * endpoint, so — unlike the upstream Claude widget which had to scrape through a
 * hidden Cloudflare-gated BrowserWindow — we just do a plain HTTPS GET from the
 * main process with the user's token.
 *
 *   GET https://api.github.com/copilot_internal/user
 *   Authorization: Bearer <token>
 *   Accept: application/json
 *
 * Response shape:
 *   {
 *     "quota_snapshots": {
 *       "premium_interactions": {
 *         "unlimited": false, "percent_remaining": 42.0,
 *         "entitlement": 300, "remaining": 126,
 *         "overage_count": 0, "overage_permitted": false
 *       }, ...
 *     },
 *     "quota_reset_date_utc": "2026-07-01T00:00:00.000Z"
 *   }
 */

const https = require('https');

const API_HOST = 'api.github.com';
const API_PATH = '/copilot_internal/user';

const LABELS = {
  premium_interactions: 'Premium',
  chat: 'Chat',
  completions: 'Completions',
};

function humanizeLabel(id) {
  if (LABELS[id]) return LABELS[id];
  return id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Low-level GET that returns { statusCode, body }.
 */
function getJson(token) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        host: API_HOST,
        path: API_PATH,
        method: 'GET',
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'application/json',
          'User-Agent': 'copilot-usage-widget',
        },
        timeout: 15000,
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => resolve({ statusCode: res.statusCode, body: data }));
      }
    );
    req.on('timeout', () => req.destroy(new Error('Timeout: request to GitHub timed out')));
    req.on('error', reject);
    req.end();
  });
}

/**
 * Turn the raw API response into a normalized metric list the renderer can draw.
 * Only *limited* quotas are returned (unlimited ones are skipped, like the Python widget).
 *
 * @returns {{ metrics: Array, resetDateUtc: string }}
 */
function parseUsage(data) {
  const snapshots = (data && data.quota_snapshots) || {};
  const resetDateUtc = (data && data.quota_reset_date_utc) || '';
  const metrics = [];

  for (const [id, snap] of Object.entries(snapshots)) {
    if (!snap || snap.unlimited) continue;
    const percentRemaining =
      typeof snap.percent_remaining === 'number' ? snap.percent_remaining : 100;
    const percentUsed = Math.max(0, Math.min(100, 100 - percentRemaining));
    metrics.push({
      id,
      label: humanizeLabel(id),
      entitlement: snap.entitlement || 0,
      remaining: typeof snap.remaining === 'number' ? snap.remaining : 0,
      percentUsed,
      overageCount: snap.overage_count || 0,
      overagePermitted: !!snap.overage_permitted,
      resetsAt: resetDateUtc,
    });
  }

  // Stable, meaningful ordering: premium first, then by usage descending.
  metrics.sort((a, b) => {
    if (a.id === 'premium_interactions') return -1;
    if (b.id === 'premium_interactions') return 1;
    return b.percentUsed - a.percentUsed;
  });

  return { metrics, resetDateUtc };
}

/**
 * Fetch + parse Copilot usage for the given token.
 * Throws Error('Unauthorized'...) / Error('SessionExpired'...) on auth failure so the
 * renderer can drop back to the login screen (mirrors the Claude widget's contract).
 */
async function fetchUsage(token) {
  if (!token) throw new Error('Unauthorized: no token');

  let res;
  try {
    res = await getJson(token);
  } catch (err) {
    throw new Error(`NetworkError: ${err.message}`);
  }

  const { statusCode, body } = res;

  if (statusCode === 401) throw new Error('Unauthorized: GitHub rejected the token (401)');
  if (statusCode === 403 || statusCode === 404) {
    // 403/404 here usually means the token lacks Copilot access or the account has no Copilot seat.
    throw new Error(
      `SessionExpired: GitHub returned ${statusCode} — token may lack Copilot access`
    );
  }
  if (statusCode < 200 || statusCode >= 300) {
    throw new Error(`HttpError ${statusCode}: ${body.slice(0, 200)}`);
  }

  let data;
  try {
    data = JSON.parse(body);
  } catch {
    throw new Error(`InvalidJSON: ${body.slice(0, 200)}`);
  }

  const parsed = parseUsage(data);
  return { ...parsed, fetchedAt: Date.now() };
}

module.exports = { fetchUsage, parseUsage, humanizeLabel };
