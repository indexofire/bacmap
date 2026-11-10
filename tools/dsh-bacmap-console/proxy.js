/**
 * Reverse proxy for the local bacmap web console.
 *
 * bacmap answers every page with `X-Frame-Options: DENY` and a CSP carrying
 * `frame-ancestors 'none'` (ADR-16), so its console cannot be framed directly.
 * DSH therefore serves it under the GUI origin: requests under MOUNT are
 * forwarded to the bacmap listener, framing headers are relaxed to the GUI
 * origin, root-absolute URLs are rewritten onto the mount path, and a
 * same-origin runtime shim prefixes URLs bacmap builds at runtime.
 *
 * Only `createHandler` is Host-facing; the pure helpers stay exported so the
 * rewrite rules can be exercised without a running harness.
 */
import { spawn } from 'node:child_process'
import { closeSync, openSync, readSync, statSync } from 'node:fs'
import { request as httpRequest } from 'node:http'
import { request as httpsRequest } from 'node:https'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/** Path prefix owned by this bundle on the DSH web server. */
export const MOUNT = '/bacmap'

/** Same-origin status probe the Client panel polls. */
export const STATUS_PATH = `${MOUNT}/__dsh/status`

/** Start request the Client panel posts when the console is down. */
export const START_PATH = `${MOUNT}/__dsh/start`

/** Runtime URL shim injected into every proxied HTML document. */
export const RUNTIME_PATH = `${MOUNT}/__dsh/runtime.js`

/** Where a started console writes its output; the status detail reads it. */
const LOG_PATH = join(tmpdir(), 'dsh-bacmap-console.log')

/** Responses larger than this are streamed unrewritten instead of buffered. */
const HTML_LIMIT = 8 * 1024 * 1024

const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade',
])

