import * as THREE from './lib/three.module.js';
import { OrbitControls } from './lib/OrbitControls.js';
import { EffectComposer } from './lib/postprocessing/EffectComposer.js';
import { RenderPass } from './lib/postprocessing/RenderPass.js';
import { UnrealBloomPass } from './lib/postprocessing/UnrealBloomPass.js';
import { OutputPass } from './lib/postprocessing/OutputPass.js';
import { createAnalysisFramework } from './framework/analysis-framework.js';

// ---------------------------------------------------------------------------
// functional-category palette (AMR / virulence are deliberately the hottest)
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// palette — dark instrument theme
// ---------------------------------------------------------------------------
const THEME = {
  paper: 0x05070d,
  paperCss: '#05070d',
  slab: 0x0b111f,
  disc: 0x080c15,      // instrument face, just above the page black
  bezel: 0x0c1220,     // mechanical ring
  mark: 0x9fb0e0,      // engraved marks
  accent: 0x6d8bff,
  accent2: 0x53e6ff,
};

/** colours used by the 2D linear canvas */
const INK = {
  bg: 'transparent',
  frame: 'rgba(120,160,255,0.22)',
  grid: 'rgba(120,160,255,0.10)',
  text: '#7e8bb0',
  textDim: '#4c587a',
  strong: '#eef2ff',
  axis: 'rgba(120,160,255,0.35)',
  gcStrip: 'rgba(255,255,255,0.03)',
  gcLine: '#4dd6a0',
  select: '#ffffff',
  selectRing: '#53e6ff',
};
// NCBI COG 2020 one-letter functional categories (authoritative, see README).
// `flag` colours (amr/vir) are a separate heuristic clinical overlay.
// COG 2020 categories, coloured by the FOUR official COG functional families so
// the ring is readable as a functional map rather than 26 random hues:
//   info      Information storage & processing  (J A K L B)  -> indigo / blue
//   cellular  Cellular processes & signalling   (D M N O T U V W Y Z) -> teal
//   metab     Metabolism                        (C E F G H I P Q)   -> green-yellow
//   poor      Poorly characterized              (R S X)             -> neutral grey
// amr / vir are a separate clinical overlay and keep the only hot reds/oranges.
const CAT = {
  amr: { hex: 0xff2d55, label: 'AMR 耐药', flag: 1, fam: 'flag' },
  vir: { hex: 0xff8a3d, label: '毒力', flag: 1, fam: 'flag' },

  J: { hex: 0x5ee0ff, label: '翻译/核糖体', fam: 'info' },
  A: { hex: 0x8b9cff, label: 'RNA 加工', fam: 'info' },
  K: { hex: 0xa78bfa, label: '转录', fam: 'info' },
  L: { hex: 0x7c6cf5, label: '复制/修复', fam: 'info' },
  B: { hex: 0x6b6f9a, label: '染色质', fam: 'info' },

  M: { hex: 0x2ec4b6, label: '细胞壁/膜', fam: 'cellular' },
  D: { hex: 0x33b4c9, label: '细胞周期/分裂', fam: 'cellular' },
  N: { hex: 0x35d0a8, label: '细胞运动', fam: 'cellular' },
  O: { hex: 0x4ec9d8, label: '翻译后修饰/伴侣', fam: 'cellular' },
  T: { hex: 0x3f9fd0, label: '信号转导', fam: 'cellular' },
  U: { hex: 0x5a8fc8, label: '分泌/运输', fam: 'cellular' },
  V: { hex: 0x8f6f9e, label: '防御机制(COG V)', fam: 'cellular' },
  W: { hex: 0x7f8ea8, label: '胞外结构', fam: 'cellular' },
  Y: { hex: 0x5f6f8f, label: '核结构', fam: 'cellular' },
  Z: { hex: 0x6f8f9f, label: '细胞骨架', fam: 'cellular' },

  C: { hex: 0xd8d44d, label: '能量产生', fam: 'metab' },
  E: { hex: 0xb4d64d, label: '氨基酸代谢', fam: 'metab' },
  F: { hex: 0x8fd64d, label: '核苷酸代谢', fam: 'metab' },
  G: { hex: 0x62d465, label: '糖类代谢', fam: 'metab' },
  H: { hex: 0xa8d64d, label: '辅酶代谢', fam: 'metab' },
  I: { hex: 0xcfd44d, label: '脂类代谢', fam: 'metab' },
  P: { hex: 0x74d6a0, label: '无机离子转运', fam: 'metab' },
  Q: { hex: 0xc0b44d, label: '次级代谢产物', fam: 'metab' },

  R: { hex: 0x6b7590, label: '仅一般功能预测', fam: 'poor' },
  S: { hex: 0x55607d, label: 'COG 功能未知', fam: 'poor' },
  X: { hex: 0x8b7ba8, label: '可移动元件', fam: 'poor' },

  trna:   { hex: 0x4de8ff, label: 'tRNA', fam: 'nc' },
  rrna:   { hex: 0x2ee6c0, label: 'rRNA', fam: 'nc' },
  ncrna:  { hex: 0x3ee0d0, label: 'ncRNA', fam: 'nc' },
  pseudo: { hex: 0x424d68, label: '假基因', fam: 'nc' },
  unknown:{ hex: 0x3d465c, label: '无 COG 注释', fam: 'nc' },
};
const COG_FAMILY = {
  flag: '临床高亮 · Clinical',
  info: '信息存储与加工 · COG J A K L B',
  cellular: '细胞过程与信号 · COG D M N O T U V W Y Z',
  metab: '代谢 · COG C E F G H I P Q',
  poor: '功能未充分表征 · COG R S X',
  nc: '非编码 / 无 COG',
};
const css = (hex) => '#' + hex.toString(16).padStart(6, '0');
const catHex = (cat) => (CAT[cat] ?? CAT.unknown).hex;
const catLabel = (cat) => (CAT[cat] ?? CAT.unknown).label;
/** colour of a feature: clinical flag wins, else its COG category */
const featHex = (f) => catHex(f.flag || f.cat);

// ring geometry (base units at scale 1)
const R = {
  gcSkew: 3.55, gcSkewW: 0.42,
  gcCont: 4.10, gcContW: 0.46,
  minusInner: 5.30, minusOuter: 5.80,
  backboneInner: 5.80, backboneOuter: 7.00,
  plusInner: 7.00, plusOuter: 7.50,
  // mechanical bezel
  hair1: 7.58, hair2: 7.88, hair3: 8.10,
  bezelInner: 8.18, bezelOuter: 9.22,
  tickIn: 8.78, tickOut: 9.14,
  labelR: 8.46,
  discR: 9.22,
};
const FEATURE_DEPTH = 0.34;
const BAND_THICKNESS = 0.5;
const MIN_WIDTH = 0.0035;
// LOD: below this camera distance individual genes are drawn, above it the ring
// is rendered as ~1.5 px category bins (4,555 genes cannot be legible at once).
const LOD_GENE_DISTANCE = 19;

// per-replicon placement: chromosome hero + plasmid off to the side
const LAYOUT = [
  { cx: 0, cy: 0, scale: 1 },
  { cx: -12.6, cy: 5.0, scale: 0.33 },
];

// ---------------------------------------------------------------------------
// dna helpers
// ---------------------------------------------------------------------------
const CODON = {
  TTT:'F',TTC:'F',TTA:'L',TTG:'L',TCT:'S',TCC:'S',TCA:'S',TCG:'S',TAT:'Y',TAC:'Y',TAA:'*',TAG:'*',TGT:'C',TGC:'C',TGA:'*',TGG:'W',
  CTT:'L',CTC:'L',CTA:'L',CTG:'L',CCT:'P',CCC:'P',CCA:'P',CCG:'P',CAT:'H',CAC:'H',CAA:'Q',CAG:'Q',CGT:'R',CGC:'R',CGA:'R',CGG:'R',
  ATT:'I',ATC:'I',ATA:'I',ATG:'M',ACT:'T',ACC:'T',ACA:'T',ACG:'T',AAT:'N',AAC:'N',AAA:'K',AAG:'K',AGT:'S',AGC:'S',AGA:'R',AGG:'R',
  GTT:'V',GTC:'V',GTA:'V',GTG:'V',GCT:'A',GCC:'A',GCA:'A',GCG:'A',GAT:'D',GAC:'D',GAA:'E',GAG:'E',GGT:'G',GGC:'G',GGA:'G',GGG:'G',
};
function revcomp(seq) {
  const c = { A:'T',T:'A',G:'C',C:'G',N:'N',a:'t',t:'a',g:'c',c:'g',n:'n' };
  let out = '';
  for (let i = seq.length - 1; i >= 0; i--) out += (c[seq[i]] ?? 'N');
  return out;
}
function translate(seq) {
  const aa = [];
  for (let i = 0; i + 3 <= seq.length; i += 3) {
    let a = CODON[seq.slice(i, i + 3)] ?? 'X';
    if (i === 0) a = 'M';
    aa.push(a);
  }
  return aa;
}
const fmt = (n) => n.toLocaleString('en-US');
const kb = (n) => n >= 1e6 ? (n / 1e6).toFixed(2) + ' Mb' : (n / 1e3).toFixed(1) + ' kb';
function brighten(hex, t) {
  const r = (hex >> 16) & 255, g = (hex >> 8) & 255, b = hex & 255;
  return ((Math.round(r + (255 - r) * t)) << 16) |
         ((Math.round(g + (255 - g) * t)) << 8) |
         (Math.round(b + (255 - b) * t));
}
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

// ---------------------------------------------------------------------------
// geometry helpers
// ---------------------------------------------------------------------------
function pushTri(pos, col, a, b, c, rgb) {
  for (const v of [a, b, c]) { pos.push(v[0], v[1], v[2]); col.push(rgb[0], rgb[1], rgb[2]); }
}
function addAnnularSector(pos, col, r0, r1, a0, a1, z, rgb, cx = 0, cy = 0) {
  const steps = Math.max(2, Math.ceil((a1 - a0) / 0.015));
  for (let i = 0; i < steps; i++) {
    const t0 = a0 + (a1 - a0) * i / steps;
    const t1 = a0 + (a1 - a0) * (i + 1) / steps;
    const i0 = [cx + Math.cos(t0) * r0, cy - Math.sin(t0) * r0, z];
    const o0 = [cx + Math.cos(t0) * r1, cy - Math.sin(t0) * r1, z];
    const i1 = [cx + Math.cos(t1) * r0, cy - Math.sin(t1) * r0, z];
    const o1 = [cx + Math.cos(t1) * r1, cy - Math.sin(t1) * r1, z];
    pushTri(pos, col, i0, o0, i1, rgb);
    pushTri(pos, col, i1, o0, o1, rgb);
  }
}
function circlePoints(r, z, seg = 320, cx = 0, cy = 0) {
  const pts = [];
  for (let i = 0; i < seg; i++) {
    const a = (i / seg) * Math.PI * 2;
    pts.push(new THREE.Vector3(cx + Math.cos(a) * r, cy - Math.sin(a) * r, z));
  }
  return pts;
}

