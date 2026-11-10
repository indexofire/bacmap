window.__ModuleLoader__.load({
  id: '@local/bacmap-console',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const NS = 'bacmapConsole'
    const PANEL_ID = 'bacmap'
    const MOUNT = '/bacmap'

    const en = {
      panel: 'bacmap',
      title: 'bacmap',
      reload: 'Reload console',
      openExternal: 'Open in a new tab',
      offlineTitle: 'bacmap is not running',
      offlineHint: 'Start the console in a terminal:',
      retry: 'Retry',
      start: 'Start bacmap',
      starting: 'Starting bacmap…',
      startFailed: 'bacmap could not be started',
      startTimeout: 'bacmap did not answer in time',
      noStartCommand: 'No start command is configured for this plugin',
      frameTitle: 'bacmap web console',
      checking: 'Checking console state',
      online: 'Connected',
      offline: 'Not reachable',
    }
    const zh = {
      panel: 'bacmap',
      title: 'bacmap 控制台',
      reload: '重新加载控制台',
      openExternal: '在新标签页打开',
      offlineTitle: 'bacmap 未运行',
      offlineHint: '请在终端启动控制台：',
      retry: '重试',
      start: '启动 bacmap',
      starting: '正在启动 bacmap…',
      startFailed: '无法启动 bacmap',
      startTimeout: 'bacmap 未在预期时间内就绪',
      noStartCommand: '该插件未配置启动命令',
      frameTitle: 'bacmap Web 控制台',
      checking: '正在检查控制台状态',
      online: '已连接',
      offline: '无法连接',
    }

    const css = `
.dsh-bacmap{flex:1 1 auto;display:flex;flex-direction:column;height:100%;min-height:0;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary)}
.dsh-bacmap__bar{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:12px;height:38px;padding:0 8px 0 12px;border-bottom:1px solid var(--dsw-alias-border-l1)}
.dsh-bacmap__identity{display:flex;align-items:center;gap:8px;min-width:0}
.dsh-bacmap__name{font-size:13px;font-weight:600;letter-spacing:.01em;white-space:nowrap}
.dsh-bacmap__dot{width:7px;height:7px;border-radius:50%;background:var(--dsw-alias-state-idle-primary);flex:0 0 auto}
.dsh-bacmap__dot[data-online="true"]{background:var(--dsw-alias-state-success-primary)}
.dsh-bacmap__dot[data-online="false"]{background:var(--dsw-alias-state-error-primary)}
.dsh-bacmap__actions{display:flex;align-items:center;gap:2px}
.dsh-bacmap__button{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--dsw-alias-label-secondary);cursor:pointer;text-decoration:none}
.dsh-bacmap__button:hover{background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary)}
.dsh-bacmap__button:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:1px}
.dsh-bacmap__banner{flex:0 0 auto;display:flex;flex-direction:column;align-items:stretch;gap:6px;padding:8px 12px;border-bottom:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1);font-size:12px;color:var(--dsw-alias-label-secondary)}
.dsh-bacmap__bannerRow{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dsh-bacmap__banner strong{font-weight:600;color:var(--dsw-alias-state-warn-primary)}
.dsh-bacmap__bannerHint{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.dsh-bacmap__banner code{padding:1px 6px;border-radius:5px;background:var(--dsw-alias-bg-layer-2);font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dsw-alias-label-primary)}
.dsh-bacmap__banner button{appearance:none;padding:2px 8px;border:1px solid var(--dsw-alias-border-l1);border-radius:6px;background:transparent;color:var(--dsw-alias-label-primary);font-size:12px;cursor:pointer}
.dsh-bacmap__banner button:hover{background:var(--dsw-alias-bg-layer-2)}
.dsh-bacmap__banner button.dsh-bacmap__start{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border:0;border-radius:6px;background:var(--dsw-alias-button-primary-fill);color:var(--dsw-alias-label-primary-foreground);font-size:12px;font-weight:600;cursor:pointer}
.dsh-bacmap__banner button.dsh-bacmap__start:hover:not(:disabled){background:var(--dsw-alias-button-primary-hover)}
.dsh-bacmap__banner button.dsh-bacmap__start:disabled{opacity:.65;cursor:default}
.dsh-bacmap__banner button.dsh-bacmap__start:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:1px}
.dsh-bacmap__spinner{width:11px;height:11px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:dsh-bacmap-spin .8s linear infinite}
.dsh-bacmap__error{color:var(--dsw-alias-state-error-primary)}
@keyframes dsh-bacmap-spin{to{transform:rotate(360deg)}}
.dsh-bacmap__frame{flex:1 1 auto;display:block;width:100%;min-height:0;border:0;background:var(--dsw-alias-bg-base)}
`

    function PanelIcon({ size = 18 }) {
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': true, style: { display: 'block' },
      },
      h('circle', { cx: 12, cy: 12, r: 8.1 }),
      h('path', { d: 'M7.9 13.6c1.3-2.9 2.7-4.3 4.1-4.3 1.4 0 2.1 1 3.4 1 .8 0 1.5-.3 2-1' }),
      h('circle', { cx: 9.4, cy: 9.6, r: 1, fill: 'currentColor', stroke: 'none' }),
      h('circle', { cx: 14.9, cy: 14.6, r: 1, fill: 'currentColor', stroke: 'none' }))
    }

    function ReloadIcon() {
      return h('svg', {
        width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': true,
      },
      h('path', { d: 'M19.5 12a7.5 7.5 0 1 1-2.2-5.3' }),
      h('path', { d: 'M19.5 4.5V9H15' }))
    }

    function ExternalIcon() {
      return h('svg', {
        width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': true,
      },
      h('path', { d: 'M13.5 4.5H19.5V10.5' }),
      h('path', { d: 'M19.5 4.5 12 12' }),
      h('path', { d: 'M18 14.5v4a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4' }))
    }

    function PlayIcon() {
      return h('svg', {
        width: 12, height: 12, viewBox: '0 0 24 24', fill: 'currentColor',
        'aria-hidden': true,
      },
      h('path', { d: 'M8 5.5v13l11-6.5z' }))
    }

    function Panel(props) {
      const fallback = key => en[key] ?? key
      const t = typeof props.t === 'function' ? props.t : fallback
      const [online, setOnline] = React.useState(null)
      const [generation, setGeneration] = React.useState(0)
      const [starting, setStarting] = React.useState(false)
      const [startError, setStartError] = React.useState(null)

      React.useEffect(function () {
        let alive = true
        let timer
        function check() {
          fetch(MOUNT + '/__dsh/status', { cache: 'no-store', headers: { accept: 'application/json' } })
            .then(function (response) {
              return response.ok ? response.json() : Promise.reject(new Error(String(response.status)))
            })
            .then(function (data) {
              if (alive) setOnline(data.online === true)
            })
            .catch(function () {
              if (alive) setOnline(false)
            })
            .then(function () {
              if (alive) timer = setTimeout(check, 10000)
            })
        }
        check()
        return function () {
          alive = false
          clearTimeout(timer)
        }
      }, [generation])

      const status = online === null ? t('checking') : online ? t('online') : t('offline')

      async function startConsole() {
        if (starting) return
        setStarting(true)
        setStartError(null)
        try {
          const response = await fetch(MOUNT + '/__dsh/start', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: '{}',
          })
          const data = await response.json().catch(function () { return {} })
          if (!response.ok || data.started !== true) {
            setStarting(false)
            setStartError(data.error === 'no-start-command' ? t('noStartCommand') : (data.error || t('startFailed')))
            return
          }
          // The console boots asynchronously; wait for it, then mount the frame once.
          for (let attempt = 0; attempt < 40; attempt += 1) {
            await new Promise(function (resolve) { setTimeout(resolve, 750) })
            let state = null
            try {
              const probe = await fetch(MOUNT + '/__dsh/status', { cache: 'no-store' })
              state = await probe.json()
            } catch {
              state = null
            }
            if (state !== null && state.online === true) {
              setOnline(true)
              setStarting(false)
              setGeneration(function (value) { return value + 1 })
              return
            }
            if (state !== null && state.start && state.start.state === 'failed') {
              setStarting(false)
              setStartError(state.start.detail || t('startFailed'))
              return
            }
          }
          setStarting(false)
          setStartError(t('startTimeout'))
        } catch (error) {
          setStarting(false)
          setStartError(t('startFailed'))
        }
      }

      return h('div', { className: 'dsh-bacmap' },
        h('style', null, css),
        h('div', { className: 'dsh-bacmap__bar' },
          h('div', { className: 'dsh-bacmap__identity' },
            h('span', {
              className: 'dsh-bacmap__dot', 'data-online': String(online), role: 'img', 'aria-label': status, title: status,
            }),
            h('span', { className: 'dsh-bacmap__name' }, t('title'))),
          h('div', { className: 'dsh-bacmap__actions' },
            h('button', {
              type: 'button', className: 'dsh-bacmap__button',
              onClick: function () { setGeneration(value => value + 1) },
              title: t('reload'), 'aria-label': t('reload'),
            }, h(ReloadIcon)),
            h('a', {
              className: 'dsh-bacmap__button', href: MOUNT + '/console/', target: '_blank',
              rel: 'noreferrer noopener', title: t('openExternal'), 'aria-label': t('openExternal'),
            }, h(ExternalIcon)))),
        online === false
          ? h('div', { className: 'dsh-bacmap__banner', role: 'status' },
            h('div', { className: 'dsh-bacmap__bannerRow' },
              h('strong', null, t('offlineTitle')),
              h('button', {
                type: 'button', className: 'dsh-bacmap__start', disabled: starting,
                onClick: startConsole,
              },
              starting
                ? h('span', { className: 'dsh-bacmap__spinner', 'aria-hidden': true })
                : h(PlayIcon),
              starting ? t('starting') : t('start'))),
            h('div', { className: 'dsh-bacmap__bannerHint' },
              h('span', null, t('offlineHint')),
              h('code', null, 'bacmap start web'),
              h('button', {
                type: 'button', onClick: function () { setGeneration(value => value + 1) },
              }, t('retry'))),
            startError !== null
              ? h('div', { className: 'dsh-bacmap__error', role: 'alert' }, startError)
              : null)
          : null,
        h('iframe', {
          key: generation,
          className: 'dsh-bacmap__frame',
          src: MOUNT + '/console/',
          title: t('frameTitle'),
          referrerPolicy: 'no-referrer',
        }))
    }

    return {
      inject: ['slots', 'locale'],
      apply(ctx) {
        ctx.effect(() => ctx.locale.register(NS, { en, zh }), 'bacmap console: dictionaries')
        const t = ctx.locale.bind(NS)
        ctx.slots.inject('main', () => ctx.slots.register({
          name: 'main', key: PANEL_ID, locale: NS,
        }, Panel))
        ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
          name: 'sidebar.panellist', id: PANEL_ID, order: 12, locale: NS,
          label: () => t('panel'),
        }, PanelIcon))
      },
    }
  },
})
