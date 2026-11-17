import { SceneHost } from './scene-host.js';
import { escapeHtml } from './primitives.js';
import { validateData } from '../contracts/schemas.js';
import { VIEWS } from '../views/index.js';

export const ANALYSIS_VIEWS = VIEWS;

/**
 * UI composition + plugin registry.
 *
 * The framework never touches global DOM state directly. The host (or the
 * default shell in `shell.js`) supplies a UI port:
 *
 *   { elements: { [elementId]: HTMLElement | null } }
 *
 * New views only need one definition object.
 */
export function createAnalysisFramework({ renderer, canvas, views = ANALYSIS_VIEWS, ui }) {
  const elements = ui?.elements;
  if (!elements || typeof elements !== 'object') {
    throw new TypeError('createAnalysisFramework: a ui port with an elements map is required');
  }
  const byId = new Map(views.map(view => [view.id, view]));
  const cache = new Map();
  const $ = id => elements[id] || null;
  const setHtml = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
  const setText = (id, text) => { const el = $(id); if (el) el.textContent = text; };
  const tooltip = $('tooltip');
  let activeDefinition = null;
  let token = 0;

  const host = new SceneHost({
    renderer, canvas,
    onHover: (payload, event) => {
      if (!tooltip) return;
      tooltip.style.display = 'none';
      host.view?.hover?.(payload);
      if (!payload || !event || !host.view) return;
      const html = host.view.tooltip?.(payload);
      if (!html) return;
      tooltip.innerHTML = html;
      tooltip.style.display = 'block';
      tooltip.style.left = `${Math.min(event.clientX + 16, window.innerWidth - 340)}px`;
      tooltip.style.top = `${Math.min(event.clientY + 14, window.innerHeight - 100)}px`;
    },
    onSelect: payload => {
      if (!payload || !host.view) {
        renderEmptyInspector();
        setText('dock-sel', '—');
        return;
      }
      const body = $('analysis-body');
      if (body) body.innerHTML = host.view.inspect?.(payload) || '<p class="empty">该对象没有详情。</p>';
      $('analysis-panel')?.classList.remove('empty');
      setText('dock-sel', host.view.selectionLabel?.(payload) || 'Selected');
    },
    onReadout: ({ zoom }) => setText('dock-zoom', zoom),
  });

  function renderEmptyInspector() {
    setHtml('analysis-body', `<p class="empty">点击节点、分支或同源区块查看详情。<br>
      拖拽旋转 · 滚轮缩放 · 右键平移 · <span class="k">双击</span> 聚焦</p>
      <div class="sec-label">科学表示原则</div>
      <p class="detail-footnote">坐标和拓扑由数据决定。3D 深度、材质与光晕仅用于视觉分层，不作为额外的统计证据。</p>`);
    $('analysis-panel')?.classList.add('empty');
  }

  function renderDescription(definition) {
    const el = $('analysis-description');
    if (!el) return;
    el.innerHTML = `<button type="button" class="desc-icon" aria-label="视图说明">i</button>
      <div class="desc-pop">${escapeHtml(definition.description)}</div>`;
  }

  function renderLoading(definition) {
    setText('analysis-kicker', definition.subtitle);
    setText('analysis-title', definition.title);
    renderDescription(definition);
    setHtml('analysis-stats', '<div class="loading-line">正在加载本地数据…</div>');
    setHtml('analysis-lists', '');
    setHtml('analysis-controls', '');
    setText('analysis-source', '');
    setText('analysis-head', `${definition.title} · Selection`);
    renderEmptyInspector();
  }

  function bindControls(controls) {
    const controlsEl = $('analysis-controls');
    if (!controlsEl) return;
    controlsEl.querySelectorAll('input,select').forEach(input => {
      input.addEventListener('input', () => {
        const value = input.type === 'checkbox'
          ? input.checked
          : input.type === 'select-one' || input.type === 'select-multiple'
            ? input.value
            : Number(input.value);
        const readout = controlsEl.querySelector(`[data-value="${input.dataset.key}"]`);
        const definitionControl = controls.find(control => control.key === input.dataset.key);
        if (readout) readout.textContent = `${value}${definitionControl?.unit || ''}`;
        host.view?.setOption?.(input.dataset.key, value);
      });
    });
  }

  function renderControls(controls) {
    let groupIndex = -1;
    setHtml('analysis-controls', controls.map(control => {
      if (control.type === 'section') {
        groupIndex += 1;
        return `${groupIndex > 0 ? '</details>' : ''}<details class="ctl-group"${groupIndex === 0 ? ' open' : ''}>
          <summary class="ctl-sec">${escapeHtml(control.label)}</summary>`;
      }
      if (control.type === 'toggle') {
        return `<label class="view-toggle"><span>${escapeHtml(control.label)}</span>
          <input type="checkbox" data-key="${escapeHtml(control.key)}" ${control.value ? 'checked' : ''}><i></i></label>`;
      }
      if (control.type === 'range') {
        return `<label class="view-range"><span>${escapeHtml(control.label)}<b data-value="${escapeHtml(control.key)}">${control.value}${control.unit || ''}</b></span>
          <input type="range" data-key="${escapeHtml(control.key)}" min="${control.min}" max="${control.max}" step="${control.step}" value="${control.value}"></label>`;
      }
      if (control.type === 'select') {
        const options = (control.options || []).map(option =>
          `<option value="${escapeHtml(option.value)}"${option.value === control.value ? ' selected' : ''}>${escapeHtml(option.label)}</option>`
        ).join('');
        return `<label class="view-select"><span>${escapeHtml(control.label)}</span>
          <select data-key="${escapeHtml(control.key)}">${options}</select></label>`;
      }
      return '';
    }).join('') + (groupIndex >= 0 ? '</details>' : ''));
    bindControls(controls);
  }

  function renderSidebar(definition, data) {
    setText('analysis-kicker', definition.subtitle);
    setText('analysis-title', definition.title);
    renderDescription(definition);
    setHtml('analysis-stats', (host.view?.stats?.() || []).map(stat => `
      <div class="analysis-stat"><span>${escapeHtml(stat.label)}</span><b>${escapeHtml(stat.value)}</b></div>`).join(''));
    const controls = typeof definition.controls === 'function' ? definition.controls(data) : (definition.controls || []);
    renderControls(controls);
    setText('analysis-source', data.source || '本地数据');
    setText('crumb-sub', `ANALYSIS // ${definition.subtitle} · ${data.demo ? 'DEMO DATA' : 'LOCAL DATA'}`);
    setText('analysis-head', `${definition.title} · Selection`);
    $('btn-analysis-auto')?.classList.toggle('on', host.autoRotateDesired);

    // Optional view-owned list blocks (object list, searchable site list,
    // interactive legend). The view manages this container; it is cleared on
    // every mount/unmount. Shells without #analysis-lists simply skip this.
    const listHost = $('analysis-lists');
    if (listHost) {
      listHost.innerHTML = '';
      host.view?.mountSidebar?.(listHost);
    }
  }

  async function activate(id) {
    const definition = byId.get(id);
    if (!definition) throw new Error(`未注册的可视化视图：${id}`);
    const currentToken = ++token;
    activeDefinition = definition;
    setText('crumb-sub', `ANALYSIS // ${definition.subtitle} · DEMO DATA`);

    // Rebuild on entry so the controls and scene options always share state.
    host.clearView();
    host.active = true;
    host.controls.enabled = true;
    renderLoading(definition);
    try {
      if (!cache.has(id)) {
        const response = await fetch(definition.dataUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status} · ${definition.dataUrl}`);
        cache.set(id, await response.json());
      }
      if (currentToken !== token) return;
      const data = cache.get(id);
      if (definition.schema) {
        const validation = validateData(definition.schema, data);
        if (!validation.ok) {
          throw new Error(`${definition.schema} 数据校验失败：${validation.errors.slice(0, 3).join('；')}`);
        }
      }
      await host.mount(definition, data);
      if (currentToken !== token) return;
      renderSidebar(definition, data);
      renderEmptyInspector();
      host.resize();
    } catch (error) {
      if (currentToken !== token) return;
      console.error(error);
      setHtml('analysis-stats', `<div class="error-box">视图加载失败<br>${escapeHtml(error.message)}</div>`);
      setHtml('analysis-lists', '');
      setHtml('analysis-controls', '');
    }
  }

  function deactivate() {
    token++;
    activeDefinition = null;
    host.deactivate();
    if (tooltip) tooltip.style.display = 'none';
  }

  $('btn-analysis-reset')?.addEventListener('click', () => host.resetCamera());
  $('btn-analysis-auto')?.addEventListener('click', event => {
    host.setAutoRotate(!host.autoRotateDesired);
    event.currentTarget.classList.toggle('on', host.autoRotateDesired);
  });
  $('btn-analysis-export')?.addEventListener('click', () => {
    if (host.view && activeDefinition) host.exportPng(`gvixb-${activeDefinition.id}.png`);
  });

  return {
    activate,
    deactivate,
    tick: dt => host.tick(dt),
    resize: (width, height) => host.resize(width, height),
    exportPng: () => host.exportPng(),
    pickAt: (x, y) => host.pick(x, y),
    get active() { return host.active; },
    get currentId() { return activeDefinition?.id || null; },
    debug: () => ({
      id: activeDefinition?.id,
      pickables: host.pickables.length,
      visiblePickables: host.pickables.filter(object => host._visible(object)).length,
      objects: host.root?.children.length || 0,
      rootNames: host.root?.children.map(child => `${child.name || child.type}:${child.children.length}`) || [],
      viewDebug: host.view?.debug?.() || null,
      camera: host.camera.position.toArray(),
      selected: $('dock-sel')?.textContent || '',
    }),
  };
}