// ---------------------------------------------------------------------------
// bootstrap
// ---------------------------------------------------------------------------
const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(THEME.paper, 1);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400);
const HOME_CAM = new THREE.Vector3(0.5, 8.5, 36);
camera.position.set(0.5, 8.5, 36);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.07;
controls.minDistance = 3;
controls.maxDistance = 90;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.4;
controls.target.set(0.5, 1.0, 0);
controls.enabled = false;

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
// gentle bloom: only the brightest features and the accent marks glow
const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.30, 0.34, 0.80);
composer.addPass(bloom);
composer.addPass(new OutputPass());

let DATA = null;
const featureGroup = new THREE.Group();
const binnedGroup = new THREE.Group();
const atmosphereGroup = new THREE.Group();
const gcGroup = new THREE.Group();
scene.add(featureGroup, binnedGroup, atmosphereGroup, gcGroup);

const fAngle = [], fRmid = [], fWidth = [], fRep = [], fCx = [], fCy = [];
const fAng0 = [], fAng1 = [];
let featureMesh = null;
let selArc = null;
let hoverId = -1, selectedId = -1;
let selectedLabel = null, selectedLine = null;
let selectedReplicon = 0;
const repliconLabels = [];
const bezelLabels = [];

// COG category filter.
//   filterOn = false           -> no filtering at all, everything opaque
//   filterOn = true            -> only the categories in catFilter stay opaque
//   filterOn = true, set empty -> 全不选: every category drops to alpha 0.10
// "no filter" and "nothing selected" therefore look different, which is what the
// 全选 / 全不选 buttons need.
const catFilter = new Set();
let filterOn = false;
const FILTER_ALPHA = 0.10;

function featureKey(f) { return f.flag || f.cat; }

/** Re-apply the filter to the gene blocks and rebuild the binned rings. */
function applyCatFilter() {
  if (featureMesh) {
    const attr = featureMesh.geometry.getAttribute('aAlpha');
    for (let i = 0; i < DATA.features.length; i++) {
      const on = !filterOn || catFilter.has(featureKey(DATA.features[i]));
      attr.array[i] = on ? 1.0 : FILTER_ALPHA;
    }
    attr.needsUpdate = true;
  }
  // the binned ring is what you see at overview zoom, so it must follow too
  for (const m of [...binnedGroup.children]) {
    binnedGroup.remove(m);
    m.geometry.dispose();
    m.material.dispose();
  }
  for (let ri = 0; ri < DATA.replicons.length; ri++) {
    const { cx, cy, scale } = layoutOf(ri);
    buildBinnedRing(ri, DATA.replicons[ri], cx, cy, scale);
  }
}

function toggleCatFilter(key) {
  filterOn = true;
  if (catFilter.has(key)) catFilter.delete(key);
  else catFilter.add(key);
  // toggling the last selected category off returns to "show everything"
  if (catFilter.size === 0) filterOn = false;
  renderLegend();
  applyCatFilter();
  renderGeneList();
}

/** 全选: every present category stays opaque (visually same as no filter). */
function selectAllCats() {
  filterOn = true;
  catFilter.clear();
  for (const k of presentCats()) catFilter.add(k);
  renderLegend();
  applyCatFilter();
  renderGeneList();
}

/** 全不选: nothing is selected, so every category fades to alpha 0.10. */
function selectNoCats() {
  filterOn = true;
  catFilter.clear();
  renderLegend();
  applyCatFilter();
  renderGeneList();
}

/** 重置: turn the filter off entirely. */
function resetCatFilter() {
  filterOn = false;
  catFilter.clear();
  renderLegend();
  applyCatFilter();
  renderGeneList();
}

function presentCats() {
  const seen = new Set();
  for (const f of DATA.features) seen.add(featureKey(f));
  return LEGEND_ORDER.filter(k => seen.has(k));
}

// ---------------------------------------------------------------------------
// atmosphere: deep-space depth (soft lens glow + drifting dust) and the bezel
// ---------------------------------------------------------------------------
function makeRadialSprite(size, stops, blending = THREE.AdditiveBlending) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 256;
  const ctx = cv.getContext('2d');
  const g = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
  for (const [pos, col] of stops) g.addColorStop(pos, col);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 256);
  const tex = new THREE.CanvasTexture(cv);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, transparent: true, depthWrite: false, blending,
  }));
  sp.scale.set(size, size, 1);
  return sp;
}

/**
 * Tight ring glow. Two rules learned from the earlier attempts:
 *  1. no filled disc — it flattens the scene into a pale circle;
 *  2. no wide, uniform halo — additive fog over the whole viewport reads as
 *     "a bright screen", not as light emitted by the ring.
 * So the falloff is narrow (the glow dies out within ~1.35x the ring radius)
 * and the peak sits exactly on the feature bands.
 */
function makeFaceGlow(scale) {
  const S = R.discR * 2.05 * scale;          // much tighter than before
  const peak = (2 * 7.25 * scale) / S;
  const sp = makeRadialSprite(S, [
    [0.00, 'rgba(0,0,0,0)'],
    [Math.max(0.05, peak * 0.62), 'rgba(20,32,74,0.02)'],
    [Math.max(0.10, peak * 0.86), 'rgba(34,54,120,0.07)'],
    [Math.min(0.96, peak * 1.00), 'rgba(40,64,142,0.10)'],
    [Math.min(0.99, peak * 1.14), 'rgba(24,40,92,0.03)'],
    [1.00, 'rgba(0,0,0,0)'],
  ]);
  sp.position.z = -3.0;
  return sp;
}

/** Very faint ambient lift behind the object — barely visible, just avoids
 *  the ring looking pasted onto flat black. */
function makeHalo() {
  const sp = makeRadialSprite(30, [
    [0.00, 'rgba(0,0,0,0)'],
    [0.55, 'rgba(0,0,0,0)'],
    [0.72, 'rgba(30,46,110,0.035)'],
    [0.86, 'rgba(44,70,160,0.05)'],
    [1.00, 'rgba(0,0,0,0)'],
  ]);
  sp.position.z = -6;
  return sp;
}

function makeDust() {
  const n = 320;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const r = 12 + Math.random() * 30;
    const th = Math.random() * Math.PI * 2;
    const ph = Math.random() * Math.PI;
    pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
    pos[i * 3 + 1] = r * Math.cos(ph);
    pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th) - 8;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  return new THREE.Points(g, new THREE.PointsMaterial({
    color: 0x7f9ad8, size: 0.05, transparent: true, opacity: 0.16,
    blending: THREE.AdditiveBlending, depthWrite: false,
  }));
}

const halo = makeHalo();
const dust = makeDust();
atmosphereGroup.add(halo, dust);
/** Mechanical bezel ring around each replicon — marks float, no solid face. */
function buildBezel(ri, rep, cx, cy, scale) {
  const TWO_PI = Math.PI * 2;
  const sr = (v) => v * scale;
  const pos = [], col = [];

  // soft glow lens instead of a hard black disc (keeps the 3D space feel)
  const face = makeFaceGlow(scale);
  face.position.set(cx, cy, -3.0);
  featureGroup.add(face);

  // engraved hairlines inside the face
  for (const r of [R.hair1, R.hair2, R.hair3]) {
    addAnnularSector(pos, col, sr(r), sr(r) + 0.012 * scale, 0, TWO_PI, -0.03,
      hexRgb(0x1b2436), cx, cy);
  }

  // bezel band: a faint outline only, not a filled slab
  addAnnularSector(pos, col, sr(R.bezelInner), sr(R.bezelInner) + 0.035 * scale, 0, TWO_PI, -0.02,
    hexRgb(0x3d4d75), cx, cy);
  addAnnularSector(pos, col, sr(R.bezelOuter) - 0.035 * scale, sr(R.bezelOuter), 0, TWO_PI, -0.02,
    hexRgb(0x3d4d75), cx, cy);

  // ---- scale: genomic coordinates, not degrees ------------------------------
  // A genome atlas must read in bp. Major ticks are labelled, minor/sub ticks
  // subdivide them 5x and 25x.
  const len = rep.len;
  // aim for ~9 labelled ticks on the chromosome, ~6 on the small plasmid
  const major = niceStepFor(len, scale < 0.6 ? 6 : 9);
  const minor = major / 5;
  const sub = major / 25;
  const angOf = (bp) => (bp / len) * TWO_PI;

  // sub ticks
  for (let bp = 0; bp < len; bp += sub) {
    const a0 = angOf(bp);
    addAnnularSector(pos, col, sr(R.tickIn), sr(R.tickOut - 0.115), a0, a0 + 0.0016, 0,
      hexRgb(0x28324a), cx, cy);
  }
  // minor ticks
  for (let bp = 0; bp < len; bp += minor) {
    const a0 = angOf(bp);
    addAnnularSector(pos, col, sr(R.tickIn), sr(R.tickOut - 0.06), a0, a0 + 0.0022, 0,
      hexRgb(0x4a5a80), cx, cy);
  }
  // major ticks + labels
  for (let bp = 0; bp <= len; bp += major) {
    const a0 = angOf(bp);
    addAnnularSector(pos, col, sr(R.tickIn), sr(R.tickOut), a0, a0 + 0.0030, 0,
      hexRgb(0x9aabd8), cx, cy);
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  featureGroup.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide,
  })));

  // coordinate labels (sized to stay legible at the default zoom)
  for (let bp = 0; bp <= len; bp += major) {
    const a = angOf(bp);
    const lab = makeTextSprite(fmtBp(bp, len), 'rgba(178,192,232,0.85)', 30,
      0.34 * Math.max(0.72, scale));
    lab.position.set(cx + Math.cos(a) * sr(R.labelR), cy - Math.sin(a) * sr(R.labelR), 0.03);
    featureGroup.add(lab);
    bezelLabels.push(lab);
  }
}

// ---------------------------------------------------------------------------
// text sprites
// ---------------------------------------------------------------------------
/**
 * Text sprites sized by real glyph metrics.
 *
 * The previous version drew into a fixed 512x80 canvas, so a short string like
 * "0.5 Mb" occupied only ~6% of the texture width — after scaling the glyphs
 * were 3 px tall and effectively invisible. Now the canvas hugs the text and
 * `hUnits` is the world-space height of the glyphs themselves.
 */
