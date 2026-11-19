/**
 * `gvixb.phylogeny` payload normalization.
 *
 * `toPhylogenyV2` is pure: v2 payloads pass through unchanged and v1 payloads
 * are converted following docs/data-contracts.md §3.8. The only inference it
 * performs is the documented internal-label heuristic — all-numeric (or
 * slash-separated numeric) internal labels are treated as support values,
 * everything else stays a node name.
 */
import { parseNewick } from '../framework/algorithms.js';

const SUPPORT_LABEL = /^\d+(\.\d+)?(\/\d+(\.\d+)?)*$/;

/** v1 → v2 internal-label heuristic; returns a support spec or null. */
function detectV1Support(newick) {
  let root;
  try {
    root = parseNewick(newick);
  } catch {
    return null;
  }
  const labels = [];
  (function walk(node, isRoot) {
    if (node.children?.length) {
      if (!isRoot && node.name) labels.push(node.name);
      node.children.forEach(child => walk(child, false));
    }
  })(root, true);
  if (!labels.length || !labels.every(label => SUPPORT_LABEL.test(label))) return null;
  const parts = labels[0].split('/').length;
  const names = parts === 1
    ? ['support']
    : parts === 2
      ? ['SH-aLRT', 'UFBoot']
      : Array.from({ length: parts }, (_, i) => `support ${i + 1}`);
  const overOne = labels.some(label => label.split('/').some(part => Number(part) > 1));
  return { labels: names, scale: overOne ? 100 : 1 };
}

function fromV1(data) {
  const summary = {};
  const copy = [['organism', 'organism'], ['n_snp_sites', 'n_snp_sites'], ['n_loci', 'n_loci'], ['scheme', 'scheme'], ['missing_rate', 'missing_rate']];
  for (const [from, to] of copy) {
    if (data[from] !== undefined && data[from] !== null && data[from] !== '') summary[to] = data[from];
  }
  if (Array.isArray(data.samples)) summary.n_samples = data.samples.length;
  const tree = {
    newick: data.newick,
    kind: 'inferred',
    root: { status: 'unknown' },
    branch_length: { unit: 'unknown', label: data.distanceLabel || '分支长度' },
  };
  const support = detectV1Support(data.newick);
  if (support) tree.support = support;
  const out = {
    schema: 'gvixb.phylogeny/v2',
    tree,
    metadata: data.metadata || {},
    summary,
  };
  if (data.demo !== undefined) out.demo = data.demo;
  if (data.title !== undefined) out.title = data.title;
  if (data.source !== undefined) out.source = data.source;
  return out;
}

/**
 * Normalize any accepted phylogeny payload to `gvixb.phylogeny/v2`.
 * Throws on an unrecognised schema so callers fail loudly.
 */
export function toPhylogenyV2(data) {
  if (data?.schema === 'gvixb.phylogeny/v2') return data;
  if (data?.schema === 'gvixb.phylogeny/v1') return fromV1(data);
  throw new Error(`无法识别的 phylogeny schema：${data?.schema ?? '缺失'}`);
}
