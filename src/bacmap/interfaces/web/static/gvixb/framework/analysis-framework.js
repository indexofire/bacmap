import { SceneHost } from './scene-host.js';
import { escapeHtml } from './primitives.js';
import { assemblyView } from '../views/assembly-view.js';
import { phyloView } from '../views/phylo-view.js';
import { mstView } from '../views/mst-view.js';

export const ANALYSIS_VIEWS = [assemblyView, phyloView, mstView];

/** UI composition + plugin registry. New views only need one definition object. */
export function createAnalysisFramework({ renderer, canvas, views = ANALYSIS_VIEWS }) {
  const byId = new Map(views.map(view => [view.id, view]));
  const cache = new Map();
  const $ = id => document.getElementById(id);
  const tooltip = $('tooltip');
  let activeDefinition = null;
  let token = 0;

  const host = new SceneHost({
    renderer, canvas,
    onHover: (payload, event) => {
      tooltip.style.display = 'none';
      if (!payload || !event || !host.view) return;
      const html = host.view.tooltip?.(payload);
      if (!html) return;
      tooltip.innerHTML = html;
      tooltip.style.display = 'block';
      tooltip.style.left = `${Math.min(event.clientX + 16, window.innerWidth - 340)}px`;
      tooltip.style.top = `${Math.min(event.clientY + 14, window.innerHeight - 100)}px`;
    },
    onSelect: payload => {
      const body = $('analysis-body');
      if (!payload || !host.view) {
        renderEmptyInspector();
        $('dock-sel').textContent = '—';
        return;
      }
      body.innerHTML = host.view.inspect?.(payload) || '<p class="empty">该对象没有详情。</p>';
      $('analysis-panel').classList.remove('empty');
      $('dock-sel').textContent = host.view.selectionLabel?.(payload) || 'Selected';
    },
    onReadout: ({ zoom }) => { $('dock-zoom').textContent = zoom; },
  });

  function renderEmptyInspector() {
    $('analysis-body').innerHTML = `<p class="empty">点击节点、分支或同源区块查看详情。<br>
      拖拽旋转 · 滚轮缩放 · 右键平移 · <span class="k">双击</span> 聚焦</p>
      <div class="sec-label">科学表示原则</div>
      <p class="detail-footnote">坐标和拓扑由数据决定。3D 深度、材质与光晕仅用于视觉分层，不作为额外的统计证据。</p>`;
    $('analysis-panel').classList.add('empty');
  }

  function renderLoading(definition) {
    $('analysis-kicker').textContent = definition.subtitle;
    $('analysis-title').textContent = definition.title;
    $('analysis-description').textContent = definition.description;
    $('analysis-stats').innerHTML = '<div class="loading-line">正在加载本地数据…</div>';
    $('analysis-controls').innerHTML = '';
    $('analysis-source').textContent = '';
    $('analysis-head').textContent = `${definition.title} · Selection`;
    renderEmptyInspector();
  }

  function renderSidebar(definition, data) {
    $('analysis-kicker').textContent = definition.subtitle;
    $('analysis-title').textContent = definition.title;
    $('analysis-description').textContent = definition.description;
    $('analysis-stats').innerHTML = (host.view?.stats?.() || []).map(stat => `
      <div class="analysis-stat"><span>${escapeHtml(stat.label)}</span><b>${escapeHtml(stat.value)}</b></div>`).join('');
    const controls = typeof definition.controls === 'function' ? definition.controls(data) : (definition.controls || []);
    $('analysis-controls').innerHTML = controls.map(control => {
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
    }).join('');
    $('analysis-source').textContent = data.source || '本地数据';
    $('crumb-sub').textContent = `ANALYSIS // ${definition.subtitle} · ${data.demo ? 'DEMO DATA' : 'LOCAL DATA'}`;
    $('analysis-head').textContent = `${definition.title} · Selection`;
    $('btn-analysis-auto').classList.toggle('on', host.controls.autoRotate);

    $('analysis-controls').querySelectorAll('input,select').forEach(input => {
      input.addEventListener('input', () => {
        const value = input.type === 'checkbox'
          ? input.checked
          : input.type === 'select-one' || input.type === 'select-multiple'
            ? input.value
            : Number(input.value);
        const readout = $('analysis-controls').querySelector(`[data-value="${input.dataset.key}"]`);
        const definitionControl = controls.find(control => control.key === input.dataset.key);
        if (readout) readout.textContent = `${value}${definitionControl?.unit || ''}`;
        host.view?.setOption?.(input.dataset.key, value);
      });
    });
  }

  async function activate(id) {
    const definition = byId.get(id);
    if (!definition) throw new Error(`未注册的可视化视图：${id}`);
    const currentToken = ++token;
    activeDefinition = definition;
    document.title = `bacmap · ${definition.title}`;
    $('crumb-sub').textContent = `ANALYSIS // ${definition.subtitle} · DEMO DATA`;

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
      await host.mount(definition, cache.get(id));
      if (currentToken !== token) return;
      renderSidebar(definition, cache.get(id));
      renderEmptyInspector();
      host.resize();
    } catch (error) {
      if (currentToken !== token) return;
      console.error(error);
      $('analysis-stats').innerHTML = `<div class="error-box">视图加载失败<br>${escapeHtml(error.message)}</div>`;
      $('analysis-controls').innerHTML = '';
    }
  }

  function deactivate() {
    token++;
    activeDefinition = null;
    host.deactivate();
    tooltip.style.display = 'none';
  }

  $('btn-analysis-reset').addEventListener('click', () => host.resetCamera());
  $('btn-analysis-auto').addEventListener('click', event => {
    host.controls.autoRotate = !host.controls.autoRotate;
    event.currentTarget.classList.toggle('on', host.controls.autoRotate);
  });
  $('btn-analysis-export').addEventListener('click', () => {
    if (host.view && activeDefinition) host.exportPng(`bacmap-${activeDefinition.id}.png`);
  });

  return {
    activate,
    deactivate,
    tick: dt => host.tick(dt),
    resize: () => host.resize(),
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
      selected: $('dock-sel').textContent,
    }),
  };
}