function makeTextTexture(text, color, fontPx = 30) {
  const font = `600 ${fontPx}px ui-monospace, Menlo, Consolas, monospace`;
  let cv = document.createElement('canvas');
  let ctx = cv.getContext('2d');
  ctx.font = font;
  const tw = Math.ceil(ctx.measureText(text).width) + 10;
  const th = Math.ceil(fontPx * 1.30);
  cv.width = tw; cv.height = th;
  ctx = cv.getContext('2d');
  ctx.font = font;
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, tw / 2, th / 2);
  const tex = new THREE.CanvasTexture(cv);
  tex.minFilter = THREE.LinearFilter;
  tex.aspect = tw / th;
  return tex;
}

/** hUnits = world height of the text; width follows automatically. */
function makeTextSprite(text, color, fontPx = 30, hUnits = 0.5) {
  const tex = makeTextTexture(text, color, fontPx);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, transparent: true, depthTest: false,
  }));
  sp.scale.set(hUnits * tex.aspect, hUnits, 1);
  return sp;
}

function setSpriteText(sprite, text, color, fontPx = 30, hUnits = null) {
  sprite.material.map?.dispose();
  const tex = makeTextTexture(text, color, fontPx);
  sprite.material.map = tex;
  sprite.material.needsUpdate = true;
  if (hUnits) sprite.scale.set(hUnits * tex.aspect, hUnits, 1);
}

// ---------------------------------------------------------------------------
// build
// ---------------------------------------------------------------------------
const layoutOf = (ri) => LAYOUT[ri] ?? LAYOUT[LAYOUT.length - 1];

function build() {
  const TWO_PI = Math.PI * 2;

  for (let ri = 0; ri < DATA.replicons.length; ri++) {
    const rep = DATA.replicons[ri];
    const { cx, cy, scale } = layoutOf(ri);
    const sr = (v) => v * scale;

    // ---- backbone: per-backbone segments with subtle shade variation
    const bPos = [], bCol = [];
    const SEG = 60;
    for (let s = 0; s < SEG; s++) {
      const a0 = (s / SEG) * TWO_PI, a1 = ((s + 1) / SEG) * TWO_PI;
      const shade = 0.09 + 0.03 * ((s * 7919) % 5) / 4;
      addAnnularSector(bPos, bCol, sr(R.backboneInner), sr(R.backboneOuter), a0, a1, 0,
        [srgbToLinear(shade), srgbToLinear(shade + 0.016), srgbToLinear(shade + 0.045)], cx, cy);
    }
    const bGeo = new THREE.BufferGeometry();
    bGeo.setAttribute('position', new THREE.Float32BufferAttribute(bPos, 3));
    bGeo.setAttribute('color', new THREE.Float32BufferAttribute(bCol, 3));
    featureGroup.add(new THREE.Mesh(bGeo, new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide,
    })));

    // ---- glowing mid line
    featureGroup.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(
        circlePoints(sr((R.backboneInner + R.backboneOuter) / 2), 0.02, 320, cx, cy)),
      new THREE.LineBasicMaterial({
        color: 0x3b4ba8, transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending,
      })));

    // ---- reference circles
    const lineMat = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.05 });
    for (const r of [R.minusInner, R.minusOuter, R.backboneInner, R.backboneOuter, R.plusInner, R.plusOuter]) {
      featureGroup.add(new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints(circlePoints(sr(r), 0.01, 320, cx, cy)), lineMat));
    }
    // ---- tick ring
    const tickPts = [];
    for (let d = 0; d < 360; d += 10) {
      const a = (d / 360) * TWO_PI;
      tickPts.push(new THREE.Vector3(cx + Math.cos(a) * sr(R.tickInner), cy - Math.sin(a) * sr(R.tickInner), 0.01));
      tickPts.push(new THREE.Vector3(cx + Math.cos(a) * sr(R.tickOuter), cy - Math.sin(a) * sr(R.tickOuter), 0.01));
    }
    featureGroup.add(new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints(tickPts), lineMat));

    // ---- replicon label, placed in the empty centre hole
    const lab = makeTextSprite(rep.name, 'rgba(140,152,188,0.9)', 30, 0.62 * scale);
    lab.position.set(cx, cy - sr(2.1), 0.02);
    featureGroup.add(lab);
    repliconLabels.push(lab);

    // ---- mechanical bezel
    buildBezel(ri, rep, cx, cy, scale);

    // ---- GC content + GC skew tracks
    buildGcTracks(ri, rep, cx, cy, scale);

    // ---- binned category ring (overview LOD)
    buildBinnedRing(ri, rep, cx, cy, scale);
  }

  // ---- features: ONE InstancedMesh for every replicon (single draw call)
  const n = DATA.features.length;
  featureMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), makeGeneMaterial(), n);
  // per-instance alpha drives the COG category filter
  featureMesh.geometry.setAttribute('aAlpha',
    new THREE.InstancedBufferAttribute(new Float32Array(n).fill(1), 1));
  featureMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  featureMesh.count = n;

  const tmpM = new THREE.Matrix4();
  const t = new THREE.Vector3(), r = new THREE.Vector3(), nrm = new THREE.Vector3(0, 0, 1);
  const p = new THREE.Vector3();

  for (let i = 0; i < n; i++) {
    const f = DATA.features[i];
    const rep = DATA.replicons[f.r];
    const { cx, cy, scale } = layoutOf(f.r);
    const ang = (f.s / rep.len) * TWO_PI;
    const ang1 = (f.e / rep.len) * TWO_PI;
    const mid = (ang + ang1) / 2;
    const plus = f.strand === '+';
    const rMid = scale * (plus ? (R.plusInner + R.plusOuter) / 2 : (R.minusInner + R.minusOuter) / 2);
    const width = Math.max(MIN_WIDTH * scale, 2 * rMid * Math.sin((ang1 - ang) / 2));

    fAngle.push(mid); fRmid.push(rMid); fWidth.push(width);
    fRep.push(f.r); fCx.push(cx); fCy.push(cy);
    fAng0.push(ang); fAng1.push(ang1);
    const c = Math.cos(mid), s = Math.sin(mid);
    p.set(cx + c * rMid, cy - s * rMid, FEATURE_DEPTH / 2);
    t.set(-s, -c, 0);
    r.set(c, -s, 0);
    tmpM.makeBasis(t, r, nrm);
    tmpM.scale(new THREE.Vector3(width, BAND_THICKNESS * scale, FEATURE_DEPTH));
    tmpM.setPosition(p);
    featureMesh.setMatrixAt(i, tmpM);
    setFeatureColor(i, featHex(f));
  }
  featureMesh.instanceMatrix.needsUpdate = true;
  featureGroup.add(featureMesh);
}

// Binned category ring: one arc per bin, coloured by the dominant functional
// category of the genes inside it. This is what carries colour at overview zoom.
// Bin count is derived from the rendered circumference (~1.6 px per bin) so the
// small plasmid ring doesn't get 1440 bins for 94 kb.
function buildBinnedRing(ri, rep, cx, cy, scale) {
  const TWO_PI = Math.PI * 2;
  const rMid = scale * (R.plusInner + R.plusOuter) / 2;
  const circumferencePx = TWO_PI * rMid * 40;          // ~40 px per world unit
  const bins = Math.max(96, Math.min(1500, Math.round(circumferencePx / 1.6)));
  const step = TWO_PI / bins;

  const acc = { '+': [], '-': [] };
  for (const s of ['+', '-']) acc[s] = Array.from({ length: bins }, () => new Map());
  for (const f of DATA.features) {
    if (f.r !== ri) continue;
    const target = acc[f.strand] ?? acc['+'];
    const b0 = Math.floor((f.s / rep.len) * bins);
    const b1 = Math.min(bins - 1, Math.floor(((f.e - 1) / rep.len) * bins));
    for (let b = b0; b <= b1; b++) {
      const m = target[b];
      const key = f.flag || f.cat;
      m.set(key, (m.get(key) || 0) + 1);
    }
  }

  const pos = [], col = [], alp = [];
  const EMPTY = hexRgb(0x1a2130);   // intergenic: visible, clearly recessive
  for (const s of ['+', '-']) {
    const plus = s === '+';
    const r0 = scale * (plus ? R.plusInner : R.minusInner);
    const r1 = scale * (plus ? R.plusOuter : R.minusOuter);
    for (let b = 0; b < bins; b++) {
      const m = acc[s][b];
      let rgb = EMPTY, best = 0, chosen = null;
      if (m.size) {
        // AMR / virulence always win their bin: a single 1 kb resistance gene must
        // stay visible next to a bin full of housekeeping genes.
        if (m.has('amr')) chosen = 'amr';
        else if (m.has('vir')) chosen = 'vir';
        else {
          for (const [cat, n] of m) {
            if (n > best) { best = n; chosen = cat; }
          }
        }
        if (chosen) rgb = hexRgb(catHex(chosen));
      }
      const v0 = pos.length / 3;
      addAnnularSector(pos, col, r0, r1, b * step, (b + 1) * step, -0.015, rgb, cx, cy);
      const v1 = pos.length / 3;
      const a = (chosen && filterOn && !catFilter.has(chosen)) ? FILTER_ALPHA : 1.0;
      for (let v = v0; v < v1; v++) alp.push(a);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  geo.setAttribute('aAlpha', new THREE.Float32BufferAttribute(alp, 1));
  const binMat = new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide, transparent: true, depthWrite: false,
  });
  binMat.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
        attribute float aAlpha;
        varying float vAlpha;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vAlpha = aAlpha;`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying float vAlpha;`)
      .replace('#include <dithering_fragment>', `
        gl_FragColor.a *= vAlpha;
        #include <dithering_fragment>`);
  };
  binnedGroup.add(new THREE.Mesh(geo, binMat));
}
function hexRgb(hex) {
  return [
    srgbToLinear(((hex >> 16) & 255) / 255),
    srgbToLinear(((hex >> 8) & 255) / 255),
    srgbToLinear((hex & 255) / 255),
  ];
}
/**
 * Vertex / instance colour buffers are interpreted as LINEAR-space by three.js.
 * Writing raw sRGB fractions there makes every colour render washed-out (e.g.
 * #45d69b came out as #8eeccd), so convert explicitly.
 */
