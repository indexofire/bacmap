# bacmap console (DSH bundle)

Left-sidebar entry plus a main panel that embeds the local
[bacmap](https://github.com/indexofire/bacmap) web console inside the DSH Web GUI.

## Why a proxy

`bacmap start web` answers with `X-Frame-Options: DENY` and a CSP carrying
`frame-ancestors 'none'` (ADR-16), so the console cannot be framed directly.
The Host half therefore registers a `webServer` prefix route at `/bacmap` and
reverse-proxies the console under the GUI origin:

- `x-frame-options` is removed and `frame-ancestors 'none'` becomes
  `frame-ancestors 'self'`;
- root-absolute URLs (`href`, `src`, `action`, redirect `Location`) are
  rewritten onto `/bacmap`, and a small same-origin script sets the SPA router
  base to `/bacmap/console/`, exposes the mount for `appUrl()`, and prefixes
  URLs that bacmap builds at runtime (for example report iframes and the
  task-detail poller). The shim is skipped for sandboxed report documents;
- the route is admitted only through `ctx.connection.requestRejection`, so an
  anonymous request is refused before it reaches bacmap;
- when bacmap is not running the route answers a small "not running" page, and
  the panel shows a banner.

## Use

1. Open the **bacmap** entry in the DSH left sidebar.
2. If the console is down, the banner offers **Start bacmap**. The Host spawns
   the configured `startCommand` in `startCwd`, waits for the console to
   answer, and reloads the frame once it is up. While booting the button shows
   a spinner; a failed start shows the exit code or the tail of the console log.
3. The toolbar dot turns green when the console answers. The reload button
   reloads the frame; the arrow button opens `/bacmap/console/` in a new tab.

The same console can still be started by hand; the Start button then reports
that it is already running.

## Configuration

`cordis.patch.yml` sets the upstream URL and the start action:

```yaml
- insert:
    - id: bacmap-console
      name: '@local/bacmap-console'
      config:
        upstream: http://127.0.0.1:8800
        startCommand: /home/mark/.pixi/bin/pixi run --manifest-path /home/mark/repos/my-project/bacmap/pixi.toml bacmap start web
        startCwd: /home/mark/repos/my-project/bacmap
```

- `startCommand` is run through the platform shell (`spawn(..., { shell: true })`)
  in `startCwd`; keep its `--port` in sync with `upstream`. An empty value
  disables the button (it reports `no-start-command`).
- Output goes to `<tmpdir>/dsh-bacmap-console.log`; a failed start reports the
  exit code or a tail of that file in the banner.
- A console started from the panel keeps running after DSH exits.
- The mount path `/bacmap` is shared by `index.js` and `client.js`; changing it
  means editing both files.

## Limits

- The console is served at `/bacmap/console/` on the GUI origin (the panel
  and the external-open button use that path). A deployment that publishes DSH
  under a path prefix (`--public-url`) is not handled by the URL rewrite yet.
- The Host half is ordinary plugin code: editing `index.js`/`proxy.js` takes
  effect when DSH loads that plugin again. A restart of `dsh web` is the
  reliable path.
