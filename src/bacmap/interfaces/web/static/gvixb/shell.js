/**
 * Default DOM shell.
 *
 * The runtime core never queries the document directly. `gvixb-app.js` (or any
 * host that wants the built-in shell) calls `createShellPort(root)` and passes
 * the resulting element map to `createAnalysisFramework`.
 *
 * The shell contract is intentionally just a set of element IDs so a host can
 * either reuse the shipped template or provide its own markup. Every element is
 * optional at the port level; the framework degrades gracefully when a host
 * omits a readout or action button.
 */
const SHELL_IDS = [
  'tooltip',
  'analysis-kicker',
  'analysis-title',
  'analysis-description',
  'analysis-stats',
  'analysis-lists',
  'analysis-controls',
  'analysis-source',
  'analysis-head',
  'analysis-panel',
  'analysis-body',
  'dock-sel',
  'dock-zoom',
  'btn-analysis-auto',
  'btn-analysis-reset',
  'btn-analysis-export',
  'crumb-sub',
];

export function createShellPort(root) {
  if (!root || !root.ownerDocument) {
    throw new TypeError('createShellPort: root must be a DOM element');
  }
  const document = root.ownerDocument;
  const lookup = id => (root.id === id ? root : root.querySelector(`#${id}`)) || document.getElementById(id);
  const elements = Object.fromEntries(SHELL_IDS.map(id => [id, lookup(id)]));
  return {
    root,
    elements,
    missing: SHELL_IDS.filter(id => !elements[id]),
  };
}

export { SHELL_IDS };