function srgbToLinear(c) {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

// GC content + GC skew ribbons around each replicon
function buildGcTracks(ri, rep, cx, cy, scale) {
  const tr = rep.track;
  if (!tr || !tr.pos?.length) return;
  const TWO_PI = Math.PI * 2;

  // --- GC content (deviation from mean GC): thin ribbon, normal blending
  const meanGC = tr.gc.reduce((a, b) => a + b, 0) / tr.gc.length;
  const gPos = [], gCol = [];
  const amp = R.gcContW * 0.5;
  for (let i = 0; i < tr.pos.length; i++) {
    const j = (i + 1) % tr.pos.length;
    const a0 = (tr.pos[i] / rep.len) * TWO_PI;
    const a1 = (tr.pos[j] / rep.len) * TWO_PI;
    const d0 = Math.max(-1, Math.min(1, (tr.gc[i] - meanGC) / 6));
    const d1 = Math.max(-1, Math.min(1, (tr.gc[j] - meanGC) / 6));
    const base = R.gcCont * scale;
    const r0i = base, r0o = base + d0 * amp * scale;
    const r1i = base, r1o = base + d1 * amp * scale;
    // above mean GC → cool blue, below → warm amber
    const col = (d0 + d1) / 2 > 0
      ? [srgbToLinear(0.22), srgbToLinear(0.48), srgbToLinear(0.92)]
      : [srgbToLinear(0.92), srgbToLinear(0.55), srgbToLinear(0.22)];
    const i0 = [cx + Math.cos(a0) * r0i, cy - Math.sin(a0) * r0i, -0.01];
    const o0 = [cx + Math.cos(a0) * r0o, cy - Math.sin(a0) * r0o, -0.01];
    const i1 = [cx + Math.cos(a1) * r1i, cy - Math.sin(a1) * r1i, -0.01];
    const o1 = [cx + Math.cos(a1) * r1o, cy - Math.sin(a1) * r1o, -0.01];
    pushTri(gPos, gCol, i0, o0, i1, col);
    pushTri(gPos, gCol, i1, o0, o1, col);
  }
  const gcGeo = new THREE.BufferGeometry();
  gcGeo.setAttribute('position', new THREE.Float32BufferAttribute(gPos, 3));
  gcGeo.setAttribute('color', new THREE.Float32BufferAttribute(gCol, 3));
  gcGroup.add(new THREE.Mesh(gcGeo, new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide, transparent: true, opacity: 0.72,
    depthWrite: false,
  })));

  // --- GC skew line (cumulative-strand-bias signature)
  const skPts = [];
  const base = R.gcSkew * scale;
  const skewAmp = R.gcSkewW * scale;
  for (let i = 0; i < tr.pos.length; i++) {
    const a = (tr.pos[i] / rep.len) * TWO_PI;
    const v = Math.max(-1, Math.min(1, tr.skew[i] * 6));
    const rr = base + v * skewAmp * 0.5;
    skPts.push(new THREE.Vector3(cx + Math.cos(a) * rr, cy - Math.sin(a) * rr, -0.01));
  }
  gcGroup.add(new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(skPts),
    new THREE.LineBasicMaterial({ color: 0x35c9a4, transparent: true, opacity: 0.85 })));
}

/**
 * Gene-block material: a 1-pixel outline derived from the box's local position
 * (constant screen width via fwidth), plus per-instance alpha for filtering.
 * One draw call — no per-instance EdgesGeometry.
 */
function makeGeneMaterial() {
  const mat = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: true });
  mat.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
        attribute float aAlpha;
        varying float vAlpha;
        varying vec3 vLocal;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vAlpha = aAlpha;
        vLocal = position;`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying float vAlpha;
        varying vec3 vLocal;`)
      .replace('#include <dithering_fragment>', `
        // outline: distance to the nearest vertical/horizontal edge of the box
        float ex = 0.5 - abs(vLocal.x);
        float ey = 0.5 - abs(vLocal.y);
        float dmin = min(ex, ey);
        float w = max(fwidth(dmin), 1e-5);
        float border = 1.0 - smoothstep(w * 0.8, w * 2.4, dmin);
        gl_FragColor.rgb *= mix(1.0, 0.30, border);
        gl_FragColor.a *= vAlpha;
        #include <dithering_fragment>`);
  };
  return mat;
}

function setFeatureColor(i, hex) {
  if (!featureMesh.instanceColor) {
    featureMesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(featureMesh.count * 3), 3);
  }
  const [r, g, b] = hexRgb(hex);
  featureMesh.instanceColor.setXYZ(i, r, g, b);
  featureMesh.instanceColor.needsUpdate = true;
}

// ---------------------------------------------------------------------------
// picking
// ---------------------------------------------------------------------------
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const pickPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
const _hit = new THREE.Vector3();

function setRay(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
}

/** Exact hit on a gene box. */
function pickExact(clientX, clientY) {
  setRay(clientX, clientY);
  const hits = raycaster.intersectObject(featureMesh, false);
  return hits.length ? hits[0].instanceId : -1;
}

/**
 * Fallback: snap to the nearest gene. At overview zoom a 1 kb gene is a fraction
 * of a pixel, so an exact ray hit is nearly impossible — but users still expect
 * "click the ring, inspect the gene".
 */
function pickNearestGene(clientX, clientY) {
  setRay(clientX, clientY);
  if (!raycaster.ray.intersectPlane(pickPlane, _hit)) return -1;

  let bestId = -1, bestScore = Infinity;
  for (let ri = 0; ri < DATA.replicons.length; ri++) {
    const { cx, cy, scale } = layoutOf(ri);
    const dx = _hit.x - cx, dy = _hit.y - cy;
    const dist = Math.hypot(dx, dy);
    // which strand band did the user aim at?
    const rPlus = scale * (R.plusInner + R.plusOuter) / 2;
    const rMinus = scale * (R.minusInner + R.minusOuter) / 2;
    const wantPlus = Math.abs(dist - rPlus) <= Math.abs(dist - rMinus);
    const rTarget = wantPlus ? rPlus : rMinus;
    const radialErr = Math.abs(dist - rTarget);
    if (radialErr > scale * 1.4) continue;   // outside this replicon's bands

    // angle → genomic position (our rings run clockwise: y = -sin)
    let ang = Math.atan2(-dy, dx);
    if (ang < 0) ang += Math.PI * 2;
    const rep = DATA.replicons[ri];
    const scaleAng = ang / (Math.PI * 2);

    // scan genes of this replicon to find the one containing (or closest to) ang
    let localBest = -1, localErr = Infinity;
    for (let i = 0; i < DATA.features.length; i++) {
      if (fRep[i] !== ri) continue;
      const strandOk = (DATA.features[i].strand === '+') === wantPlus;
      const pen = strandOk ? 0 : 0.02;   // prefer the aimed strand
      const a0 = scaleAng - fAng0[i] / (Math.PI * 2);
      const a1 = scaleAng - fAng1[i] / (Math.PI * 2);
      const err = (a0 >= 0 && a1 <= 0)
        ? 0                                        // inside the gene
        : Math.min(Math.abs(a0), Math.abs(a1));    // distance to its edge
      const score = err + pen + radialErr * 0.02;
      if (score < localErr) { localErr = score; localBest = i; }
    }
    if (localBest >= 0 && localErr < bestScore) { bestScore = localErr; bestId = localBest; }
  }
  return bestId;
}

function pickId(clientX, clientY) {
  const exact = pickExact(clientX, clientY);
  if (exact >= 0) return exact;
  return pickNearestGene(clientX, clientY);
}

// ---------------------------------------------------------------------------
// explode + selection label
// ---------------------------------------------------------------------------
let explode = 0;
function applyExplode(v) {
  const tmpM = new THREE.Matrix4();
  const t = new THREE.Vector3(), r = new THREE.Vector3(), nrm = new THREE.Vector3(0, 0, 1);
  const p = new THREE.Vector3();
  for (let i = 0; i < DATA.features.length; i++) {
    const mid = fAngle[i], rMid = fRmid[i], cx = fCx[i], cy = fCy[i];
    const scale = layoutOf(fRep[i]).scale;
    const lift = v * 2.4 + (i === selectedId ? 0.55 : 0);
    const c = Math.cos(mid), s = Math.sin(mid);
    p.set(cx + c * rMid, cy - s * rMid, lift + FEATURE_DEPTH / 2);
    t.set(-s, -c, 0);
    r.set(c, -s, 0);
    tmpM.makeBasis(t, r, nrm);
    tmpM.scale(new THREE.Vector3(fWidth[i], BAND_THICKNESS * scale, FEATURE_DEPTH));
    tmpM.setPosition(p);
    featureMesh.setMatrixAt(i, tmpM);
  }
  featureMesh.instanceMatrix.needsUpdate = true;
  updateSelectedLabel();
}
function updateSelectedLabel() {
  if (selectedId < 0 || !selectedLabel) {
    if (selArc) selArc.visible = false;
    if (selectedLabel) selectedLabel.visible = false;
    if (selectedLine) selectedLine.visible = false;
    return;
  }
  const mid = fAngle[selectedId], rMid = fRmid[selectedId];
  const cx = fCx[selectedId], cy = fCy[selectedId];
  const lift = explode * 2.4 + 0.55;
  const c = Math.cos(mid), s = Math.sin(mid);

  updateSelArc(selectedId);

  const base = new THREE.Vector3(cx + c * rMid, cy - s * rMid, lift + FEATURE_DEPTH / 2);
  const dist = camera.position.distanceTo(base);

  // label sits above the gene in screen space
  const tip = base.clone()
    .add(new THREE.Vector3(0, 1, 0).multiplyScalar(Math.max(0.5, dist * 0.06)))
    .add(new THREE.Vector3(0, 0, 1).multiplyScalar(Math.max(0.4, dist * 0.03)));
  selectedLine.geometry.setFromPoints([base, tip]);
  selectedLine.geometry.attributes.position.needsUpdate = true;
  selectedLine.visible = true;
  selectedLabel.position.copy(tip);
  selectedLabel.visible = true;
  const k = Math.max(0.10, Math.min(2.4, dist / 27));
  const tex = selectedLabel.material.map;
  const hU = 0.42 * k;
  selectedLabel.scale.set(hU * (tex?.aspect || 4), hU, 1);
}

/**
 * Highlight as a curved annular sector instead of a rotated box.
 * A BoxGeometry rotated to the ring tangent showed two of its faces and, worse,
 * was 90° off (its tall axis pointed radially) — that read as "two genes lit up".
 */
