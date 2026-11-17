import { mountGvixb } from './gvixb.js';

const mount = document.getElementById('app');
if (!mount) throw new Error('gvixb: 缺少 #app 挂载容器');

// Dev/preview overrides. The host route normally sets data-view / data-endpoint
// server-side; these query parameters only replace those attributes and are
// validated by mountGvixb (same-origin endpoint, registered view).
const params = new URLSearchParams(location.search);
const queryView = params.get('view');
if (queryView) mount.dataset.view = queryView;
const queryEndpoint = params.get('endpoint');
if (queryEndpoint) mount.dataset.endpoint = queryEndpoint;

let instance = null;
try {
  instance = mountGvixb(mount, {
    view: mount.dataset.view,
    endpoint: mount.dataset.endpoint,
  });
} catch (error) {
  console.error(error);
  const stats = document.getElementById('analysis-stats');
  if (stats) {
    stats.innerHTML = '';
    const box = document.createElement('div');
    box.className = 'error-box';
    box.textContent = `视图加载失败：${error.message}`;
    stats.append(box);
  }
}

document.getElementById('gvixb-view-switch')?.addEventListener('change', event => {
  const target = event.target;
  if (target instanceof HTMLSelectElement && target.value) location.href = target.value;
});

if (instance) {
  // Read-only diagnostics for local integration tests and support.
  window.__gvixb = {
    debug: () => instance.framework.debug(),
    pickAt: (x, y) => {
      const payload = instance.framework.pickAt(x, y);
      return payload ? { id: payload.id } : null;
    },
    destroy: () => instance.destroy(),
  };
}
