/**
 * Shared 匹配表 right-panel component — the table of filter-matched records
 * used by phylo (matched leaves) and MST (matched sample records). Owns the
 * DOM, column picker, sort, collapse, keyboard browsing and TSV export; the
 * view supplies data and activation through the adapter and persists `state`.
 *
 * Full render() only on filter/column/sort/collapse changes — emphasis
 * changes dim rows via updateDim() without rebuilding.
 */
import { makeRowComparator } from './query.js';
import { escapeHtml } from './primitives.js';

// Live-filter the column-picker rows in place (same IME-safe trick as the
// filter editor — no re-render while typing).
function pickerFilterRows(blk, q) {
  for (const row of blk.querySelectorAll('[data-mpopt-row]')) {
    row.hidden = !!q && !(row.dataset.mpoptText || '').includes(q);
  }
  for (const g of blk.querySelectorAll('[data-mpopt-group]')) {
    g.hidden = ![...g.querySelectorAll('[data-mpopt-row]')].some(r => !r.hidden);
  }
}

/**
 * adapter = {
 *   state: { columns, sort, collapsed, colPickerOpen, colSearch },  // view-owned
 *   active() => boolean,               // false → panel hidden + emptied
 *   rows() => [row, ...],              // matched records, display order
 *   rowKey(row) => string,             // unique key for highlight/data attr
 *   leadingCols: [{ id, label, value(row) }],   // sticky first column(s)
 *   columns() => { options: [col], current: [col] },
 *   cellValue(col, row) => any,        // non-leading columns
 *   cellText(col, row) => string,
 *   title(k) => string,                // e.g. k => `匹配表 · ${k} 株`
 *   isDimmed(row) => boolean,          // excluded by another emphasis source
 *   isSelected(row) => boolean,
 *   activate(row),                     // click / Enter / arrows
 *   notify(),                          // host.notifyStateChange
 * }
 */