function updateSelArc(id) {
  const f = DATA.features[id];
  const rep = DATA.replicons[f.r];
  const { cx, cy, scale } = layoutOf(f.r);
  const TWO_PI = Math.PI * 2;
  const plus = f.strand === '+';
  const r0 = scale * (plus ? R.plusInner : R.minusInner) - 0.08 * scale;
  const r1 = scale * (plus ? R.plusOuter : R.minusOuter) + 0.08 * scale;
  const a0 = (f.s / rep.len) * TWO_PI;
  const a1 = (f.e / rep.len) * TWO_PI;
  const rMid = scale * (plus ? (R.plusInner + R.plusOuter) / 2 : (R.minusInner + R.minusOuter) / 2);
  const midA = (a0 + a1) / 2;

  // enforce a minimum on-screen width so a sub-pixel gene is still visible
  const probe = new THREE.Vector3(cx + Math.cos(midA) * rMid, cy - Math.sin(midA) * rMid, 0);
  const wpp = worldPerPixel(camera.position.distanceTo(probe));
  const minAng = (5 * wpp) / Math.max(0.001, rMid);
  const half = Math.max(minAng, a1 - a0) / 2;

  const pos = [], col = [];
  addAnnularSector(pos, col, r0, r1, midA - half, midA + half,
    explode * 2.4 + FEATURE_DEPTH + 0.06, [1, 1, 1], cx, cy);

  if (!selArc) {
    selArc = new THREE.Mesh(new THREE.BufferGeometry(),
      new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, depthWrite: false }));
    selArc.renderOrder = 5;
    scene.add(selArc);
  }
  selArc.geometry.dispose();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  selArc.geometry = g;
  selArc.visible = true;
}

/** world units per screen pixel at a given camera distance */
function worldPerPixel(dist) {
  const h = renderer.domElement.clientHeight || 900;
  return (2 * dist * Math.tan((camera.fov * Math.PI / 180) / 2)) / h;
}

// ---------------------------------------------------------------------------
// ui: stats / legend
// ---------------------------------------------------------------------------
function renderStats() {
  const rep = DATA.replicons;
  const totalBp = rep.reduce((s, r) => s + r.len, 0);
  document.getElementById('crumb-sub').textContent =
    `SECTOR 01 · ${(DATA.organism || '').toUpperCase()} · ${(totalBp / 1e6).toFixed(2)} MB`;
}
function animateCounters() { /* counters removed in instrument theme */ }

const LEGEND_ORDER = ['amr', 'vir',
  'J', 'A', 'K', 'L', 'B',
  'M', 'D', 'N', 'O', 'T', 'U', 'V', 'W', 'Y', 'Z',
  'C', 'E', 'F', 'G', 'H', 'I', 'P', 'Q',
  'R', 'S', 'X',
  'trna', 'rrna', 'ncrna', 'pseudo', 'unknown'];

function renderLegend() {
  const counts = {};
  for (const f of DATA.features) {
    const k = f.flag || f.cat;
    counts[k] = (counts[k] || 0) + 1;
  }
  const present = LEGEND_ORDER.filter(k => counts[k]);
  // group into the four official COG families (plus the clinical overlay)
  const groups = [];
  for (const k of present) {
    const fam = CAT[k].fam;
    let g = groups.find(x => x.fam === fam);
    if (!g) { g = { fam, keys: [] }; groups.push(g); }
    g.keys.push(k);
  }
  const rep = DATA.replicons[selectedReplicon];
  document.getElementById('legend').innerHTML = `
    <div class="lg-head"><span class="t">轨道 · Tracks</span><span class="n">${rep.name}</span></div>
    <div class="lg-tracks">
      <div><i class="sw-plus"></i>+ 链 CDS（外环）</div>
      <div><i class="sw-minus"></i>− 链 CDS（内环）</div>
      <div><i class="sw-gc"></i>GC 含量 ${rep.track.window / 1000} kb 滑窗</div>
      <div><i class="sw-skew"></i>GC skew (G−C)/(G+C)</div>
    </div>
    <div class="lg-head" style="border-top:1px solid var(--border-subtle);margin-top:8px;padding-top:8px">
      <span class="t">COG 2020 · 功能分类</span>
      <span class="n">${filterOn ? `${catFilter.size}/${present.length} 选中` : `${DATA.features.length} feat`}</span>
    </div>
    <div class="lg-actions">
      <button data-act="all">全选</button>
      <button data-act="none">全不选</button>
      <button data-act="reset">重置</button>
    </div>
    <div class="lg-grid">${groups.map(g => `
      <div class="lg-fam">${COG_FAMILY[g.fam]}</div>
      ${g.keys.map(k => {
        const on = filterOn && catFilter.has(k);
        const dim = filterOn && !catFilter.has(k);
        return `
        <button class="lg-item${on ? ' on' : ''}${dim ? ' dim' : ''}" data-cat="${k}">
          <i style="background:${css(CAT[k].hex)}"></i>
          <span class="lg-code">${k.length <= 2 ? k.toUpperCase() : ''}</span>
          ${CAT[k].label}<b>${counts[k]}</b></button>`;
      }).join('')}`).join('')}
    </div>`;

  document.querySelectorAll('#legend .lg-item').forEach(el => {
    el.addEventListener('click', () => toggleCatFilter(el.dataset.cat));
  });
  document.querySelectorAll('#legend .lg-actions button').forEach(el => {
    el.addEventListener('click', () => {
      const a = el.dataset.act;
      if (a === 'all') selectAllCats();
      else if (a === 'none') selectNoCats();
      else resetCatFilter();
    });
  });
}

// ---------------------------------------------------------------------------
// view modes: ORBIT (circular, 3D)  ⇄  LINEAR (flat map, 2D)
// Same idea as the reference UI: the object has two spatial representations and
// the selection is preserved across modes.
// ---------------------------------------------------------------------------
let mode = 'orbit';
let analysisFramework = null;

/** Unified shell: the original genome map plus registered analytical plugins. */
function setMode(m) {
  const analysis = !['orbit', 'linear'].includes(m);
  if (analysis && !analysisFramework) return;
  mode = m;
  const orbit = m === 'orbit';
  document.querySelectorAll('#dock [data-mode]').forEach(button => {
    button.classList.toggle('on', button.dataset.mode === m);
  });

  document.getElementById('sidebar').hidden = analysis;
  document.getElementById('panel').hidden = analysis;
  document.getElementById('analysis-sidebar').hidden = !analysis;
  document.getElementById('analysis-panel').hidden = !analysis;
  document.getElementById('bottombar').classList.toggle('linear', m === 'linear');
  document.getElementById('bottombar').classList.toggle('analysis', analysis);

  if (analysis) {
    controls.enabled = false;
    canvas.style.display = 'block';
    document.getElementById('linear').classList.remove('on');
    analysisFramework.activate(m);
    return;
  }

  analysisFramework?.deactivate();
  document.title = `gvixb · ${DATA.organism || '3D atlas'}`;
  renderStats();
  canvas.style.display = orbit ? 'block' : 'none';
  document.getElementById('linear').classList.toggle('on', !orbit);
  controls.enabled = orbit && INTRO.done;
  if (!orbit) drawLinear();
}

const linCanvas = document.getElementById('linear');
let linWindow = null; // {r, start, end}
let linDrag = null;

/** Build the visible genomic window for linear mode. */
function linWindowFor() {
  const rep = DATA.replicons[selectedReplicon];
  if (selectedId >= 0 && DATA.features[selectedId].r === selectedReplicon) {
    const f = DATA.features[selectedId];
    const pad = Math.max(12000, (f.e - f.s) * 6);
    return { r: selectedReplicon, start: Math.max(0, f.s - pad), end: Math.min(rep.len, f.e + pad) };
  }
  return { r: selectedReplicon, start: 0, end: rep.len };
}

