/**
 * Host half of the bacmap console bundle.
 *
 * Registers one `webServer` prefix route that proxies the local bacmap web
 * console under the GUI origin. The Client half renders the sidebar entry and
 * the panel that frames that route; see `client.js`.
 */
import { MOUNT, createHandler } from './proxy.js'

/** Services this bundle needs: an HTTP seat and the browser admission fence. */
export const inject = ['webServer', 'connection']

/** One row's optional overrides; the row lives in `cordis.patch.yml`. */
export const DEFAULT_UPSTREAM = 'http://127.0.0.1:8800'

/**
 * Mount the console proxy for this profile.
 * @param ctx - Host plugin context.
 * @param config - the row's config: `{ upstream?: string, startCommand?: string, startCwd?: string }`.
 */
export function apply(ctx, config) {
  const candidate = typeof config?.upstream === 'string' && config.upstream.trim() !== ''
    ? config.upstream.trim()
    : DEFAULT_UPSTREAM
  let upstream
  try {
    upstream = new URL(candidate)
  } catch {
    throw new Error(`bacmap console: "upstream" is not a URL: ${candidate}`)
  }
  if (upstream.protocol !== 'http:' && upstream.protocol !== 'https:') {
    throw new Error(`bacmap console: "upstream" must be http(s): ${candidate}`)
  }

  const handle = createHandler({
    upstream: upstream.href,
    mount: MOUNT,
    // The console is loopback data: serve it only to a request the GUI's
    // browser admission already trusts, never to an anonymous guest.
    admission: req => ctx.connection.requestRejection(req),
    start: {
      command: typeof config?.startCommand === 'string' ? config.startCommand : '',
      cwd: typeof config?.startCwd === 'string' ? config.startCwd : undefined,
    },
  })

  ctx.effect(
    () => ctx.webServer.register({ kind: 'prefix', path: MOUNT, handler: handle }),
    `bacmap console: ${MOUNT} → ${upstream.origin}`,
  )
}