export function createMatchTable({ el, adapter }) {
  const state = adapter.state;
  let lastMs = 0;
  // normalize once so every code path (header, cells, sort, export) treats
  // leading columns uniformly — adapter-supplied objects lack the flag
  const leadingCols = adapter.leadingCols.map(c => ({ ...c, leading: true, kind: 'leading', type: 'text' }));

  const setVisible = on => {
    el.hidden = !on;
    el.parentElement?.classList.toggle('has-view-panel', on);
  };

  const colValue = (col, row) => col.leading ? col.value(row) : adapter.cellValue(col, row);
  const colText = (col, row) => col.leading ? (col.value(row) ?? '—') : adapter.cellText(col, row);

  function tableRows() {
    let rows = adapter.rows();
    const cols = adapter.columns().current;
    const all = [...leadingCols, ...cols];
    if (state.sort) {
      const col = all.find(c => c.id === state.sort.key);
      if (col) rows = [...rows].sort(makeRowComparator(col, state.sort.dir, (c2, row) => colValue(c2, row)));
    }
    return { rows, cols };
  }

  function renderPicker() {
    const { options, current } = adapter.columns();
    const ids = new Set(current.map(c => c.id));
    return `<input class="mst-search" type="search" placeholder="搜索列…" data-mp-colsearch value="${escapeHtml(state.colSearch)}">
      <div class="ring-col-list mp-collist"><div data-mpopt-group>${options.map(c =>
        `<label class="cat-row" data-mpopt-row data-mpopt-text="${escapeHtml(`${c.id} ${c.label}`.toLowerCase())}"><input type="checkbox" data-mp-col="${escapeHtml(c.id)}" ${ids.has(c.id) ? 'checked' : ''}><span class="ring-col-name">${escapeHtml(c.label)}</span></label>`).join('')}
      </div></div>`;
  }

  function render() {
    if (!el) return;
    if (!adapter.active()) { el.innerHTML = ''; setVisible(false); return; }
    const t0 = performance.now();
    const { rows, cols } = tableRows();
    const k = rows.length;
    const sortMark = id => (state.sort?.key === id ? (state.sort.dir > 0 ? ' ▲' : ' ▼') : '');
    el.innerHTML = `<div class="mp-head"><span class="t">${escapeHtml(adapter.title(k))}</span><span class="mp-actions">
        <button type="button" data-mp-cols title="选择列">列</button>
        <button type="button" data-mp-export title="导出 TSV">TSV</button>
        <button type="button" data-mp-collapse title="折叠">${state.collapsed ? '▸' : '▾'}</button>
      </span></div>
      ${state.colPickerOpen ? renderPicker() : ''}
      ${state.collapsed ? '' : `<div class="mp-scroll" tabindex="0"><table class="mp-table"><thead><tr>
        ${leadingCols.map((c, i) => `<th${i === 0 ? ' class="mp-name"' : ''} data-mp-sort="${escapeHtml(c.id)}" title="排序">${escapeHtml(c.label)}${sortMark(c.id)}</th>`).join('')}
        ${cols.map(c => `<th data-mp-sort="${escapeHtml(c.id)}" title="排序">${escapeHtml(c.label)}${sortMark(c.id)}</th>`).join('')}
        </tr></thead><tbody>
        ${rows.map(row => `<tr data-mp-row data-node="${escapeHtml(adapter.rowKey(row))}" class="${adapter.isDimmed(row) ? 'dim' : ''}${adapter.isSelected(row) ? ' sel' : ''}">
          ${leadingCols.map((c, i) => `<td${i === 0 ? ' class="mp-name"' : ''}>${escapeHtml(String(colText(c, row)))}</td>`).join('')}
          ${cols.map(c => { const v = adapter.cellValue(c, row);
            const extra = adapter.cellClass?.(c, row, v) || '';
            return `<td class="${v === null || v === undefined ? 'mp-null' : ''}${extra ? ` ${extra}` : ''}">${escapeHtml(adapter.cellText(c, row))}</td>`; }).join('')}
        </tr>`).join('')}
        </tbody></table></div>`}`;
    setVisible(true);
    if (state.colSearch) pickerFilterRows(el, state.colSearch);
    lastMs = performance.now() - t0;
  }

  // Emphasis changes only dim rows — no rebuild.
  function updateDim() {
    if (!el || el.hidden) return;
    const rows = adapter.rows();
    const byKey = new Map(rows.map(r => [String(adapter.rowKey(r)), r]));
    for (const tr of el.querySelectorAll('tr[data-mp-row]')) {
      const row = byKey.get(tr.dataset.node);
      if (row) tr.classList.toggle('dim', adapter.isDimmed(row));
    }
  }

  function highlight(keys) {
    if (!el || el.hidden) return;
    el.querySelector('tr.sel')?.classList.remove('sel');
    const list = Array.isArray(keys) ? keys : [keys];
    let first = null;
    for (const key of list) {
      const tr = el.querySelector(`tr[data-node="${CSS.escape(String(key))}"]`);
      if (tr) { tr.classList.add('sel'); first ||= tr; }
    }
    first?.scrollIntoView({ block: 'nearest' });
  }

  function exportTsv() {
    const { rows, cols } = tableRows();
    const all = [...leadingCols, ...cols];
    const lines = [all.map(c => c.label),
      ...rows.map(row => all.map(c => colText(c, row)))];
    const tsv = '\ufeff' + lines.map(r => r.map(v => String(v).replace(/[\t\n\r]/g, ' ')).join('\t')).join('\n');
    const url = URL.createObjectURL(new Blob([tsv], { type: 'text/tab-separated-values;charset=utf-8' }));
    const a = el.ownerDocument.createElement('a');
    a.href = url;
    a.download = `gvixb-matched-${rows.length}.tsv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  el.onclick = ev => {
    const t = ev.target;
    if (t.hasAttribute('data-mp-cols')) { state.colPickerOpen = !state.colPickerOpen; render(); }
    else if (t.hasAttribute('data-mp-export')) exportTsv();
    else if (t.hasAttribute('data-mp-collapse')) { state.collapsed = !state.collapsed; render(); adapter.notify(); }
    else if (t.dataset.mpSort) {
      state.sort = state.sort?.key === t.dataset.mpSort
        ? { key: t.dataset.mpSort, dir: -state.sort.dir }
        : { key: t.dataset.mpSort, dir: 1 };
      render();
      adapter.notify();
    } else {
      const tr = t.closest('tr[data-mp-row]');
      if (!tr) return;
      const row = adapter.rows().find(r => String(adapter.rowKey(r)) === tr.dataset.node);
      if (row) adapter.activate(row);
    }
  };
  el.onchange = ev => {
    const t = ev.target;
    if (!t.dataset.mpCol) return;
    const ids = new Set(state.columns || adapter.columns().current.map(c => c.id));
    if (t.checked) ids.add(t.dataset.mpCol); else ids.delete(t.dataset.mpCol);
    state.columns = [...ids];
    render();
    adapter.notify();
  };
  el.oninput = ev => {
    if (ev.isComposing) return;
    const t = ev.target;
    if (t.dataset.mpColsearch !== undefined) {
      state.colSearch = t.value.trim().toLowerCase();
      pickerFilterRows(el, state.colSearch);
    }
  };
  el.onkeydown = ev => {
    if (!['ArrowUp', 'ArrowDown', 'Enter'].includes(ev.key)) return;
    const trs = [...el.querySelectorAll('tr[data-mp-row]')];
    if (!trs.length) return;
    ev.preventDefault();
    const rows = adapter.rows();
    const byKey = new Map(rows.map(r => [String(adapter.rowKey(r)), r]));
    const idx = trs.findIndex(r => r.classList.contains('sel'));
    if (ev.key === 'Enter' && idx >= 0) { trs[idx].dispatchEvent(new MouseEvent('click', { bubbles: true })); return; }
    const next = ev.key === 'ArrowDown'
      ? trs[Math.min(trs.length - 1, idx + 1)]
      : trs[Math.max(0, idx - 1)];
    const row = byKey.get(next.dataset.node);
    if (row) adapter.activate(row);
  };

  return { render, updateDim, highlight, state, get lastMs() { return lastMs; } };
}