function drawLinear() {
  if (mode !== 'linear') return;
  const dpr = window.devicePixelRatio || 1;
  const W = window.innerWidth, H = window.innerHeight;
  if (linCanvas.width !== W * dpr || linCanvas.height !== H * dpr) {
    linCanvas.width = W * dpr; linCanvas.height = H * dpr;
    linCanvas.style.width = W + 'px'; linCanvas.style.height = H + 'px';
  }
  const ctx = linCanvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const win = linWindowFor();
  linWindow = win;
  const rep = DATA.replicons[win.r];
  const feats = DATA.features.filter(f => f.r === win.r && f.e > win.start && f.s < win.end);

  // plot area between the two panels
  const L = 292, Rr = W - 388;
  const Wd = Math.max(220, Rr - L);
  const xOf = (bp) => L + ((bp - win.start) / (win.end - win.start)) * Wd;

  // vertical stack: genes (2 rows) + GC content + GC skew + ruler
  const GENE_H = 20, GAP = 42, GC_H = 92, SKEW_H = 58, RULER = 26;
  const contentH = 30 + GENE_H * 2 + GAP + GC_H + GAP + SKEW_H + RULER;
  const TOP = Math.max(104, (H - contentH) / 2);
  const geneTop = TOP + 30;
  const axisY = geneTop + GENE_H;
  const gcTop = axisY + GAP + 6;
  const skewTop = gcTop + GC_H + GAP;

  // ---- frame
  ctx.strokeStyle = INK.frame; ctx.lineWidth = 1;
  ctx.strokeRect(L + 0.5, Math.round(geneTop - 12) + 0.5, Wd, (skewTop + SKEW_H) - geneTop + 14);

  // ---- graticule + ruler
  const span = win.end - win.start;
  const step = niceStep(span / 8);
  ctx.font = '9px ui-monospace, Menlo, monospace';
  for (let bp = Math.ceil(win.start / step) * step; bp <= win.end; bp += step) {
    const x = Math.round(xOf(bp)) + 0.5;
    ctx.strokeStyle = INK.grid;
    ctx.beginPath(); ctx.moveTo(x, geneTop - 12); ctx.lineTo(x, skewTop + SKEW_H); ctx.stroke();
    ctx.fillStyle = INK.text;
    ctx.fillText(kb(bp), x + 3, skewTop + SKEW_H + 15);
  }

  // ---- gene strands
  ctx.strokeStyle = INK.axis; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(L, axisY + 0.5); ctx.lineTo(L + Wd, axisY + 0.5); ctx.stroke();

  ctx.font = '8px ui-monospace, Menlo, monospace';
  ctx.fillStyle = INK.textDim;

  for (const f of feats) {
    const x0 = xOf(f.s), x1 = xOf(f.e);
    const w = Math.max(1.5, x1 - x0);
    const plus = f.strand === '+';
    const y = plus ? axisY - GENE_H + 2 : axisY + 2;
    const isSel = DATA.features.indexOf(f) === selectedId;
    ctx.fillStyle = isSel ? INK.select : css(featHex(f));
    ctx.globalAlpha = isSel ? 1 : 0.88;
    ctx.fillRect(x0, y, w, GENE_H - 4);
    ctx.globalAlpha = 1;
    if (isSel) {
      ctx.strokeStyle = INK.selectRing; ctx.lineWidth = 1.5;
      ctx.strokeRect(x0 - 1.5, y - 1.5, w + 3, GENE_H - 1);
    }
    if (w > 30 && f.gene) {
      ctx.fillStyle = isSel ? INK.strong : INK.text;
      ctx.font = '9px ui-monospace, Menlo, monospace';
      ctx.fillText(f.gene, x0 + 3, plus ? y - 3 : y + GENE_H + 9);
    }
  }

  // ---- GC content
  const tr = rep.track;
  const mean = tr.gc.reduce((a, b) => a + b, 0) / tr.gc.length;
  ctx.fillStyle = INK.gcStrip;
  ctx.fillRect(L, gcTop, Wd, GC_H);
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < tr.pos.length; i++) {
    const bp = tr.pos[i];
    if (bp < win.start || bp > win.end) continue;
    const x = xOf(bp);
    const y = gcTop + GC_H / 2 - ((tr.gc[i] - mean) / 8) * GC_H;
    if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = INK.gcLine; ctx.lineWidth = 1.2; ctx.stroke();
  // mean baseline
  ctx.strokeStyle = INK.grid; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(L, gcTop + GC_H / 2 + 0.5); ctx.lineTo(L + Wd, gcTop + GC_H / 2 + 0.5); ctx.stroke();
  ctx.fillStyle = INK.text; ctx.font = '8px ui-monospace, Menlo, monospace';
  ctx.fillText('GC CONTENT', L + 2, gcTop - 5);

  // ---- GC skew
  ctx.fillStyle = INK.gcStrip;
  ctx.fillRect(L, skewTop, Wd, SKEW_H);
  ctx.beginPath();
  started = false;
  for (let i = 0; i < tr.pos.length; i++) {
    const bp = tr.pos[i];
    if (bp < win.start || bp > win.end) continue;
    const x = xOf(bp);
    const v = Math.max(-1, Math.min(1, tr.skew[i] * 6));
    const y = skewTop + SKEW_H / 2 - v * SKEW_H / 2;
    if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = '#6d8bff'; ctx.lineWidth = 1.2; ctx.stroke();
  ctx.strokeStyle = INK.grid; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(L, skewTop + SKEW_H / 2 + 0.5); ctx.lineTo(L + Wd, skewTop + SKEW_H / 2 + 0.5); ctx.stroke();
  ctx.fillStyle = INK.text;
  ctx.fillText('GC SKEW', L + 2, skewTop - 5);

  // ---- header
  ctx.fillStyle = INK.strong; ctx.font = '600 10px ui-monospace, Menlo, monospace';
  ctx.fillText('LINEAR MAP', L, geneTop - 30);
  ctx.font = '8px ui-monospace, Menlo, monospace';
  ctx.fillStyle = INK.textDim;
  ctx.fillText('+ ABOVE  /  \u2212 BELOW', L + 76, geneTop - 30);
  ctx.fillStyle = INK.text; ctx.font = '9px ui-monospace, Menlo, monospace';
  ctx.fillText(`${rep.name} · ${fmt(win.start + 1)}\u2013${fmt(win.end)} bp · ${feats.length} features`, L, geneTop - 16);
}

/** 1234567 -> "1.23 Mb", 45000 -> "45 kb" */
function fmtBp(bp, len) {
  if (len >= 1e6) {
    const v = bp / 1e6;
    return (v % 1 === 0 ? v.toFixed(0) : v.toFixed(2).replace(/0$/, '')) + ' Mb';
  }
  return (bp / 1e3).toFixed(bp % 1000 === 0 ? 0 : 1) + ' kb';
}

/** Pick a "nice" step giving approximately `target` intervals over `total`. */
function niceStepFor(total, target = 9) {
  const raw = total / target;
  const exp = Math.pow(10, Math.floor(Math.log10(raw)));
  let best = exp, bestErr = Infinity;
  for (const m of [1, 2, 2.5, 5, 10]) {
    const step = m * exp;
    const err = Math.abs(total / step - target);
    if (err < bestErr) { bestErr = err; best = step; }
  }
  return best;
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

// click / drag on the linear map
linCanvas.addEventListener('click', (ev) => {
  if (!linWindow || mode !== 'linear') return;
  const W = window.innerWidth;
  const L = 300, Rr = W - 388;
  const x = ev.clientX;
  if (x < L || x > Rr) return;
  const bp = linWindow.start + ((x - L) / (Rr - L)) * (linWindow.end - linWindow.start);
  // nearest feature on the clicked strand-ish
  let best = -1, bestD = Infinity;
  for (let i = 0; i < DATA.features.length; i++) {
    const f = DATA.features[i];
    if (f.r !== linWindow.r) continue;
    const d = bp < f.s ? f.s - bp : (bp > f.e ? bp - f.e : 0);
    if (d < bestD) { bestD = d; best = i; }
  }
  if (best >= 0) { selectFeature(best); drawLinear(); }
});

// ---------------------------------------------------------------------------
// ui: tooltip + inspector
// ---------------------------------------------------------------------------
const tooltipEl = document.getElementById('tooltip');
const featureBody = document.getElementById('feature-body');
const trunc = (s, n) => (!s ? '' : s.length > n ? s.slice(0, n - 1) + '…' : s);

function showTooltip(clientX, clientY, id) {
  if (id < 0) { tooltipEl.style.display = 'none'; return; }
  const f = DATA.features[id];
  const rep = DATA.replicons[f.r];
  const name = f.gene || f.locus || `CDS_${fmt(f.s + 1)}`;
  const tag = f.flag ? CAT[f.flag].label : `${f.cat} · ${CAT[f.cat] ? CAT[f.cat].label : '—'}`;
  tooltipEl.innerHTML = `
    <div class="tt-name" style="color:${css(featHex(f))}">${name}
      <span style="color:var(--text-4)">· ${f.strand}</span>
      <span class="tt-tag" style="color:${css(featHex(f))}">${tag}</span></div>
    <div class="tt-sub">${trunc(f.product, 72) || '—'}</div>
    ${f.cog ? `<div class="tt-sub">${f.cog} · ${trunc(f.cogname, 48)}</div>` : ''}
    <div class="tt-sub">${rep.name} : ${fmt(f.s + 1)}–${fmt(f.e)}</div>`;
  tooltipEl.style.display = 'block';
  tooltipEl.style.left = Math.min(clientX + 16, window.innerWidth - 340) + 'px';
  tooltipEl.style.top = Math.min(clientY + 14, window.innerHeight - 90) + 'px';
}

function selectFeature(id) {
  if (selectedId >= 0) setFeatureColor(selectedId, featHex(DATA.features[selectedId]));
  selectedId = id;
  if (id < 0) {
    featureBody.innerHTML = `<p class="empty">点击环上任意基因，查看真实注释、GC 仪表与碱基序列。
      <br><span class="hint-key">滚轮缩放 · 拖拽旋转 · 滑杆拆解</span></p>`;
    if (selectedLabel) selectedLabel.visible = false;
    if (selectedLine) selectedLine.visible = false;
    if (selArc) selArc.visible = false;
    document.getElementById('panel').classList.add('empty');
    applyExplode(explode);
    syncGeneListSelection();
    if (mode === 'linear') drawLinear();
    return;
  }
  setFeatureColor(id, 0xffffff);
  applyExplode(explode);

  const f = DATA.features[id];
  const rep = DATA.replicons[f.r];
  document.getElementById('panel').classList.remove('empty');
  // follow the selection in the sidebar
  if (f.r !== selectedReplicon) {
    selectedReplicon = f.r;
    renderRepliconList();
    renderGeneList();
  } else {
    syncGeneListSelection();
  }
  const name = f.gene || f.locus || `CDS_${fmt(f.s + 1)}`;
  const cHex = css(featHex(f));
  const badge = f.flag ? CAT[f.flag].label
    : `COG ${f.cat !== 'unknown' ? f.cat : '—'}${CAT[f.cat] ? ' · ' + CAT[f.cat].label : ''}`;
  const coding = f.kind === 'CDS';
  const seq = coding
    ? (f.strand === '+' ? rep.seq.slice(f.s, f.e) : revcomp(rep.seq.slice(f.s, f.e)))
    : (f.strand === '+' ? rep.seq.slice(f.s, f.e) : revcomp(rep.seq.slice(f.s, f.e)));
  const aa = coding ? translate(seq) : null;

  featureBody.innerHTML = `
    <div class="gene-name">${name}<span class="strand"> · ${f.strand}</span>
      <span class="badge" style="color:${cHex};border-color:${cHex}55;background:${cHex}14">${badge}</span></div>
    <p class="gene-product">${f.product || '（未注释 / unannotated）'}</p>

    <div class="gauges">
      <canvas id="gc-gauge" width="92" height="92"></canvas>
      <div class="gauge-stats">
        <div class="g"><span>长度</span><b>${fmt(f.e - f.s)} bp</b></div>
        <div class="g"><span>${coding ? 'aa' : '类型'}</span><b>${coding ? aa.length : f.kind}</b></div>
        <div class="g"><span>GC</span><b>${f.gc}%</b></div>
        <div class="g"><span>链</span><b>${f.strand}</b></div>
      </div>
    </div>

    <dl class="kv">
      <dt>locus_tag</dt><dd>${f.locus || '—'}</dd>
      <dt>COG</dt><dd>${f.cog ? f.cog + ' · ' + (f.cogname || '') : '—（无 COG 命中）'}</dd>
      <dt>复制子</dt><dd>${rep.name}</dd>
      <dt>位置</dt><dd>${fmt(f.s + 1)} – ${fmt(f.e)}</dd>
    </dl>

    <div class="sec-label">局部轨道 · Locus</div>
    <canvas id="track"></canvas>

    <div class="btn-row" style="margin-top:10px">
      <button id="btn-focus" class="slab-btn">定位放大 · Focus</button>
    </div>

    <div class="sec-label">碱基序列 · ${coding ? 'Bases + 翻译' : 'Bases'}</div>
    <div class="seq-scroll" id="seq-body"></div>`;

  drawGauge(document.getElementById('gc-gauge'), f.gc, cHex);
  drawLinearTrack(document.getElementById('track'), f);
  renderSequence(seq, f, aa);
  document.getElementById('btn-focus')?.addEventListener('click', () => focusGene(id));

  if (!selectedLabel) {
    selectedLabel = makeTextSprite(name, '#ffffff', 30, 0.42);
    selectedLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.6 }));
    featureGroup.add(selectedLine, selectedLabel);
  } else {
    setSpriteText(selectedLabel, name, '#ffffff', 30);
  }
  updateSelectedLabel();
  if (mode === 'linear') drawLinear();
}

