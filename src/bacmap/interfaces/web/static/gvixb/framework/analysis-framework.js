import * as THREE from '../vendor/three.module.js';
import { SceneHost } from './scene-host.js';
import { escapeHtml } from './primitives.js';
import { validateData } from '../contracts/schemas.js';
import { VIEWS } from '../views/index.js';
import { readUiPrefs, writeUiPrefs } from './ui-prefs.js';

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
  let panelEl = null;
  const viewStateListeners = new Set();
  const controlValues = {};
  let currentControls = [];
  const notifyViewStateChange = () => viewStateListeners.forEach(cb => {
    try { cb(getViewState()); } catch (error) { console.error(error); }
  });

  const handleSelect = payload => {
    if (!payload || !host.view) {
      renderEmptyInspector();
      setText('dock-sel', '—');
      return;
    }
    const body = $('analysis-body');
    if (body) body.innerHTML = host.view.inspect?.(payload) || '<p class="empty">该对象没有详情。</p>';
    $('analysis-panel')?.classList.remove('empty');
    setText('dock-sel', host.view.selectionLabel?.(payload) || 'Selected');
    // selection while the right panel is collapsed: hint on the tab, no auto-open
    const rightAside = $('analysis-panel');
    if (rightAside?.classList.contains('collapsed')) panelTabs.get('right')?.classList.add('dot');
  };

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
    onSelect: handleSelect,
    onReadout: ({ zoom }) => setText('dock-zoom', zoom),
  });

  // Programmatic selection — identical to a pick click: plugin.select handles
  // the scene mark, the framework path renders the inspector + dock label.
  host.select = payload => {
    host.view?.select?.(payload);
    handleSelect(payload);
  };
  // Fly so the camera keeps its CURRENT view direction and ends centred on
  // `position` at `distance` (default: current distance, clamped to [6, 14]).
  host.centerOn = (position, { distance } = {}) => {
    const target = new THREE.Vector3().copy(position);
    const dir = host.camera.position.clone().sub(host.controls.target).normalize();
    const current = host.camera.position.distanceTo(host.controls.target);
    const dist = Math.min(14, Math.max(6, Number.isFinite(distance) ? distance : current));
    host.flyTo(target.clone().add(dir.multiplyScalar(dist)), target);
  };

  host.notifyStateChange = notifyViewStateChange;
  // set a control through the same path as user input (DOM + setOption + notify)
  host.setControl = (key, value) => {
    const input = $('analysis-controls')?.querySelector(`[data-key="${key}"]`);
    if (!input) return false;
    if (input.type === 'checkbox') input.checked = !!value;
    else input.value = String(value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  };
  host.controls?.addEventListener?.('end', notifyViewStateChange);

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
        controlValues[input.dataset.key] = value;
        host.view?.setOption?.(input.dataset.key, value);
        notifyViewStateChange();
      });
    });
  }

  function renderControls(controls) {
    currentControls = controls;
    for (const control of controls) if (control.key !== undefined) controlValues[control.key] = control.value;
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

    // Optional view-owned right-panel section (e.g. a matched-leaf table),
    // inserted above the inspector body. The plugin toggles el.hidden; the
    // shell keeps the aside visible via the has-view-panel class.
    const panelAside = $('analysis-panel');
    const panelBody = $('analysis-body');
    if (panelAside && panelBody && host.view?.mountPanel) {
      panelEl?.remove();
      panelEl = document.createElement('section');
      panelEl.className = 'view-panel';
      panelEl.dataset.role = 'view-panel';
      panelEl.hidden = true;
      panelAside.insertBefore(panelEl, panelBody);
      host.view.mountPanel(panelEl);
    }
  }

  async function activate(id) {
    const definition = byId.get(id);
    if (!definition) throw new Error(`未注册的可视化视图：${id}`);
    const currentToken = ++token;
    activeDefinition = definition;
    panelEl?.remove();
    panelEl = null;
    $('analysis-panel')?.classList.remove('has-view-panel');
    setText('crumb-sub', `ANALYSIS // ${definition.subtitle} · DEMO DATA`);

    // Rebuild on entry so the controls and scene options always share state.
    host.clearView();
    host.active = true;
    host.controls.enabled = true;
    renderLoading(definition);
    try {
      if (!cache.has(id)) {
        if (definition.data !== undefined) {
          cache.set(id, definition.data);
        } else {
          const response = await fetch(definition.dataUrl);
          if (!response.ok) throw new Error(`HTTP ${response.status} · ${definition.dataUrl}`);
          cache.set(id, await response.json());
        }
      }
      if (currentToken !== token) return;
      const data = cache.get(id);
      const schema = definition.acceptsSchemas?.includes(data?.schema)
        ? data.schema
        : definition.schema;
      if (schema) {
        const validation = validateData(schema, data);
        if (!validation.ok) {
          throw new Error(`${schema} 数据校验失败：${validation.errors.slice(0, 3).join('；')}`);
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

  // ---- collapsible side panels ------------------------------------------
  // Screen-layout preference only (localStorage gvixb:ui-panels) — never part
  // of the view-state/session contract. Each existing aside gets a slim tab on
  // its inner edge; collapsed asides slide off-screen (pointer-events none).
  const panelTabs = new Map();
  const panelCleanups = [];
  const panelAside = side => $(side === 'left' ? 'analysis-sidebar' : 'analysis-panel');

  function positionPanelTab(side) {
    const aside = panelAside(side);
    const tab = panelTabs.get(side);
    if (!aside || !tab) return;
    const collapsed = aside.classList.contains('collapsed');
    // offset* metrics ignore the slide transform, so the tab gets the settled
    // (expanded) edge even while the panel is still animating back in
    // the tab is position:fixed, so add the (untransformed) offsetParent's
    // viewport origin — hosts may not mount the shell at the page origin
    const base = aside.offsetParent?.getBoundingClientRect?.() ?? { left: 0, top: 0 };
    const left = base.left + aside.offsetLeft, width = aside.offsetWidth;
    if (side === 'left') {
      tab.style.left = collapsed ? '0px' : `${Math.max(0, left + width - 1)}px`;
      tab.style.right = 'auto';
    } else {
      tab.style.right = collapsed ? '0px' : `${Math.max(0, window.innerWidth - left - 1)}px`;
      tab.style.left = 'auto';
    }
    tab.style.top = `${Math.max(0, base.top + aside.offsetTop + 30)}px`;
  }

  function setPanelCollapsed(side, collapsed, { persist = true } = {}) {
    const aside = panelAside(side);
    const tab = panelTabs.get(side);
    if (!aside || !tab) return;
    aside.classList.toggle('collapsed', collapsed);
    tab.classList.toggle('collapsed', collapsed);
    tab.setAttribute('aria-expanded', String(!collapsed));
    tab.setAttribute('aria-label', `${collapsed ? '显示' : '隐藏'}${side === 'left' ? '左' : '右'}侧面板`);
    tab.textContent = side === 'left' ? (collapsed ? '›' : '‹') : (collapsed ? '‹' : '›');
    if (!collapsed) tab.classList.remove('dot');
    if (persist) writeUiPrefs({ [side]: collapsed });
    positionPanelTab(side);
    // let float-legend listeners reposition once the slide settles (and once
    // immediately for prefers-reduced-motion where no transition fires)
    document.dispatchEvent(new CustomEvent('gvixb:layout'));
  }

  function setupPanelToggles() {
    const prefs = readUiPrefs();
    for (const side of ['left', 'right']) {
      const aside = panelAside(side);
      if (!aside) continue;
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = `panel-tab panel-tab-${side}`;
      aside.parentElement?.appendChild(tab);
      panelTabs.set(side, tab);
      tab.addEventListener('click', () => setPanelCollapsed(side, !aside.classList.contains('collapsed')));
      const onAsideEnd = ev => {
        if (ev.target !== aside || ev.propertyName !== 'transform') return;
        positionPanelTab(side);
        document.dispatchEvent(new CustomEvent('gvixb:layout'));
      };
      aside.addEventListener('transitionend', onAsideEnd);
      panelCleanups.push(() => aside.removeEventListener('transitionend', onAsideEnd));
      setPanelCollapsed(side, !!prefs[side], { persist: false });
    }
    const onPanelResize = () => { positionPanelTab('left'); positionPanelTab('right'); };
    window.addEventListener('resize', onPanelResize);
    panelCleanups.push(() => window.removeEventListener('resize', onPanelResize));
    const onPanelKeydown = ev => {
      if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.isComposing) return;
      // physical key position wins (IME may rewrite ev.key to 【/】 or 'Process')
      const side = ev.code === 'BracketLeft' ? 'left'
        : ev.code === 'BracketRight' ? 'right'
        : ev.key === '[' || ev.key === '【' ? 'left'
        : ev.key === ']' || ev.key === '】' ? 'right' : null;
      if (!side) return;
      const t = ev.target;
      const tag = t?.tagName;
      if (tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable) return;
      if (tag === 'INPUT') {
        const type = (t.type || 'text').toLowerCase();
        const nonText = ['checkbox', 'radio', 'range', 'button', 'submit', 'reset', 'color', 'file', 'image', 'hidden'];
        if (!nonText.includes(type)) return; // text-entry inputs keep their keys
      }
      setPanelCollapsed(side, !panelAside(side)?.classList.contains('collapsed'));
    };
    window.addEventListener('keydown', onPanelKeydown);
    panelCleanups.push(() => window.removeEventListener('keydown', onPanelKeydown));
  }
  setupPanelToggles();

  function deactivate() {
    token++;
    activeDefinition = null;
    panelEl?.remove();
    panelEl = null;
    $('analysis-panel')?.classList.remove('has-view-panel');
    renderEmptyInspector();
    setText('dock-sel', '—');
    host.deactivate();
    if (tooltip) tooltip.style.display = 'none';
  }

  // Full teardown: the tabs live outside the mount root and the window/aside
  // listeners are registered per mount — without this, remounting the app
  // (e.g. 重新导入) duplicates tabs and keydown handlers. The asides' collapsed
  // classes stay: prefs re-apply on the next setupPanelToggles.
  function dispose() {
    for (const cleanup of panelCleanups.splice(0)) cleanup();
    for (const tab of panelTabs.values()) tab.remove();
    panelTabs.clear();
    panelEl?.remove();
    panelEl = null;
    $('analysis-panel')?.classList.remove('has-view-panel');
    // deactivate() alone leaves the view mounted — dispose it so per-view DOM
    // (float legend, view-panel leftovers) and listeners are actually removed
    host.clearView?.();
    for (const id of ['analysis-stats', 'analysis-lists', 'analysis-controls', 'analysis-description', 'analysis-source', 'analysis-head', 'analysis-kicker', 'analysis-title']) {
      const el = $(id);
      if (el) el.textContent = '';
    }
  }

  $('btn-analysis-reset')?.addEventListener('click', () => host.resetCamera());
  $('btn-analysis-auto')?.addEventListener('click', event => {
    host.setAutoRotate(!host.autoRotateDesired);
    event.currentTarget.classList.toggle('on', host.autoRotateDesired);
  });
  $('btn-analysis-export')?.addEventListener('click', () => {
    if (host.view && activeDefinition) host.exportPng(`gvixb-${activeDefinition.id}.png`);
  });

  function getViewState() {
    if (!activeDefinition || !host.view) return null;
    return {
      version: 1,
      view: activeDefinition.id,
      controls: { ...controlValues },
      plugin: host.view.getState?.() ?? null,
      camera: {
        position: host.camera.position.toArray(),
        target: host.controls.target.toArray(),
      },
    };
  }

  function applyViewState(state) {
    const warnings = [];
    if (!state || state.view !== activeDefinition?.id || !host.view) return warnings;
    const saved = state.controls || {};
    // Apply in control-definition order so dependent rebuilds settle correctly.
    for (const control of currentControls) {
      const key = control.key;
      if (key === undefined || !(key in saved)) continue;
      const value = saved[key];
      const changed = value !== controlValues[key];
      controlValues[key] = value;
      const input = $('analysis-controls')?.querySelector(`[data-key="${key}"]`);
      if (input) {
        if (input.type === 'checkbox') input.checked = !!value;
        else input.value = value;
        const readout = input.closest('label')?.querySelector(`[data-value="${key}"]`)
          || $('analysis-controls').querySelector(`[data-value="${key}"]`);
        if (readout) readout.textContent = `${value}${control.unit || ''}`;
      }
      // Only re-issue setOption for values that differ from the current state:
      // unchanged defaults must not trigger side effects (e.g. rotate → autoRotate).
      if (changed) host.view.setOption?.(key, value);
    }
    if (state.plugin) {
      try {
        const pluginWarnings = host.view.setState?.(state.plugin);
        if (Array.isArray(pluginWarnings)) warnings.push(...pluginWarnings);
      } catch (error) {
        warnings.push(`插件状态恢复失败：${error.message}`);
      }
    }
    if (Array.isArray(state.camera?.position)) {
      const [x, y, z] = state.camera.position;
      const target = state.camera.target || [0, 0, 0];
      host.setCamera(host.camera.position.clone().set(x, y, z), host.controls.target.clone().set(target[0], target[1], target[2]));
    }
    notifyViewStateChange();
    return warnings;
  }

  function onViewStateChange(cb) {
    viewStateListeners.add(cb);
    return () => viewStateListeners.delete(cb);
  }

  return {
    activate,
    deactivate,
    dispose,
    getViewState,
    applyViewState,
    onViewStateChange,
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
      autoRotate: host.autoRotateDesired,
      selected: $('dock-sel')?.textContent || '',
    }),
  };
}
