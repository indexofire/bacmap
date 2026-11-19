import * as THREE from './vendor/three.module.js';
import { createAnalysisFramework, ANALYSIS_VIEWS } from './framework/analysis-framework.js';
import { createShellPort } from './shell.js';

export { ANALYSIS_VIEWS };

// Canvases whose WebGL context was force-lost by destroy(); a remount on the
// same element must swap in a fresh canvas.
const RETIRED_CANVASES = new WeakSet();

/**
 * Mount one gvixb view into a host-owned element.
 *
 *   const instance = mountGvixb(root, {
 *     view: 'mst',
 *     endpoint: '/api/result/mst.json',  // or `data: <json object>`
 *   });
 *   instance.ready.then(() => ...);
 *   instance.destroy();
 *
 * The runtime only needs a root element and a same-origin JSON endpoint; it
 * does not depend on global IDs, the document title, or a particular host
 * layout. When `shell: true` (default) it reads the optional IDs documented in
 * `shell.js`; with `shell: false` the caller supplies its own UI.
 */
export function mountGvixb(root, {
  view,
  endpoint,
  data,
  views = ANALYSIS_VIEWS,
  shell = true,
} = {}) {
  const definition = views.find(item => item.id === view);
  if (!definition) {
    throw new Error(`未注册的可视化视图：${view}`);
  }
  if ((endpoint == null) === (data == null)) {
    throw new Error('mountGvixb: exactly one of endpoint or data is required');
  }
  if (!root || !root.ownerDocument) {
    throw new TypeError('mountGvixb: root must be a DOM element');
  }

  const document = root.ownerDocument;
  const window = document.defaultView;
  let url = null;
  if (endpoint != null) {
    url = new URL(endpoint, document.baseURI);
    if (window && url.origin !== window.location.origin) {
      throw new Error('mountGvixb: endpoint must be same-origin');
    }
  }

  let canvas = root.querySelector('canvas#scene') || root.querySelector('canvas');
  const createdCanvas = !canvas;
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = 'scene';
    canvas.setAttribute('aria-label', 'gvixb 3D 可视化画布');
    root.prepend(canvas);
  } else {
    // A canvas whose GL context was lost (e.g. a previous instance's
    // destroy() → forceContextLoss) can never render again — swap in a clone.
    // Probing with getContext() would create a context with default
    // attributes on a fresh host canvas, so only retired canvases are swapped.
    if (RETIRED_CANVASES.has(canvas)) {
      const fresh = canvas.cloneNode(false);
      canvas.replaceWith(fresh);
      canvas = fresh;
    }
  }

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window?.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x05070d, 1);

  const ui = shell ? createShellPort(root) : { root, elements: {}, missing: [] };
  const selectedView = { ...definition };
  if (url) selectedView.dataUrl = url.href;
  else selectedView.data = data;
  const framework = createAnalysisFramework({
    renderer, canvas, views: [selectedView], ui,
  });

  function measure() {
    return {
      width: root.clientWidth || window?.innerWidth || 1,
      height: root.clientHeight || window?.innerHeight || 1,
    };
  }

  function resize() {
    const { width, height } = measure();
    renderer.setPixelRatio(Math.min(window?.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    framework.resize(width, height);
  }

  const clock = new THREE.Clock();
  let frame = 0;
  let destroyed = false;
  function animate() {
    if (destroyed) return;
    frame = window.requestAnimationFrame(animate);
    framework.tick(clock.getDelta());
  }

  const observer = typeof window?.ResizeObserver === 'function'
    ? new window.ResizeObserver(() => resize())
    : null;
  observer?.observe(root);
  window?.addEventListener('resize', resize);

  resize();
  const ready = framework.activate(definition.id);
  animate();

  return {
    root,
    canvas,
    renderer,
    framework,
    view: definition,
    ready,
    resize,
    getViewState: () => framework.getViewState(),
    applyViewState: state => framework.applyViewState(state),
    onViewStateChange: cb => framework.onViewStateChange(cb),
    destroy() {
      if (destroyed) return;
      destroyed = true;
      window?.cancelAnimationFrame(frame);
      observer?.disconnect();
      window?.removeEventListener('resize', resize);
      framework.deactivate();
      renderer.dispose();
      renderer.forceContextLoss?.();
      RETIRED_CANVASES.add(canvas);
      if (createdCanvas) canvas.remove();
    },
  };
}