function drawGauge(cv, pct, color) {
  const dpr = window.devicePixelRatio || 1;
  const size = cv.width / dpr;
  cv.width = size * dpr; cv.height = size * dpr;
  const ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, size, size);
  const c = size / 2, rad = size / 2 - 7;
  const start = Math.PI * 0.75, sweep = Math.PI * 1.5;
  ctx.lineWidth = 6; ctx.lineCap = 'round';
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.beginPath(); ctx.arc(c, c, rad, start, start + sweep); ctx.stroke();
  ctx.strokeStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 8;
  ctx.beginPath(); ctx.arc(c, c, rad, start, start + sweep * Math.min(1, pct / 100)); ctx.stroke();
  ctx.shadowBlur = 0;
  // ---- centre label, auto-fitted to the chord of the arc -------------------
  // A fixed 21px font overflowed the dial for values like "54.4%"; size the text
  // to the widest chord it can occupy without touching the ring.
  const label = pct + '%';
  const TY = 4;                       // baseline offset above centre
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  // Small by design: the dial is the graphic, the number is a caption.
  let fs = 11;
  do {
    const yTop = TY + fs / 2;
    const halfChord = Math.sqrt(Math.max(1, (rad - 4) ** 2 - yTop ** 2));
    const maxW = halfChord * 2 * 0.50;               // keep well clear of the arc
    ctx.font = `600 ${fs}px ui-monospace, Menlo, monospace`;
    if (ctx.measureText(label).width <= maxW) break;
    fs -= 1;
  } while (fs > 7);

  ctx.fillStyle = '#dfe6f8';
  ctx.font = `600 ${fs}px ui-monospace, Menlo, monospace`;
  ctx.fillText(label, c, c - TY);

  // unit label sits just under the value so they read as one block
  ctx.fillStyle = '#7e8bb0';
  ctx.font = '8px -apple-system, sans-serif';
  ctx.fillText('GC', c, c - TY + fs / 2 + 6);
}

function drawLinearTrack(cv, f) {
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const rep = DATA.replicons[f.r];
  const pad = Math.max(4000, Math.round((f.e - f.s) * 1.2));
  const win = [Math.max(0, f.s - pad), Math.min(rep.len, f.e + pad)];
  const scale = w / Math.max(1, win[1] - win[0]);
  const midY = h / 2, trackH = 20;

  ctx.strokeStyle = 'rgba(255,255,255,0.12)';
  ctx.beginPath(); ctx.moveTo(0, midY); ctx.lineTo(w, midY); ctx.stroke();

  const near = DATA.features.filter(g => g.r === f.r && g.e > win[0] && g.s < win[1]);
  for (const g of near) {
    const x0 = (g.s - win[0]) * scale, x1 = (g.e - win[0]) * scale;
    const y = g.strand === '+' ? midY - trackH : midY;
    ctx.fillStyle = g === f ? '#ffffff' : css(featHex(g));
    ctx.globalAlpha = g === f ? 1 : 0.72;
    ctx.fillRect(x0, y, Math.max(2, x1 - x0), trackH - 4);
    if (x1 - x0 > 8) {
      ctx.beginPath();
      if (g.strand === '+') {
        ctx.moveTo(x1 + 5, y); ctx.lineTo(x1 - 3, y + (trackH - 4) / 2); ctx.lineTo(x1 + 5, y + trackH - 4);
      } else {
        ctx.moveTo(x0 - 5, y); ctx.lineTo(x0 + 3, y + (trackH - 4) / 2); ctx.lineTo(x0 - 5, y + trackH - 4);
      }
      ctx.fill();
    }
  }
  ctx.globalAlpha = 1;

  ctx.fillStyle = 'rgba(126,139,176,0.85)';
  ctx.font = '10px ui-monospace, Menlo, monospace';
  const step = (win[1] - win[0]) / 5;
  let lastLabelX = -1e9;
  for (let i = 0; i <= 5; i++) {
    const bp = win[0] + step * i;
    const x = (bp - win[0]) * scale;
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath(); ctx.moveTo(x, midY - trackH - 8); ctx.lineTo(x, midY + trackH + 8); ctx.stroke();
    const label = kb(bp);
    const isLast = i === 5;
    const lx = isLast ? x - ctx.measureText(label).width - 2 : x + 3;
    if (lx - lastLabelX > 30) {          // avoid the "3.04 4b kb" pile-up at the edge
      ctx.fillText(label, lx, midY + trackH + 18);
      lastLabelX = lx;
    }
  }
}

function renderSequence(seq, f, aa) {
  // Fit the row to the panel so the sequence never scrolls horizontally:
  // measure the available width and derive codons-per-line (multiple of 3).
  // Fixed 30 bases / 10 codons per line: a clean round number that also fits the
  // panel width, so the sequence never needs a horizontal scrollbar.
  const host = document.getElementById('seq-body');
  const avail = Math.max(150, (host?.clientWidth || 300) - 70);
  const baseW = 6.0 + (0.4 * 10) / 3;              // 10px monospace + codon gap
  const fit = Math.max(3, Math.floor(avail / baseW));
  const PER = Math.min(30, Math.floor(fit / 3) * 3);   // 30 when it fits
  let html = '';
  for (let i = 0; i < seq.length; i += PER) {
    const chunk = seq.slice(i, i + PER);
    const pos = f.strand === '+' ? f.s + i + 1 : f.e - i;
    let bases = '';
    for (let j = 0; j < chunk.length; j++) {
      const b = chunk[j];
      const gi = i + j;
      const first = gi < 3, last = gi >= seq.length - 3;
      const cls = `b-${b}${first ? ' b-start' : ''}${last ? ' b-stop' : ''}`;
      if (j % 3 === 0) bases += `<span class="b3 ${cls}">`;
      bases += b;
      if (j % 3 === 2) bases += '</span>';
    }
    html += `<div class="seq-row"><span class="seq-pos">${fmt(pos)}</span><span class="seq-bases">${bases}</span></div>`;
    if (aa) {
      const line = aa.slice(i / 3, i / 3 + PER / 3).join(' ');
      html += `<div class="seq-row"><span class="seq-pos"></span><span class="seq-aa">${line}</span></div>`;
    }
  }
  document.getElementById('seq-body').innerHTML = html;
}

// ---------------------------------------------------------------------------
// events
// ---------------------------------------------------------------------------
renderer.domElement.addEventListener('pointermove', (ev) => {
  if (mode !== 'orbit') return;
  const id = pickId(ev.clientX, ev.clientY);
  if (id !== hoverId) {
    if (hoverId >= 0 && hoverId !== selectedId) setFeatureColor(hoverId, featHex(DATA.features[hoverId]));
    hoverId = id;
    if (id >= 0 && id !== selectedId) setFeatureColor(id, brighten(featHex(DATA.features[id]), 0.55));
  }
  showTooltip(ev.clientX, ev.clientY, id);
});
renderer.domElement.addEventListener('pointerleave', () => {
  if (mode !== 'orbit') return;
  if (hoverId >= 0 && hoverId !== selectedId) setFeatureColor(hoverId, featHex(DATA.features[hoverId]));
  hoverId = -1;
  tooltipEl.style.display = 'none';
});
renderer.domElement.addEventListener('click', (ev) => {
  if (mode === 'orbit') selectFeature(pickId(ev.clientX, ev.clientY));
});
renderer.domElement.addEventListener('dblclick', (ev) => {
  if (mode !== 'orbit') return;
  const id = pickId(ev.clientX, ev.clientY);
  if (id >= 0) { selectFeature(id); focusGene(id); }
});

document.getElementById('explode').addEventListener('input', (ev) => {
  explode = parseFloat(ev.target.value);
  document.getElementById('explode-val').textContent = explode.toFixed(2);
  applyExplode(explode);
});
document.getElementById('btn-reset').addEventListener('click', () => {
  flyTo(HOME_CAM.clone(), target0.clone(), 0.9);
});
document.getElementById('btn-auto').addEventListener('click', (ev) => {
  controls.autoRotate = !controls.autoRotate;
  ev.currentTarget.classList.toggle('on', controls.autoRotate);
});
document.getElementById('btn-gc').addEventListener('click', (ev) => {
  gcGroup.visible = !gcGroup.visible;
  ev.currentTarget.classList.toggle('on', gcGroup.visible);
});
document.querySelectorAll('#dock [data-mode]').forEach(button => {
  button.addEventListener('click', () => setMode(button.dataset.mode));
});