const OFFLINE_PAGE = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bacmap 未运行</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
    font: 14px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    background: #f6f7fb; color: #1f2430; }
  main { max-width: 34rem; padding: 32px; }
  h1 { font-size: 17px; margin: 0 0 8px; }
  p { margin: 0 0 12px; color: #4b5263; }
  code { display: inline-block; padding: 2px 7px; border-radius: 6px;
    background: #eceef6; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
  a { color: #4f5bd5; }
  @media (prefers-color-scheme: dark) {
    body { background: #15171c; color: #e6e8ef; }
    p { color: #a7adbb; }
    code { background: #23262e; }
    a { color: #9aa4ff; }
  }
</style>
</head>
<body>
<main>
  <h1>bacmap 未运行</h1>
  <p>Bacmap's web console is not answering at <code>__UPSTREAM__</code>.</p>
  <p>启动控制台 / Start it in a terminal:</p>
  <p><code>bacmap start web</code></p>
  <p><a href="__MOUNT__/">重新加载 / Retry</a></p>
</main>
</body>
</html>
`

/**
 * Rewrite root-absolute URLs onto the mount path and inject the URL shim.
 * @param html - proxied HTML document text.
 * @param mount - path prefix the proxy answers on.
 * @returns rewritten document text.
 */
export function rewriteHtml(html, mount = MOUNT, { injectShim = true } = {}) {
  const prefixed = html.replace(
    /\b(href|src|action)=(["'])\/(?!\/)/gi,
    (_match, attribute, quote) => `${attribute}=${quote}${mount}/`,
  )
  if (!injectShim) return prefixed
  const shim = `<script src="${mount}/__dsh/runtime.js"></script>`
  return prefixed.includes('</head>')
    ? prefixed.replace('</head>', `${shim}</head>`)
    : `${shim}${prefixed}`
}

/**
 * Relax `frame-ancestors` to the GUI origin while keeping every other directive.
 * @param value - upstream Content-Security-Policy value, when present.
 * @returns the relaxed policy, or undefined when the upstream sent none.
 */
export function relaxCsp(value) {
  if (typeof value !== 'string' || value.trim() === '') return undefined
  if (/frame-ancestors/i.test(value)) {
    return value.replace(/frame-ancestors[^;]*/i, "frame-ancestors 'self'")
  }
  return `${value.replace(/;\s*$/, '')}; frame-ancestors 'self'`
}

/**
 * Prefix a root-relative redirect target with the mount path.
 * @param location - upstream Location header.
 * @param mount - path prefix the proxy answers on.
 * @returns the rewritten target.
 */
export function rewriteLocation(location, mount = MOUNT) {
  if (typeof location !== 'string') return location
  if (location.startsWith('/') && !location.startsWith('//')) return `${mount}${location}`
  return location
}

/**
 * Resolve the upstream request target for one proxied pathname.
 * @param pathname - request pathname as received by the DSH web server.
 * @param mount - path prefix the proxy answers on.
 * @returns the path to request from bacmap.
 */
export function upstreamPath(pathname, mount = MOUNT) {
  if (pathname === mount || pathname === `${mount}/`) return '/'
  const rest = pathname.startsWith(`${mount}/`) ? pathname.slice(mount.length) : pathname
  return rest === '' ? '/' : rest
}

/** @param {URL} target - configured bacmap origin. */
function requester(target) {
  return target.protocol === 'https:' ? httpsRequest : httpRequest
}

/** @param {URL} target - configured bacmap origin. */
function connectionOptions(target) {
  return {
    protocol: target.protocol,
    hostname: target.hostname,
    port: target.port === '' ? undefined : target.port,
  }
}

/** @param {URL} target - configured bacmap origin. */
function probe(target) {
  return new Promise((resolve) => {
    let settled = false
    const done = (value) => {
      if (settled) return
      settled = true
      resolve(value)
    }
    const request = requester(target)({
      ...connectionOptions(target),
      method: 'GET',
      path: '/',
      headers: { accept: 'text/html' },
      timeout: 2500,
    }, (response) => {
      response.resume()
      done(response.statusCode !== undefined && response.statusCode < 500)
    })
    request.on('timeout', () => { request.destroy(new Error('timeout')) })
    request.on('error', () => done(false))
    request.end()
  })
}

/**
 * Answer one request that could not reach bacmap.
 * @param res - response to complete.
 * @param target - configured bacmap origin.
 * @param status - HTTP status to send.
 */
function sendOffline(res, target, status = 502) {
  if (res.headersSent || res.writableEnded || res.destroyed) {
    if (!res.writableEnded && !res.destroyed) res.end()
    return
  }
  const body = OFFLINE_PAGE
    .replaceAll('__UPSTREAM__', target.href.replace(/\/$/, ''))
    .replaceAll('__MOUNT__', MOUNT)
  res.writeHead(status, {
    'content-type': 'text/html; charset=utf-8',
    'content-length': String(Buffer.byteLength(body)),
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  })
  res.end(body)
}

/** @returns the JavaScript shim that prefixes runtime-built root-absolute URLs. */
function runtimeSource() {
  return `(function () {
  var mount = ${JSON.stringify(MOUNT)};
  window.__BACMAP_MOUNT__ = mount;
  window.__BACMAP_ROUTER_BASE__ = mount + '/console/';
  function fix(value) {
    if (typeof value !== 'string' || value.charAt(0) !== '/' || value.charAt(1) === '/') return value;
    if (value === mount || value.indexOf(mount + '/') === 0) return value;
    return mount + value;
  }
  var originalFetch = window.fetch;
  if (typeof originalFetch === 'function') {
    window.fetch = function (input, init) {
      if (typeof input === 'string') return originalFetch.call(this, fix(input), init);
      return originalFetch.call(this, input, init);
    };
  }
  var setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if ((name === 'href' || name === 'src') && typeof value === 'string') {
      value = fix(value);
    }
    return setAttribute.call(this, name, value);
  };
  var xhrOpen = window.XMLHttpRequest && window.XMLHttpRequest.prototype.open;
  if (typeof xhrOpen === 'function') {
    window.XMLHttpRequest.prototype.open = function (method, url) {
      var args = Array.prototype.slice.call(arguments);
      if (typeof url === 'string') args[1] = fix(url);
      return xhrOpen.apply(this, args);
    };
  }
  var NativeEventSource = window.EventSource;
  if (typeof NativeEventSource === 'function') {
    window.EventSource = function (url, config) { return new NativeEventSource(fix(url), config); };
    window.EventSource.prototype = NativeEventSource.prototype;
  }
})();
`
}

/** @returns the last lines a started console wrote, for diagnostics. */
function tailLog() {
  try {
    const size = statSync(LOG_PATH).size
    const length = Math.min(size, 2048)
    if (length === 0) return null
    const buffer = Buffer.alloc(length)
    const fd = openSync(LOG_PATH, 'r')
    try {
      readSync(fd, buffer, 0, length, size - length)
    } finally {
      closeSync(fd)
    }
    return buffer.toString('utf8').trim() || null
  } catch {
    return null
  }
}

/** @param value - text to bound. @param max - maximum length. @returns the bounded text. */
function truncate(value, max = 600) {
  if (typeof value !== 'string') return null
  return value.length <= max ? value : `${value.slice(0, max)}…`
}

/**
 * Build the `webServer` prefix handler for one configured bacmap origin.
 * @param options - upstream URL, mount path, optional admission check, and start command.
 * @returns a node:http request handler.
 */
export function createHandler(options) {
  const target = new URL(options.upstream)
  const mount = options.mount ?? MOUNT
  const admission = options.admission ?? (() => undefined)
  const start = options.start ?? { command: '' }
  const startCommand = typeof start.command === 'string' ? start.command.trim() : ''
  const startCwd = typeof start.cwd === 'string' && start.cwd.trim() !== '' ? start.cwd : undefined

  let child = null
  let lastError = null
  let lastExit = null

  const sendJson = (res, status, payload) => {
    const body = JSON.stringify(payload)
    res.writeHead(status, {
      'content-type': 'application/json; charset=utf-8',
      'content-length': String(Buffer.byteLength(body)),
      'cache-control': 'no-store',
    })
    res.end(body)
  }

  const exitDetail = () => {
    if (lastError !== null) return lastError
    if (lastExit === null) return null
    return lastExit.signal !== null
      ? `exit signal ${String(lastExit.signal)}`
      : `exit code ${String(lastExit.code)}`
  }

  const startSnapshot = (online) => {
    const live = child !== null && child.exitCode === null && child.signalCode === null
    let state = 'idle'
    if (online) state = 'running'
    else if (live) state = 'starting'
    else if (lastExit !== null || lastError !== null) state = 'failed'
    return {
      configured: startCommand !== '',
      state,
      detail: state === 'failed' ? truncate(exitDetail() ?? tailLog()) : null,
    }
  }

  return async function handle(req, res) {
    const rejection = admission(req)
    if (rejection !== undefined) {
      res.statusCode = rejection
      res.end()
      return
    }

    const url = new URL(String(req.url), 'http://dsh.invalid')
    if (url.pathname === START_PATH) {
      if (req.method !== 'POST') {
        res.writeHead(405, { allow: 'POST' })
        res.end()
        return
      }
      if (await probe(target)) {
        sendJson(res, 200, { started: true, alreadyRunning: true })
        return
      }
      const live = child !== null && child.exitCode === null && child.signalCode === null
      if (live) {
        sendJson(res, 202, { started: true, starting: true, pid: child.pid ?? null })
        return
      }
      if (startCommand === '') {
        sendJson(res, 409, { started: false, error: 'no-start-command' })
        return
      }
      lastError = null
      lastExit = null
      try {
        const log = openSync(LOG_PATH, 'a')
        try {
          child = spawn(startCommand, {
            shell: true,
            cwd: startCwd,
            stdio: ['ignore', log, log],
          })
        } finally {
          closeSync(log)
        }
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error)
        sendJson(res, 500, { started: false, error: truncate(lastError) })
        return
      }
      const spawned = child
      spawned.on('error', (error) => {
        lastError = error instanceof Error ? error.message : String(error)
        if (child === spawned) child = null
      })
      spawned.on('exit', (code, signal) => {
        lastExit = { code, signal }
        if (child === spawned) child = null
      })
      // A console started from the panel keeps running after the GUI closes.
      spawned.unref()
      sendJson(res, 202, { started: true, pid: spawned.pid ?? null, log: LOG_PATH })
      return
    }
    if (url.pathname === STATUS_PATH) {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.writeHead(405, { allow: 'GET, HEAD' })
        res.end()
        return
      }
      const online = await probe(target)
      const body = JSON.stringify({
        online,
        upstream: target.href.replace(/\/$/, ''),
        mount,
        start: startSnapshot(online),
      })
      res.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        'content-length': String(Buffer.byteLength(body)),
        'cache-control': 'no-store',
      })
      res.end(body)
      return
    }
    if (url.pathname === RUNTIME_PATH) {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.writeHead(405, { allow: 'GET, HEAD' })
        res.end()
        return
      }
      const body = runtimeSource()
      res.writeHead(200, {
        'content-type': 'text/javascript; charset=utf-8',
        'content-length': String(Buffer.byteLength(body)),
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff',
      })
      res.end(body)
      return
    }

    const headers = {}
    for (const [name, value] of Object.entries(req.headers)) {
      if (value === undefined) continue
      if (HOP_BY_HOP.has(name)) continue
      headers[name] = value
    }
    // Keep HTML plain so the rewrite never has to decode a content encoding.
    headers['accept-encoding'] = 'identity'
    // Keep the browser-facing authority so bacmap's same-origin checks agree
    // with the Origin/Referer the browser sent to the DSH GUI.
    headers.host = req.headers.host ?? target.host

    const upstream = requester(target)({
      ...connectionOptions(target),
      method: req.method,
      path: `${upstreamPath(url.pathname, mount)}${url.search}`,
      headers,
    }, (response) => {
      const out = {}
      for (const [name, value] of Object.entries(response.headers)) {
        if (value === undefined) continue
        if (HOP_BY_HOP.has(name)) continue
        if (name === 'x-frame-options') continue
        out[name] = value
      }
      const relaxed = relaxCsp(response.headers['content-security-policy'])
      if (relaxed === undefined) delete out['content-security-policy']
      else out['content-security-policy'] = relaxed
      if (out.location !== undefined) out.location = rewriteLocation(String(out.location), mount)

      const type = String(response.headers['content-type'] ?? '')
      const encoding = String(response.headers['content-encoding'] ?? 'identity')
      const rewrite = req.method !== 'HEAD' && encoding === 'identity' && /text\/html/i.test(type)

      if (!rewrite) {
        res.writeHead(response.statusCode ?? 502, out)
        response.pipe(res)
        return
      }

      const chunks = []
      let size = 0
      let overflow = false
      response.on('data', (chunk) => {
        size += chunk.length
        if (size > HTML_LIMIT) overflow = true
        if (!overflow) chunks.push(chunk)
      })
      response.on('end', () => {
        if (overflow) {
          // Too large to buffer: answer without pretending the page is usable.
          sendOffline(res, target, 502)
          return
        }
        const upstreamTarget = upstreamPath(url.pathname, mount)
        const isReport = /^\/samples\/[^/]+\/report$/.test(upstreamTarget)
        const body = Buffer.from(
          rewriteHtml(Buffer.concat(chunks).toString('utf8'), mount, { injectShim: !isReport }),
          'utf8',
        )
        delete out['content-length']
        out['content-length'] = String(body.length)
        res.writeHead(response.statusCode ?? 502, out)
        res.end(body)
      })
      response.on('error', () => { sendOffline(res, target) })
    })

    upstream.setTimeout(30_000, () => { upstream.destroy(new Error('bacmap request timed out')) })
    upstream.on('error', () => { sendOffline(res, target) })
    res.on('close', () => { upstream.destroy() })
    req.pipe(upstream)
  }
}