// UTC clock
function tickClock() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  document.getElementById('clock').textContent =
    `${d.getUTCFullYear()}.${p(d.getUTCMonth() + 1)}.${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}
tickClock();
setInterval(tickClock, 1000);

window.addEventListener('resize', onResize);
function onResize() {
  const w = window.innerWidth, h = window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
  bloom.resolution.set(w, h);
  analysisFramework?.resize();
  if (mode === 'linear') drawLinear();
}

// ---------------------------------------------------------------------------
// left sidebar: replicon list + gene list
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);

function renderRepliconList() {
  const el = $('replicon-list');
  $('rep-count').textContent = `${DATA.replicons.length}`;
  el.innerHTML = DATA.replicons.map((r, i) => {
    const n = DATA.features.filter(f => f.r === i).length;
    const hot = DATA.features.filter(f => f.r === i && (f.cat === 'amr' || f.cat === 'vir')).length;
    return `<button class="rep-row${i === selectedReplicon ? ' on' : ''}" data-rep="${i}">
      <div class="rname"><span>${r.name}</span><span class="rlen">${kb(r.len)}</span></div>
      <div class="rmeta"><span>${r.id}</span><span><b>${fmt(n)}</b> genes</span>${hot ? `<span class="hot"><b>${hot}</b> AMR/毒力</span>` : ''}</div>
    </button>`;
  }).join('');
  el.querySelectorAll('.rep-row').forEach(btn => {
    btn.addEventListener('click', () => {
      selectedReplicon = parseInt(btn.dataset.rep, 10);
      renderRepliconList();
      renderGeneList();
      focusReplicon(selectedReplicon);
    });
  });
}

const MAX_ROWS = 220;
function renderGeneList() {
  const q = ($('gene-search').value || '').trim().toLowerCase();
  const all = [];
  for (let i = 0; i < DATA.features.length; i++) {
    if (DATA.features[i].r === selectedReplicon) all.push(i);
  }
  // --- COG category filter is shared with the ring: keep both views in sync ---
  let pool = all;
  let catScoped = false;
  if (filterOn) {
    catScoped = true;
    pool = pool.filter(i => catFilter.has(featureKey(DATA.features[i])));
  }
  if (q) {
    pool = pool.filter(i => {
      const f = DATA.features[i];
      return (f.gene || '').toLowerCase().includes(q) ||
             (f.locus || '').toLowerCase().includes(q) ||
             (f.product || '').toLowerCase().includes(q);
    });
  }
  const hotRank = (f) => (f.flag === 'amr' ? 0 : f.flag === 'vir' ? 1 : 2);
  if (!q) {
    // hot genes first so AMR / virulence surface immediately, then genomic order
    pool = pool.slice().sort((a, b) =>
      hotRank(DATA.features[a]) - hotRank(DATA.features[b]) || a - b);
  }

  $('gene-count').textContent =
    (catScoped || q) ? `${pool.length}/${all.length}` : `${all.length}`;
  const rows = pool.slice(0, MAX_ROWS);
  const el = $('gene-list');
  el.innerHTML = rows.map((i, n) => {
    const f = DATA.features[i];
    const c = css(featHex(f));
    const tag = f.flag ? (f.flag === 'amr' ? 'AMR' : 'VIR') : f.cat.toUpperCase();
    return `<button class="gene-row${i === selectedId ? ' on' : ''}" data-i="${i}">
      <span class="idx">${String(n + 1).padStart(2, '0')}</span>
      <span class="gr-main">
        <b><span style="color:${c}">|</span> ${f.gene || f.locus || '—'}</b>
        <em>${trunc(f.product || f.kind, 46)}</em>
      </span>
      <span class="tag" style="${f.cat === 'amr' || f.cat === 'vir' ? `color:${c}` : ''}">${tag}</span>
    </button>`;
  }).join('') + (pool.length > MAX_ROWS
    ? `<div class="gene-note">仅显示前 ${MAX_ROWS} 条（共 ${fmt(pool.length)}）· 可用搜索缩小</div>`
    : (rows.length ? ''
        : `<div class="gene-note">${filterOn && catFilter.size === 0
            ? '全不选：没有可显示的类别'
            : '没有匹配的基因'}</div>`));

  el.querySelectorAll('.gene-row').forEach(btn => {
    btn.addEventListener('click', () => {
      const i = parseInt(btn.dataset.i, 10);
      selectFeature(i);
      focusGene(i);
      renderGeneList();
    });
  });
}

/** keep the list highlight in sync with a 3D selection */
function syncGeneListSelection() {
  document.querySelectorAll('#gene-list .gene-row').forEach(btn => {
    btn.classList.toggle('on', parseInt(btn.dataset.i, 10) === selectedId);
  });
}

// ---------------------------------------------------------------------------
// camera fly-to (replicon overview)
// ---------------------------------------------------------------------------
/**
 * The two sidebars are not symmetric, so "centred on screen" is not "centred in
 * the visible area". Returns the world-space x offset that puts a point in the
 * middle of the free area between the sidebar and the inspector.
 */
function freeAreaShift(dist) {
  const sb = document.getElementById('sidebar');
  const pn = document.getElementById('panel');
  const freeLeft = sb ? sb.getBoundingClientRect().right + 8 : 0;
  const freeRight = pn ? pn.getBoundingClientRect().left - 8 : window.innerWidth;
  const freeCenter = (freeLeft + freeRight) / 2;
  const pxShift = window.innerWidth / 2 - freeCenter;
  const vFov = camera.fov * Math.PI / 180;
  const pxPerUnit = window.innerHeight / (2 * dist * Math.tan(vFov / 2));
  return pxShift / pxPerUnit;
}

function flyTo(toPos, toTgt, dur = 0.95) {
  camAnim = {
    fromPos: camera.position.clone(), toPos,
    fromTgt: controls.target.clone(), toTgt,
    t: 0, dur,
  };
  if (controls.autoRotate) {
    controls.autoRotate = false;
    document.getElementById('btn-auto')?.classList.remove('on');
  }
}

function focusReplicon(ri) {
  const { cx, cy, scale } = layoutOf(ri);
  const radius = (R.plusOuter + 1.4) * scale;
  const vFov = camera.fov * Math.PI / 180;
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const dist = Math.max(radius / Math.tan(vFov / 2), radius / Math.tan(hFov / 2)) * 1.16;
  const target = new THREE.Vector3(cx + freeAreaShift(dist), cy, 0);
  const toPos = target.clone().add(new THREE.Vector3(0, dist * 0.24, dist * 0.97));
  flyTo(toPos, target);
  selectFeature(-1);
}

// ---------------------------------------------------------------------------
// camera fly-to (zoom into a gene)
// ---------------------------------------------------------------------------
let camAnim = null;
function focusGene(id) {
  if (id < 0) return;
  const mid = fAngle[id], rMid = fRmid[id];
  const cx = fCx[id], cy = fCy[id];
  const scale = layoutOf(fRep[id]).scale;
  const c = Math.cos(mid), s = Math.sin(mid);
  const target = new THREE.Vector3(cx + c * rMid, cy - s * rMid, 0);
  // stand outside the ring, looking inwards at the gene
  const away = new THREE.Vector3(c, -s, 0).multiplyScalar(Math.max(3.4, 6.5 * scale));
  const want = target.clone().add(away)
    .add(new THREE.Vector3(0, Math.max(1.1, 2.4 * scale), Math.max(3.4, 6 * scale)));
  const d = want.distanceTo(target);
  const shift = freeAreaShift(d);
  const toPos = want.clone().add(new THREE.Vector3(shift, 0, 0));
  const toTgt = target.clone().add(new THREE.Vector3(shift, 0, 0));
  flyTo(toPos, toTgt);
}

// ---------------------------------------------------------------------------
// animate
// ---------------------------------------------------------------------------
const clock = new THREE.Clock();
const target0 = new THREE.Vector3(0.5, 1.0, 0);
const INTRO = {
  from: new THREE.Vector3(-6, 30, 52),
  to: HOME_CAM.clone(),
  t: 0, dur: 1.8, done: false,
};

function animate() {
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  if (analysisFramework?.active) {
    analysisFramework.tick(dt);
    return;
  }

  if (camAnim) {
    camAnim.t += dt / camAnim.dur;
    const e = easeOutCubic(Math.min(1, camAnim.t));
    camera.position.lerpVectors(camAnim.fromPos, camAnim.toPos, e);
    controls.target.lerpVectors(camAnim.fromTgt, camAnim.toTgt, e);
    camera.lookAt(controls.target);
    if (camAnim.t >= 1) camAnim = null;
  } else if (!INTRO.done) {
    INTRO.t += dt / INTRO.dur;
    const e = easeOutCubic(Math.min(1, INTRO.t));
    camera.position.lerpVectors(INTRO.from, INTRO.to, e);
    camera.lookAt(target0);
    if (INTRO.t >= 1) { INTRO.done = true; controls.enabled = true; controls.update(); }
  } else {
    controls.update();
  }

  // deep-space atmosphere motion
  if (dust) { dust.rotation.y += dt * 0.03; dust.rotation.x += dt * 0.011; }
  if (halo) halo.material.opacity = 0.75 + Math.sin(performance.now() * 0.0012) * 0.15;

  // ---- LOD: individual genes only when close enough to see them
  const dist = camera.position.distanceTo(controls.target);
  const showGenes = dist < LOD_GENE_DISTANCE;
  if (featureMesh && featureMesh.visible !== showGenes) featureMesh.visible = showGenes;
  for (const lab of repliconLabels) lab.visible = !showGenes;
  for (const lab of bezelLabels) lab.visible = !showGenes;

  // keep the selected-gene label + marker sized for the current zoom
  if (selectedId >= 0) updateSelectedLabel();

  // dock readouts
  const zd = document.getElementById('dock-zoom');
  if (zd) zd.textContent = (27 / Math.max(0.001, dist)).toFixed(1) + '×';
  const sd = document.getElementById('dock-sel');
  if (sd) sd.textContent = selectedId >= 0
    ? (DATA.features[selectedId].gene || DATA.features[selectedId].locus || '—')
    : '—';

  composer.render();
}

// ---------------------------------------------------------------------------
// go
// ---------------------------------------------------------------------------
const resp = await fetch('./data.json');
DATA = await resp.json();
document.title = `gvixb · ${DATA.organism || 'genome control'}`;
renderStats();
renderLegend();
build();
renderRepliconList();
renderGeneList();
$('gene-search').addEventListener('input', renderGeneList);
analysisFramework = createAnalysisFramework({ renderer, canvas });
onResize();
const requestedView = new URLSearchParams(location.search).get('view');
if (['linear', 'phylo', 'mst', 'synteny'].includes(requestedView)) setMode(requestedView);
animate();

window.__g3d = {
  setMode,
  analysis: () => analysisFramework?.debug(),
  selectFeature,
  getData: () => DATA,
  project: (i) => {
    const c = Math.cos(fAngle[i]), s = Math.sin(fAngle[i]);
    const v = new THREE.Vector3(
      fCx[i] + c * fRmid[i], fCy[i] - s * fRmid[i], FEATURE_DEPTH / 2);
    v.project(camera);
    const rect = renderer.domElement.getBoundingClientRect();
    return {
      x: (v.x * 0.5 + 0.5) * rect.width + rect.left,
      y: (-v.y * 0.5 + 0.5) * rect.height + rect.top,
    };
  },
  pickAt: (x, y) => pickId(x, y),
  alphaOf: () => featureMesh ? Array.from(featureMesh.geometry.getAttribute('aAlpha').array) : [],
  catFilter: () => ({ on: filterOn, keys: Array.from(catFilter) }),
  pickExactAt: (x, y) => pickExact(x, y),
  focusGene: (i) => focusGene(i),
  lod: () => ({
    dist: camera.position.distanceTo(controls.target),
    genesVisible: featureMesh.visible,
    threshold: LOD_GENE_DISTANCE,
  }),
  zoomTo: (d) => {
    const dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).add(dir.multiplyScalar(d));
    controls.update();
  },
  selMarkerVisible: () => (selArc ? selArc.visible : null),
  selLineVisible: () => (selectedLine ? selectedLine.visible : null),
  selLabelVisible: () => (selectedLabel ? selectedLabel.visible : null),
  findGene: (name) => DATA.features.findIndex(f => f.gene === name),
  focusReplicon: (i) => focusReplicon(i),
  selectedReplicon: () => selectedReplicon,
  probe: (x, y) => {
    setRay(x, y);
    const ok = raycaster.ray.intersectPlane(pickPlane, _hit);
    return ok ? { x: _hit.x, y: _hit.y, z: _hit.z } : null;
  },
};
