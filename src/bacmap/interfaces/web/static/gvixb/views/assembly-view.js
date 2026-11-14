import * as THREE from '../vendor/three.module.js';
import {
  makeLabel, escapeHtml, formatBp, disposeHierarchy, makeDustField,
  addAnnularSector, sectorMeshFromArrays, hexRgb, srgbToLinear, pushTri,
  makeRadialSprite, circlePoints, lineFromPoints,
} from '../framework/primitives.js';
import { clamp } from '../framework/algorithms.js';

// ---------------------------------------------------------------------------
// ring geometry — the same instrument-face layout as the reference demo:
// inner GC tracks, minus / backbone / plus bands, engraved hairlines, then a
// mechanical bezel carrying genomic bp ticks and labels.
// ---------------------------------------------------------------------------
const RING = {
  gcSkew: 3.55, gcSkewW: 0.42,
  gcCont: 4.10, gcContW: 0.46,
  minusInner: 5.30, minusOuter: 5.80,
  backboneInner: 5.80, backboneOuter: 7.00,
  plusInner: 7.00, plusOuter: 7.50,
  hairlines: [7.58, 7.88, 8.10],
  bezelInner: 8.18, bezelOuter: 9.22,
  tickIn: 8.78, tickSub: 9.025, tickMinor: 9.08, tickOut: 9.14,
  labelR: 8.46, nameR: 9.90,
};
const FEATURE_DEPTH = 0.34;
const BAND_THICKNESS = 0.5;
const EXPLODE_LIFT = 2.4;
// Overview-vs-detail split, like the demo's LOD_GENE_DISTANCE: ring labels
// (contig names + bp ticks) hide when the camera is close enough to inspect
// hits. The hit blocks themselves stay visible — assembly hits are sparse,
// so hiding them at distance would remove the only screening signal.
const LOD_LABEL_DISTANCE = 19;
const KIND_HEX = { amr: 0xff2d55, vir: 0xff8a3d };
const featHex = feature => KIND_HEX[feature.kind] ?? KIND_HEX.vir;

function formatCoordinate(position) {
  return position < 1000 ? `${position} bp` : formatBp(position);
}

/** Tick labels on the bezel: 1234567 -> "1.23 Mb", 45000 -> "45 kb". */
function fmtBpTick(bp, len) {
  if (len >= 1e6) {
    const v = bp / 1e6;
    return `${v % 1 === 0 ? v.toFixed(0) : v.toFixed(2).replace(/0$/, '')} Mb`;
  }
  return `${(bp / 1e3).toFixed(bp % 1000 === 0 ? 0 : 1)} kb`;
}

/** Pick a "nice" step giving approximately `target` intervals over `total`. */
function niceStepFor(total, target = 9) {
  const raw = total / target;
  const exp = 10 ** Math.floor(Math.log10(raw));
  let best = exp, bestErr = Infinity;
  for (const m of [1, 2, 2.5, 5, 10]) {
    const step = m * exp;
    const err = Math.abs(total / step - target);
    if (err < bestErr) { bestErr = err; best = step; }
  }
  return Math.max(1, best);
}

function contigOptionLabel(rank, contig) {
  const id = contig.id.length > 38 ? `${contig.id.slice(0, 37)}…` : contig.id;
  return `#${String(rank + 1).padStart(2, '0')}  ${id}  ·  ${formatBp(contig.length)}`;
}

function brighten(hex, t) {
  const r = (hex >> 16) & 255, g = (hex >> 8) & 255, b = hex & 255;
  return ((Math.round(r + (255 - r) * t)) << 16) |
    ((Math.round(g + (255 - g) * t)) << 8) |
    (Math.round(b + (255 - b) * t));
}

// ---------------------------------------------------------------------------
// atmosphere: the demo's tight lens glow behind the ring, a faint halo and a
// slow dust field. Decorative only — they carry no data meaning.
// ---------------------------------------------------------------------------
function makeFaceGlow(discR) {
  const size = discR * 2.05;
  const peak = (2 * 7.25) / size;
  const sprite = makeRadialSprite(size, [
    [0.00, 'rgba(0,0,0,0)'],
    [Math.max(0.05, peak * 0.62), 'rgba(20,32,74,0.02)'],
    [Math.max(0.10, peak * 0.86), 'rgba(34,54,120,0.07)'],
    [Math.min(0.96, peak * 1.00), 'rgba(40,64,142,0.10)'],
    [Math.min(0.99, peak * 1.14), 'rgba(24,40,92,0.03)'],
    [1.00, 'rgba(0,0,0,0)'],
  ]);
  sprite.position.z = -3.0;
  return sprite;
}

function makeHalo() {
  const sprite = makeRadialSprite(30, [
    [0.00, 'rgba(0,0,0,0)'],
    [0.55, 'rgba(0,0,0,0)'],
    [0.72, 'rgba(30,46,110,0.035)'],
    [0.86, 'rgba(44,70,160,0.05)'],
    [1.00, 'rgba(0,0,0,0)'],
  ]);
  sprite.position.z = -6;
  return sprite;
}

/**
 * Gene-block material: a 1-pixel outline derived from the box's local position
 * (constant screen width via fwidth). Same treatment as the demo's genes.
 */
function makeGeneMaterial() {
  const material = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: true });
  material.onBeforeCompile = shader => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
        varying vec3 vLocal;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vLocal = position;`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying vec3 vLocal;`)
      .replace('#include <dithering_fragment>', `
        float ex = 0.5 - abs(vLocal.x);
        float ey = 0.5 - abs(vLocal.y);
        float dmin = min(ex, ey);
        float w = max(fwidth(dmin), 1e-5);
        float border = 1.0 - smoothstep(w * 0.8, w * 2.4, dmin);
        gl_FragColor.rgb *= mix(1.0, 0.30, border);
        #include <dithering_fragment>`);
  };
  return material;
}

/** Draft assembly atlas: the bacterial-genome default is a draft circular layout. */
export const assemblyView = {
  id: 'assembly',
  title: '3D 基因组圈图',
  subtitle: 'DRAFT CIRCULAR GENOME ATLAS',
  description: '按细菌基因组常见方式，将 ≥10 kb contigs 从大到小排列成 draft 圈图；这是布局方式，不声明 contigs 已闭合。可切换到线性视图，并从全部 contig 列表选择一个 contig 居中查看。',
  controls: data => {
    const sorted = data.contigs.slice().sort((a, b) => b.length - a.length);
    const maxKb = Math.max(10, Math.ceil(sorted[0].length / 1000));
    return [
      {
        key: 'layout', label: '布局', type: 'select', value: 'circular',
        options: [
          { value: 'circular', label: 'Draft 圈图（从大到小）' },
          { value: 'linear', label: '线性单 contig 视图' },
        ],
      },
      { key: 'thresholdKb', label: '圈图 contig 阈值', type: 'range', min: 0, max: maxKb, step: 1, value: 10, unit: ' kb' },
      {
        key: 'contig', label: 'Contig 列表（线性视图居中）', type: 'select',
        value: sorted[0]?.id || '',
        options: sorted.map((contig, rank) => ({ value: contig.id, label: contigOptionLabel(rank, contig) })),
      },
      { key: 'explode', label: '拆解命中块', type: 'range', min: 0, max: 1, step: 0.05, value: 0 },
      { key: 'labels', label: '显示 contig / 坐标标签', type: 'toggle', value: true },
      { key: 'gc', label: '显示 GC / GC-skew 轨道', type: 'toggle', value: true },
    ];
  },

  create({ root, data, host, registerPickable }) {
    const sorted = data.contigs
      .filter(contig => Number.isFinite(contig.length) && contig.length > 0)
      .sort((a, b) => b.length - a.length);
    if (!sorted.length) throw new Error('assembly 数据缺少 contigs');
    const rankById = new Map(sorted.map((contig, rank) => [contig.id, rank]));
    const features = Array.isArray(data.features) ? data.features : [];
    const featureByContig = new Map(sorted.map(contig => [contig.id, []]));
    for (const feature of features) featureByContig.get(feature.contig)?.push(feature);
    const featureById = new Map(features.map(feature => [feature.id, feature]));

    host.setBloom({ strength: 0.30, radius: 0.34, threshold: 0.80 });
    host.setAutoRotate(true, 0.4);

    // --- atmosphere, persistent across layout rebuilds (decorative only) ---
    const faceGlow = makeFaceGlow(RING.bezelOuter);
    const halo = makeHalo();
    const dust = makeDustField({ count: 320, radius: 42, color: 0x7f9ad8, size: 2.0, opacity: 0.35 });
    root.add(faceGlow, halo, dust);

    const layoutGroup = new THREE.Group();
    layoutGroup.name = 'assembly-layout';
    root.add(layoutGroup);
    const overlay = new THREE.Group();
    overlay.name = 'assembly-overlay';
    root.add(overlay);

    let dynamicPickables = [];
    let labelObjects = [], gcObjects = [], lodLabels = [];
    let labelsOn = true;
    let contigMeshes = new Map();
    let placements = [];
    let featureMesh = null;
    let arcs = new Map();
    let currentRing = [];
    let layoutKind = 'circular';
    let thresholdKb = 10;
    let selectedContigId = sorted[0].id;
    let explode = 0;
    let selected = null;
    let hovered = null;
    let selArc = null, selRect = null, selLabel = null, selLine = null;

    // ---- sidebar list state (demo's objects / sites / legend blocks) -------
    let sidebarEl = null;
    const KINDS = ['amr', 'vir'];
    const kindFilter = new Set(KINDS);
    let kindFilterOn = false;
    const featureKind = feature => (feature.kind === 'amr' ? 'amr' : 'vir');
    const truncText = (text, n) => {
      const value = String(text ?? '');
      return value.length > n ? `${value.slice(0, n - 1)}…` : value;
    };

    function addPickable(object, payload) {
      dynamicPickables.push(object);
      return registerPickable(object, payload);
    }

    function hideMarks() {
      for (const mark of [selArc, selRect, selLabel, selLine]) if (mark) mark.visible = false;
    }

    function clearLayout() {
      selected = null;
      hovered = null;
      syncSidebarSelection();
      for (const object of dynamicPickables) host.unregisterPickable(object);
      dynamicPickables = [];
      labelObjects = []; gcObjects = []; lodLabels = [];
      contigMeshes = new Map(); placements = []; arcs = new Map();
      featureMesh = null;
      hideMarks();
      disposeHierarchy(layoutGroup);
    }

    // ---- shared helpers -----------------------------------------------------
    function arcLine(r0, a0, a1, color, opacity, z, additive = false) {
      const steps = Math.max(8, Math.ceil((a1 - a0) / 0.012));
      const points = [];
      for (let i = 0; i <= steps; i++) {
        const a = a0 + (a1 - a0) * i / steps;
        points.push(new THREE.Vector3(Math.cos(a) * r0, -Math.sin(a) * r0, z));
      }
      return new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({
          color, transparent: true, opacity,
          ...(additive ? { blending: THREE.AdditiveBlending, depthWrite: false } : {}),
        }),
      );
    }

    function centerLabel(text, color, height, y = 0) {
      const label = makeLabel(text, { color, height, fontSize: 30, align: 'center' });
      label.position.set(0, y, 0.06);
      layoutGroup.add(label);
      labelObjects.push(label);
      return label;
    }

    // ---- circular draft layout ----------------------------------------------
    function renderCircular() {
      const threshold = thresholdKb * 1000;
      currentRing = sorted.filter(contig => contig.length >= threshold);
      if (!currentRing.length) currentRing = [sorted[0]];
      const totalBp = currentRing.reduce((sum, contig) => sum + contig.length, 0);
      const gapAngle = Math.min(0.018, (Math.PI * 2 / currentRing.length) * 0.20);
      const usable = Math.PI * 2 - gapAngle * currentRing.length;
      let cursor = Math.PI / 2;

      // one merged vertex-colour mesh carries every engraved mark + tick
      const pos = [], col = [];

      for (const contig of currentRing) {
        const arcWidth = contig.length / totalBp * usable;
        const a0 = cursor, a1 = cursor + arcWidth;
        arcs.set(contig.id, { a0, width: arcWidth, contig });
        const angleOf = bp => a0 + (bp / contig.length) * arcWidth;

        // ---- backbone: subtle per-segment shade variation -------------------
        const segCount = Math.max(10, Math.ceil(arcWidth / 0.10));
        const bPos = [], bCol = [];
        for (let s = 0; s < segCount; s++) {
          const s0 = a0 + arcWidth * s / segCount;
          const s1 = a0 + arcWidth * (s + 1) / segCount;
          const shade = 0.09 + 0.03 * ((s * 7919) % 5) / 4;
          addAnnularSector(bPos, bCol, RING.backboneInner, RING.backboneOuter, s0, s1, 0,
            [srgbToLinear(shade), srgbToLinear(shade + 0.016), srgbToLinear(shade + 0.045)]);
        }
        const backbone = sectorMeshFromArrays(bPos, bCol);
        backbone.name = `contig:${contig.id}`;
        layoutGroup.add(addPickable(backbone, { type: 'contig', id: contig.id }));
        contigMeshes.set(contig.id, backbone);

        // glowing mid line, like the demo's backbone separator
        layoutGroup.add(arcLine(
          (RING.backboneInner + RING.backboneOuter) / 2, a0, a1, 0x3b4ba8, 0.45, 0.02, true));

        // ---- GC content ribbon + GC skew line -------------------------------
        // Track arrays may be ragged in real data — iterate the shortest
        // length and tolerate non-finite cells instead of emitting NaN verts.
        const track = contig.track;
        const trackLen = track
          ? Math.min(track.pos?.length ?? 0, track.gc?.length ?? 0, track.skew?.length ?? 0)
          : 0;
        if (trackLen > 1) {
          const mean = Number.isFinite(contig.gc)
            ? contig.gc
            : track.gc.slice(0, trackLen).reduce((x, y) => x + y, 0) / trackLen;
          const gcAt = i => (Number.isFinite(track.gc[i]) ? track.gc[i] : mean);
          const gPos = [], gCol = [];
          const amp = RING.gcContW * 0.5;
          for (let i = 0; i < trackLen - 1; i++) {
            const t0 = angleOf(track.pos[i]), t1 = angleOf(track.pos[i + 1]);
            const d0 = clamp((gcAt(i) - mean) / 6, -1, 1);
            const d1 = clamp((gcAt(i + 1) - mean) / 6, -1, 1);
            const rgb = (d0 + d1) / 2 > 0
              ? [srgbToLinear(0.22), srgbToLinear(0.48), srgbToLinear(0.92)]
              : [srgbToLinear(0.92), srgbToLinear(0.55), srgbToLinear(0.22)];
            const i0 = [Math.cos(t0) * RING.gcCont, -Math.sin(t0) * RING.gcCont, -0.01];
            const o0 = [Math.cos(t0) * (RING.gcCont + d0 * amp), -Math.sin(t0) * (RING.gcCont + d0 * amp), -0.01];
            const i1 = [Math.cos(t1) * RING.gcCont, -Math.sin(t1) * RING.gcCont, -0.01];
            const o1 = [Math.cos(t1) * (RING.gcCont + d1 * amp), -Math.sin(t1) * (RING.gcCont + d1 * amp), -0.01];
            pushTri(gPos, gCol, i0, o0, i1, rgb);
            pushTri(gPos, gCol, i1, o0, o1, rgb);
          }
          const gcRibbon = sectorMeshFromArrays(gPos, gCol, { transparent: true, opacity: 0.72 });
          gcRibbon.material.depthWrite = false;
          layoutGroup.add(gcRibbon);
          gcObjects.push(gcRibbon);

          const skewPoints = track.pos.slice(0, trackLen).map((position, index) => {
            const a = angleOf(position);
            const skew = Number.isFinite(track.skew[index]) ? track.skew[index] : 0;
            const radius = RING.gcSkew + clamp(skew * 6, -1, 1) * RING.gcSkewW * 0.5;
            return new THREE.Vector3(Math.cos(a) * radius, -Math.sin(a) * radius, -0.01);
          });
          const skewLine = lineFromPoints(skewPoints, 0x35c9a4, 0.85);
          layoutGroup.add(skewLine);
          gcObjects.push(skewLine);
        }

        // ---- genomic scale on the bezel: sub / minor / major ticks ----------
        const target = clamp(Math.round(arcWidth / 0.65), 2, 9);
        const major = niceStepFor(contig.length, target);
        const subSpacing = (major / 25) / contig.length * arcWidth;
        const minorSpacing = (major / 5) / contig.length * arcWidth;
        if (subSpacing > 0.004) {
          for (let bp = 0; bp < contig.length; bp += major / 25) {
            const a = angleOf(bp);
            addAnnularSector(pos, col, RING.tickIn, RING.tickSub, a, a + 0.0016, 0, hexRgb(0x28324a));
          }
        }
        if (minorSpacing > 0.01) {
          for (let bp = 0; bp < contig.length; bp += major / 5) {
            const a = angleOf(bp);
            addAnnularSector(pos, col, RING.tickIn, RING.tickMinor, a, a + 0.0022, 0, hexRgb(0x4a5a80));
          }
        }
        const majorGap = major / contig.length * arcWidth;
        for (let bp = 0; bp <= contig.length; bp += major) {
          const a = angleOf(Math.min(bp, contig.length));
          addAnnularSector(pos, col, RING.tickIn, RING.tickOut, a, a + 0.0030, 0, hexRgb(0x9aabd8));
        }
        // coordinate labels sized to stay legible, skipped when they collide
        if (arcWidth > 0.15) {
          for (let bp = 0; bp <= contig.length; bp += major) {
            const a = angleOf(Math.min(bp, contig.length));
            const label = makeLabel(fmtBpTick(bp, contig.length), {
              color: 'rgba(178,192,232,0.85)', height: 0.30, fontSize: 28, align: 'center',
            });
            if (label.userData.worldWidth / RING.labelR > majorGap * 1.6) { disposeHierarchy(label); continue; }
            label.position.set(Math.cos(a) * RING.labelR, -Math.sin(a) * RING.labelR, 0.03);
            layoutGroup.add(label);
            lodLabels.push(label);
          }
        }

        // ---- contig name outside the bezel ----------------------------------
        const mid = a0 + arcWidth / 2;
        const shortId = contig.id.length > 22 ? `${contig.id.slice(0, 21)}…` : contig.id;
        const nameLabel = makeLabel(`${shortId} · ${formatBp(contig.length)}`, {
          color: '#9aabd8', height: 0.27, fontSize: 22, align: 'center',
        });
        if (nameLabel.userData.worldWidth / RING.nameR < arcWidth * 0.9) {
          nameLabel.position.set(Math.cos(mid) * RING.nameR, -Math.sin(mid) * RING.nameR, 0.18);
          layoutGroup.add(nameLabel);
          lodLabels.push(nameLabel);
        } else {
          disposeHierarchy(nameLabel);
        }

        // ---- CARD / VFDB hits on the two strand bands -----------------------
        for (const feature of featureByContig.get(contig.id) || []) {
          if (!Number.isFinite(feature.start) || !Number.isFinite(feature.end) ||
              feature.end <= feature.start) continue;
          const plus = feature.strand === '+';
          const rMid = plus ? (RING.plusInner + RING.plusOuter) / 2 : (RING.minusInner + RING.minusOuter) / 2;
          const f0 = angleOf(clamp(feature.start, 0, contig.length));
          const f1 = angleOf(clamp(feature.end, 0, contig.length));
          const fm = (f0 + f1) / 2;
          const width = Math.max(0.05, 2 * rMid * Math.sin((f1 - f0) / 2));
          const c = Math.cos(fm), s = Math.sin(fm);
          placements.push({
            feature,
            pos: new THREE.Vector3(c * rMid, -s * rMid, FEATURE_DEPTH / 2),
            tx: -s, ty: -c, rx: c, ry: -s,
            w: width, h: BAND_THICKNESS, liftScale: 1,
            arc: {
              r0: (plus ? RING.plusInner : RING.minusInner) - 0.08,
              r1: (plus ? RING.plusOuter : RING.minusOuter) + 0.08,
              a0: f0, a1: f1, mid: fm,
            },
          });
        }

        cursor = a1 + gapAngle;
      }

      // ---- engraved face: hairlines, bezel edges, band reference circles ----
      for (const radius of RING.hairlines) {
        addAnnularSector(pos, col, radius, radius + 0.012, 0, Math.PI * 2, -0.03, hexRgb(0x1b2436));
      }
      addAnnularSector(pos, col, RING.bezelInner, RING.bezelInner + 0.035, 0, Math.PI * 2, -0.02, hexRgb(0x3d4d75));
      addAnnularSector(pos, col, RING.bezelOuter - 0.035, RING.bezelOuter, 0, Math.PI * 2, -0.02, hexRgb(0x3d4d75));
      const bezel = sectorMeshFromArrays(pos, col);
      bezel.name = 'bezel';
      layoutGroup.add(bezel);

      const refMat = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.05 });
      for (const radius of [RING.minusInner, RING.minusOuter, RING.backboneInner, RING.backboneOuter, RING.plusInner, RING.plusOuter]) {
        layoutGroup.add(new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(circlePoints(radius, 0.01)), refMat));
      }

      centerLabel(`DRAFT CIRCULAR LAYOUT · ≥ ${formatCoordinate(threshold)}`, '#eef2ff', 0.46);
      centerLabel(`${currentRing.length} contigs · ${formatBp(totalBp)} · sorted by length`, '#8b9cc8', 0.30, -0.55);

      buildFeatureInstances();
    }

    // ---- linear single-contig map (the demo's flat map, in the same 3D scene)
    function renderLinear() {
      const contig = sorted.find(item => item.id === selectedContigId) || sorted[0];
      selectedContigId = contig.id;
      currentRing = [contig];
      const width = 20, x0 = -width / 2;
      const xOf = bp => x0 + (bp / contig.length) * width;
      const AXIS = 0.9, GENE_H = 0.5;

      const frame = { x0: x0 - 0.6, x1: x0 + width + 0.6, y0: -3.55, y1: 2.05 };
      layoutGroup.add(lineFromPoints([
        new THREE.Vector3(frame.x0, frame.y0, 0.02), new THREE.Vector3(frame.x1, frame.y0, 0.02),
        new THREE.Vector3(frame.x1, frame.y1, 0.02), new THREE.Vector3(frame.x0, frame.y1, 0.02),
        new THREE.Vector3(frame.x0, frame.y0, 0.02),
      ], 0x3a4d78, 0.65));

      // graticule + ruler
      const step = niceStepFor(contig.length, 8);
      const GC_TOP = -0.15, GC_BOT = -1.15, SKEW_TOP = -1.6, SKEW_BOT = -2.4, RULE_Y = -2.75;
      for (let bp = 0; bp <= contig.length; bp += step) {
        const x = xOf(bp);
        layoutGroup.add(lineFromPoints([
          new THREE.Vector3(x, frame.y1 - 0.1, 0.01), new THREE.Vector3(x, RULE_Y + 0.15, 0.01),
        ], 0x28324a, 0.35));
        layoutGroup.add(lineFromPoints([
          new THREE.Vector3(x, RULE_Y - 0.10, 0.02), new THREE.Vector3(x, RULE_Y + 0.10, 0.02),
        ], 0x7e8bb0, 0.7));
        const label = makeLabel(formatCoordinate(bp), { color: '#7e8bb0', height: 0.24, fontSize: 21, align: 'center' });
        label.position.set(x, RULE_Y - 0.42, 0.02);
        layoutGroup.add(label);
        labelObjects.push(label);
      }

      // backbone spine — pickable like the circular arcs
      const spine = new THREE.Mesh(
        new THREE.BoxGeometry(width, 0.12, 0.08),
        new THREE.MeshBasicMaterial({ color: 0x1d2c4d }),
      );
      spine.position.set(0, AXIS, 0.02);
      spine.name = `contig:${contig.id}`;
      layoutGroup.add(addPickable(spine, { type: 'contig', id: contig.id }));
      contigMeshes.set(contig.id, spine);
      layoutGroup.add(lineFromPoints([
        new THREE.Vector3(x0, AXIS, 0.06), new THREE.Vector3(x0 + width, AXIS, 0.06),
      ], 0x3b4ba8, 0.7));

      // CARD / VFDB hits: + strand above the axis, − strand below (demo layout)
      for (const feature of featureByContig.get(contig.id) || []) {
        if (!Number.isFinite(feature.start) || !Number.isFinite(feature.end) ||
            feature.end <= feature.start) continue;
        const plus = feature.strand === '+';
        const y0 = plus ? AXIS + 0.12 : AXIS - 0.12 - GENE_H;
        const f0 = xOf(clamp(feature.start, 0, contig.length));
        const f1 = xOf(clamp(feature.end, 0, contig.length));
        placements.push({
          feature,
          pos: new THREE.Vector3((f0 + f1) / 2, y0 + GENE_H / 2, FEATURE_DEPTH / 2),
          tx: 1, ty: 0, rx: 0, ry: 1,
          w: Math.max(0.12, f1 - f0), h: GENE_H, liftScale: 0.5,
          rect: { x0: f0, x1: f1, y0, y1: y0 + GENE_H },
        });
        if (f1 - f0 > 1.5) {
          const hex = `#${featHex(feature).toString(16).padStart(6, '0')}`;
          const geneLabel = makeLabel(feature.gene, { color: hex, height: 0.20, fontSize: 18, align: 'center' });
          geneLabel.position.set((f0 + f1) / 2, plus ? y0 + GENE_H + 0.28 : y0 - 0.28, 0.05);
          layoutGroup.add(geneLabel);
          labelObjects.push(geneLabel);
        }
      }

      // GC content + GC skew strip charts
      const track = contig.track;
      const trackLen = track
        ? Math.min(track.pos?.length ?? 0, track.gc?.length ?? 0, track.skew?.length ?? 0)
        : 0;
      const gcGroup = new THREE.Group();
      if (trackLen > 1) {
        const strip = (top, bottom) => {
          const mesh = new THREE.Mesh(
            new THREE.PlaneGeometry(width, top - bottom),
            new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.03, depthWrite: false }),
          );
          mesh.position.set(0, (top + bottom) / 2, 0.01);
          gcGroup.add(mesh);
          return mesh;
        };
        strip(GC_TOP, GC_BOT);
        strip(SKEW_TOP, SKEW_BOT);
        const midY = (GC_TOP + GC_BOT) / 2, skewY = (SKEW_TOP + SKEW_BOT) / 2;
        gcGroup.add(lineFromPoints([
          new THREE.Vector3(x0, midY, 0.02), new THREE.Vector3(x0 + width, midY, 0.02),
        ], 0x28324a, 0.5));
        gcGroup.add(lineFromPoints([
          new THREE.Vector3(x0, skewY, 0.02), new THREE.Vector3(x0 + width, skewY, 0.02),
        ], 0x28324a, 0.5));
        const mean = Number.isFinite(contig.gc)
          ? contig.gc
          : track.gc.slice(0, trackLen).reduce((a, b) => a + b, 0) / trackLen;
        const gcLine = lineFromPoints(track.pos.slice(0, trackLen).map((position, index) => new THREE.Vector3(
          xOf(position),
          midY - clamp(((Number.isFinite(track.gc[index]) ? track.gc[index] : mean) - mean) / 8, -1, 1) * (GC_TOP - GC_BOT),
          0.04,
        )), 0x4dd6a0, 0.9);
        const skewLine = lineFromPoints(track.pos.slice(0, trackLen).map((position, index) => new THREE.Vector3(
          xOf(position),
          skewY - clamp((Number.isFinite(track.skew[index]) ? track.skew[index] : 0) * 6, -1, 1) * (SKEW_TOP - SKEW_BOT) / 2,
          0.04,
        )), 0x6d8bff, 0.85);
        gcGroup.add(gcLine, skewLine);
      }
      layoutGroup.add(gcGroup);
      gcObjects.push(gcGroup);

      const title = makeLabel(
        `${contig.id} · ${formatBp(contig.length)} · linear contig`,
        { color: '#dfe6f8', height: 0.40, fontSize: 27, align: 'center' },
      );
      title.position.set(0, 2.75, 0.04);
      layoutGroup.add(title);
      labelObjects.push(title);
      const rank = rankById.get(contig.id) + 1;
      const sub = makeLabel(
        `LINEAR MAP · + ABOVE / − BELOW · length rank ${rank} / ${sorted.length}`,
        { color: '#7e8bb0', height: 0.26, fontSize: 22, align: 'center' },
      );
      sub.position.set(0, 2.30, 0.04);
      layoutGroup.add(sub);
      labelObjects.push(sub);
      const gcTag = makeLabel('GC CONTENT', { color: '#7e8bb0', height: 0.20, fontSize: 18, align: 'left' });
      gcTag.position.set(x0 + 0.15, GC_TOP + 0.28, 0.04);
      const skewTag = makeLabel('GC SKEW', { color: '#7e8bb0', height: 0.20, fontSize: 18, align: 'left' });
      skewTag.position.set(x0 + 0.15, SKEW_TOP + 0.28, 0.04);
      layoutGroup.add(gcTag, skewTag);
      labelObjects.push(gcTag, skewTag);

      buildFeatureInstances();
    }

    // ---- one InstancedMesh for every hit (single draw call, like the demo) --
    function buildFeatureInstances() {
      if (!placements.length) return;
      featureMesh = new THREE.InstancedMesh(
        new THREE.BoxGeometry(1, 1, 1), makeGeneMaterial(), placements.length);
      featureMesh.instanceColor = new THREE.InstancedBufferAttribute(
        new Float32Array(placements.length * 3), 3);
      placements.forEach((placement, index) => setFeatureColor(index, featHex(placement.feature)));
      applyExplode(explode);
      featureMesh.userData.pickFor = instanceId => {
        const feature = placements[instanceId].feature;
        if (kindFilterOn && !kindFilter.has(featureKind(feature))) return null;
        return { type: 'feature', id: feature.id };
      };
      layoutGroup.add(registerPickable(featureMesh, null));
      dynamicPickables.push(featureMesh);
    }

    function setFeatureColor(index, hex) {
      const [r, g, b] = hexRgb(hex);
      featureMesh.instanceColor.setXYZ(index, r, g, b);
      featureMesh.instanceColor.needsUpdate = true;
    }

    function featureIndex(id) {
      return placements.findIndex(placement => placement.feature.id === id);
    }

    function applyExplode(value) {
      if (!featureMesh) return;
      const matrix = new THREE.Matrix4();
      const tangent = new THREE.Vector3(), radial = new THREE.Vector3(), normal = new THREE.Vector3(0, 0, 1);
      const position = new THREE.Vector3();
      placements.forEach((placement, index) => {
        if (kindFilterOn && !kindFilter.has(featureKind(placement.feature))) {
          // filtered-out hits are parked far below the face: invisible and
          // unreachable by the raycaster
          matrix.makeScale(1, 1, 1);
          matrix.setPosition(0, 0, -1e5);
          featureMesh.setMatrixAt(index, matrix);
          return;
        }
        const lift = value * EXPLODE_LIFT * placement.liftScale +
          (selected?.type === 'feature' && selected.id === placement.feature.id ? 0.55 : 0);
        position.copy(placement.pos);
        position.z += lift;
        tangent.set(placement.tx, placement.ty, 0);
        radial.set(placement.rx, placement.ry, 0);
        matrix.makeBasis(tangent, radial, normal);
        matrix.scale(new THREE.Vector3(placement.w, placement.h, FEATURE_DEPTH));
        matrix.setPosition(position);
        featureMesh.setMatrixAt(index, matrix);
      });
      featureMesh.instanceMatrix.needsUpdate = true;
      updateSelectionMarks();
    }

    // ---- selection marks: white arc on the ring / rect on the flat map ------
    function ensureSelLine() {
      if (!selLine) {
        selLine = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
          new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.6 }));
        overlay.add(selLine);
      }
    }

    function updateSelectionMarks() {
      hideMarks();
      if (!selected) return;
      if (selected.type === 'feature') {
        const index = featureIndex(selected.id);
        if (index < 0) return;
        const placement = placements[index];
        if (kindFilterOn && !kindFilter.has(featureKind(placement.feature))) return;
        const lift = explode * EXPLODE_LIFT * placement.liftScale + 0.55;
        if (placement.arc) {
          const { r0, r1, a0, a1, mid } = placement.arc;
          // enforce a minimum on-screen width so a sub-pixel hit stays visible
          const probe = new THREE.Vector3(Math.cos(mid) * r1, -Math.sin(mid) * r1, 0);
          const dist = host.camera.position.distanceTo(probe);
          const hPx = host.canvas.clientHeight || 900;
          const wpp = (2 * dist * Math.tan((host.camera.fov * Math.PI / 180) / 2)) / hPx;
          const minAng = (5 * wpp) / Math.max(0.001, (r0 + r1) / 2);
          const half = Math.max(minAng, a1 - a0) / 2;
          const p = [], c = [];
          addAnnularSector(p, c, r0, r1, mid - half, mid + half, lift + FEATURE_DEPTH + 0.06, [1, 1, 1]);
          if (!selArc) {
            selArc = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({
              color: 0xffffff, side: THREE.DoubleSide, depthWrite: false }));
            selArc.renderOrder = 5;
            overlay.add(selArc);
          }
          selArc.material.transparent = false;
          selArc.material.opacity = 1;
          selArc.material.needsUpdate = true;
          selArc.geometry.dispose();
          const geometry = new THREE.BufferGeometry();
          geometry.setAttribute('position', new THREE.Float32BufferAttribute(p, 3));
          selArc.geometry = geometry;
          selArc.visible = true;
        } else if (placement.rect) {
          const { x0, x1, y0, y1 } = placement.rect;
          if (!selRect) {
            selRect = new THREE.LineLoop(
              new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x53e6ff }));
            selRect.renderOrder = 5;
            overlay.add(selRect);
          }
          const pad = 0.09;
          selRect.geometry.dispose();
          selRect.geometry = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(x0 - pad, y0 - pad, lift + FEATURE_DEPTH + 0.05),
            new THREE.Vector3(x1 + pad, y0 - pad, lift + FEATURE_DEPTH + 0.05),
            new THREE.Vector3(x1 + pad, y1 + pad, lift + FEATURE_DEPTH + 0.05),
            new THREE.Vector3(x0 - pad, y1 + pad, lift + FEATURE_DEPTH + 0.05),
          ]);
          selRect.visible = true;
        }
        // floating label + leader line above the selected hit
        ensureSelLine();
        const base = placement.pos.clone();
        base.z += lift;
        const dist = host.camera.position.distanceTo(base);
        const tip = base.clone()
          .add(new THREE.Vector3(0, Math.max(0.5, dist * 0.06), Math.max(0.4, dist * 0.03)));
        selLine.geometry.setFromPoints([base, tip]);
        selLine.geometry.attributes.position.needsUpdate = true;
        selLine.visible = true;
        if (selLabel) {
          selLabel.position.copy(tip);
          selLabel.visible = true;
        }
      } else if (selected.type === 'contig' && layoutKind === 'circular') {
        const arc = arcs.get(selected.id);
        if (!arc) return;
        const p = [], c = [];
        addAnnularSector(p, c, RING.backboneInner - 0.08, RING.backboneOuter + 0.08,
          arc.a0, arc.a0 + arc.width, FEATURE_DEPTH + 0.06, [1, 1, 1]);
        if (!selArc) {
          selArc = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({
            color: 0xffffff, side: THREE.DoubleSide, depthWrite: false }));
          selArc.renderOrder = 5;
          overlay.add(selArc);
        }
        selArc.material.transparent = true;
        selArc.material.opacity = 0.35;
        selArc.material.needsUpdate = true;
        selArc.geometry.dispose();
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(p, 3));
        selArc.geometry = geometry;
        selArc.visible = true;
      } else if (selected.type === 'contig' && layoutKind === 'linear') {
        if (!selRect) {
          selRect = new THREE.LineLoop(
            new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x53e6ff }));
          selRect.renderOrder = 5;
          overlay.add(selRect);
        }
        selRect.geometry.dispose();
        selRect.geometry = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(-10.1, 0.70, 0.08), new THREE.Vector3(10.1, 0.70, 0.08),
          new THREE.Vector3(10.1, 1.10, 0.08), new THREE.Vector3(-10.1, 1.10, 0.08),
        ]);
        selRect.visible = true;
      }
    }

    // ---- selection ----------------------------------------------------------
    function clearSelection() {
      if (!selected) return;
      if (selected.type === 'feature') {
        const index = featureIndex(selected.id);
        if (index >= 0) setFeatureColor(index, featHex(placements[index].feature));
      }
      selected = null;
      hideMarks();
      applyExplode(explode);
    }

    function select(payload) {
      if (selected?.type === 'feature' && payload?.id !== selected.id) {
        const index = featureIndex(selected.id);
        if (index >= 0) setFeatureColor(index, featHex(placements[index].feature));
      }
      if (hovered?.type === 'feature' && hovered.id !== payload?.id) {
        const index = featureIndex(hovered.id);
        if (index >= 0) setFeatureColor(index, featHex(placements[index].feature));
      }
      selected = payload || null;
      if (selected?.type === 'feature') {
        const index = featureIndex(selected.id);
        if (index >= 0) setFeatureColor(index, 0xffffff);
        if (selLabel) { overlay.remove(selLabel); disposeHierarchy(selLabel); }
        selLabel = makeLabel(featureById.get(selected.id)?.gene || selected.id, {
          color: '#ffffff', height: 0.42, fontSize: 30, align: 'center' });
        overlay.add(selLabel);
      }
      // a contig selection (canvas or control) also rescopes the sites list,
      // like the demo's selectedReplicon
      if (selected?.type === 'contig' && selectedContigId !== selected.id &&
          sorted.some(item => item.id === selected.id)) {
        selectedContigId = selected.id;
        if (sidebarEl) { renderSiteList(); renderSidebarLegend(); }
      }
      hideMarks();
      applyExplode(explode);
      syncSidebarSelection();
    }

    function payloadPosition(payload) {
      if (payload?.type === 'contig' && layoutKind === 'circular') {
        const arc = arcs.get(payload.id);
        if (arc) {
          const mid = arc.a0 + arc.width / 2;
          return new THREE.Vector3(Math.cos(mid) * 6.4, -Math.sin(mid) * 6.4, 0);
        }
      }
      if (payload?.type === 'feature') {
        const index = featureIndex(payload.id);
        if (index >= 0) return placements[index].pos.clone();
      }
      if (payload?.type === 'contig' && layoutKind === 'linear') return new THREE.Vector3(0, 0.9, 0);
      return null;
    }

    function focusPayload(payload) {
      const position = payloadPosition(payload);
      if (!position) return;
      if (layoutKind === 'circular' && payload?.type === 'feature') {
        // stand outside the ring, looking inwards at the hit
        const radial = new THREE.Vector3(position.x, position.y, 0).normalize();
        const want = position.clone()
          .add(radial.multiplyScalar(4.5))
          .add(new THREE.Vector3(0, 2.2, 5.5));
        host.flyTo(want, position);
      } else if (layoutKind === 'circular') {
        const arc = arcs.get(payload.id);
        const distance = arc ? 13 + arc.width * 4 : 20;
        host.flyTo(position.clone().add(new THREE.Vector3(0, distance * 0.22, distance * 0.9)), position);
      } else {
        host.flyTo(position.clone().add(new THREE.Vector3(0, 1.0, 7)), position);
      }
    }

    // ---- left sidebar blocks: objects / searchable sites / legend ----------
    // Same structure as the demo's #sidebar. The view owns this container;
    // list clicks route through the same select/focus paths as canvas picks.
    function syncSidebarSelection() {
      if (!sidebarEl) return;
      // rep-row.on marks the scoped object (drives the sites list), like the
      // demo's selectedReplicon — not the transient canvas selection
      sidebarEl.querySelectorAll('.rep-row').forEach(btn =>
        btn.classList.toggle('on', btn.dataset.id === selectedContigId));
      sidebarEl.querySelectorAll('.gene-row').forEach(btn =>
        btn.classList.toggle('on', selected?.type === 'feature' && btn.dataset.id === selected.id));
    }

    function scopeContig() {
      return sorted.find(item => item.id === selectedContigId) || sorted[0];
    }

    /** Route a contig activation through the framework select control so the
     *  dropdown stays in sync; falls back to the internal path if missing. */
    function goContig(id) {
      const control = sidebarEl?.closest('aside')?.querySelector('select[data-key="contig"]');
      if (control) {
        control.value = id;
        control.dispatchEvent(new Event('input'));
        return;
      }
      setContigActive(id);
    }

    function setContigActive(id) {
      selectedContigId = id;
      if (sidebarEl) { renderSiteList(); renderSidebarLegend(); }
      if (layoutKind === 'linear') {
        render();
        host.resetCamera();
      } else {
        select({ type: 'contig', id });
        focusPayload({ type: 'contig', id });
      }
    }

    function renderObjectList() {
      const box = sidebarEl.querySelector('[data-role="objects"]');
      box.innerHTML = sorted.map((contig, rank) => {
        const hits = featureByContig.get(contig.id)?.length || 0;
        return `<button class="rep-row" data-id="${escapeHtml(contig.id)}">
          <div class="rname"><span>${escapeHtml(truncText(contig.id, 24))}</span><span class="rlen">${formatBp(contig.length)}</span></div>
          <div class="rmeta"><span>#${rank + 1}${contig.name ? ` · ${escapeHtml(truncText(contig.name, 16))}` : ''}</span><span><b>${hits}</b> hits</span>${hits ? `<span class="hot"><b>${hits}</b> AMR/VIR</span>` : ''}</div>
        </button>`;
      }).join('');
      box.querySelectorAll('.rep-row').forEach(btn =>
        btn.addEventListener('click', () => goContig(btn.dataset.id)));
      syncSidebarSelection();
    }

    function renderSiteList() {
      const box = sidebarEl.querySelector('[data-role="sites"]');
      const countEl = sidebarEl.querySelector('[data-role="site-count"]');
      const q = (sidebarEl.querySelector('[data-role="search"]').value || '').trim().toLowerCase();
      const contig = scopeContig();
      let pool = (featureByContig.get(contig.id) || []).slice().sort((a, b) => a.start - b.start);
      const total = pool.length;
      if (kindFilterOn) pool = pool.filter(feature => kindFilter.has(featureKind(feature)));
      if (q) {
        pool = pool.filter(feature =>
          [feature.gene, feature.product, feature.database, feature.contig]
            .some(value => String(value ?? '').toLowerCase().includes(q)));
      }
      countEl.textContent = (kindFilterOn || q) ? `${pool.length}/${total}` : `${total}`;
      const MAX_ROWS = 220;
      const rows = pool.slice(0, MAX_ROWS);
      box.innerHTML = rows.map((feature, index) => {
        const hex = `#${featHex(feature).toString(16).padStart(6, '0')}`;
        return `<button class="gene-row" data-id="${escapeHtml(feature.id)}">
          <span class="idx">${String(index + 1).padStart(2, '0')}</span>
          <span class="gr-main">
            <b><span style="color:${hex}">|</span> ${escapeHtml(feature.gene || feature.id || '—')}</b>
            <em>${escapeHtml(truncText(feature.product || feature.database || feature.contig, 46))}</em>
          </span>
          <span class="tag" style="color:${hex}">${featureKind(feature).toUpperCase()}</span>
        </button>`;
      }).join('') + (pool.length > MAX_ROWS
        ? `<div class="gene-note">仅显示前 ${MAX_ROWS} 条（共 ${pool.length}）· 可用搜索缩小</div>`
        : (rows.length ? '' : `<div class="gene-note">${kindFilterOn && !kindFilter.size ? '全不选：没有可显示的类别' : '该 contig 没有匹配的命中'}</div>`));
      box.querySelectorAll('.gene-row').forEach(btn => btn.addEventListener('click', () => {
        const payload = { type: 'feature', id: btn.dataset.id };
        select(payload);
        focusPayload(payload);
      }));
      syncSidebarSelection();
    }

    function renderSidebarLegend() {
      const el = sidebarEl.querySelector('[data-role="legend"]');
      const contig = scopeContig();
      const windowKb = contig.track?.window ? `${(contig.track.window / 1000).toFixed(0)} kb ` : '';
      const counts = { amr: 0, vir: 0 };
      for (const feature of features) counts[featureKind(feature)]++;
      const stateOf = kind =>
        (kindFilterOn && kindFilter.has(kind) ? ' on' : '') +
        (kindFilterOn && !kindFilter.has(kind) ? ' dim' : '');
      el.innerHTML = `
        <div class="lg-head"><span class="t">轨道 · Tracks</span><span class="n">${escapeHtml(truncText(contig.id, 18))}</span></div>
        <div class="lg-tracks">
          <div><i class="sw-plus"></i>+ 链命中带（外侧）</div>
          <div><i class="sw-minus"></i>− 链命中带（内侧）</div>
          <div><i class="sw-gc"></i>GC 含量 ${windowKb}滑窗</div>
          <div><i class="sw-skew"></i>GC skew (G−C)/(G+C)</div>
        </div>
        <div class="lg-head" style="border-top:1px solid var(--border-subtle);margin-top:8px;padding-top:8px">
          <span class="t">筛查数据库 · Screening</span>
          <span class="n">${kindFilterOn ? `${kindFilter.size}/${KINDS.length} 选中` : `${features.length} hits`}</span>
        </div>
        <div class="lg-actions">
          <button data-act="all">全选</button>
          <button data-act="none">全不选</button>
          <button data-act="reset">重置</button>
        </div>
        <div class="lg-grid">
          <button class="lg-item${stateOf('amr')}" data-kind="amr">
            <i style="background:#ff2d55"></i><span class="lg-code">AMR</span>CARD 耐药<b>${counts.amr}</b></button>
          <button class="lg-item${stateOf('vir')}" data-kind="vir">
            <i style="background:#ff8a3d"></i><span class="lg-code">VIR</span>VFDB 毒力<b>${counts.vir}</b></button>
        </div>`;
      el.querySelectorAll('.lg-item').forEach(btn => btn.addEventListener('click', () => {
        const kind = btn.dataset.kind;
        if (kindFilter.has(kind)) kindFilter.delete(kind); else kindFilter.add(kind);
        kindFilterOn = kindFilter.size < KINDS.length;
        applyExplode(explode);
        renderSidebarLegend();
        renderSiteList();
      }));
      el.querySelectorAll('.lg-actions button').forEach(btn => btn.addEventListener('click', () => {
        kindFilter.clear();
        if (btn.dataset.act !== 'none') KINDS.forEach(kind => kindFilter.add(kind));
        kindFilterOn = kindFilter.size < KINDS.length;
        applyExplode(explode);
        renderSidebarLegend();
        renderSiteList();
      }));
    }

    function mountSidebar(el) {
      sidebarEl = el;
      el.innerHTML = `
        <div class="blk">
          <div class="blk-head"><span class="t">复制子 · Objects</span><span class="n">${sorted.length} contigs</span></div>
          <div data-role="objects"></div>
        </div>
        <div class="blk grow">
          <div class="blk-head"><span class="t">位点 · Sites</span><span class="n" data-role="site-count"></span></div>
          <div class="sb-search"><input data-role="search" type="search" placeholder="基因 / 产物 / contig" spellcheck="false"></div>
          <div id="gene-list" data-role="sites"></div>
        </div>
        <div id="legend" class="blk" data-role="legend"></div>`;
      el.querySelector('[data-role="search"]').addEventListener('input', renderSiteList);
      renderObjectList();
      renderSiteList();
      renderSidebarLegend();
    }

    function render() {
      clearLayout();
      if (layoutKind === 'linear') renderLinear();
      else renderCircular();
    }

    render();

    return {
      debug: () => ({
        layout: layoutKind, ring: currentRing.length, placements: placements.length,
      }),
      stats: () => {
        const threshold = thresholdKb * 1000;
        const included = layoutKind === 'circular' ? currentRing.length : sorted.filter(item => item.length >= threshold).length;
        return [
          { label: '组装总长度', value: formatBp(data.total_bp) },
          { label: 'Contigs', value: sorted.length },
          { label: '圈图 contigs', value: layoutKind === 'circular' ? `${included} / ${sorted.length}` : `${included} eligible` },
          { label: 'CARD / VFDB 命中', value: features.length },
        ];
      },
      resetCamera: () => {
        if (layoutKind === 'circular') {
          host.controls.maxDistance = 120;
          host.setCamera(new THREE.Vector3(0.5, 8.5, 34), new THREE.Vector3(0.3, 0.4, 0));
        } else {
          host.controls.maxDistance = 120;
          host.setCamera(new THREE.Vector3(0, 0.6, 27), new THREE.Vector3(0, -0.3, 0));
        }
      },
      setOption: (key, value) => {
        if (key === 'layout') {
          layoutKind = value === 'linear' ? 'linear' : 'circular';
          render();
          host.resetCamera();
        }
        if (key === 'thresholdKb') {
          thresholdKb = Math.max(0, Number(value));
          if (layoutKind === 'circular') render();
          host.resetCamera();
        }
        if (key === 'contig') setContigActive(String(value));
        if (key === 'explode') {
          explode = clamp(Number(value) || 0, 0, 1);
          applyExplode(explode);
        }
        if (key === 'labels') {
          labelsOn = !!value;
          labelObjects.forEach(object => { object.visible = labelsOn; });
        }
        if (key === 'gc') gcObjects.forEach(object => { object.visible = value; });
      },
      select,
      hover: payload => {
        if (hovered?.type === 'feature' && hovered.id !== selected?.id && hovered.id !== payload?.id) {
          const index = featureIndex(hovered.id);
          if (index >= 0) setFeatureColor(index, featHex(placements[index].feature));
        }
        hovered = payload;
        if (hovered?.type === 'feature' && hovered.id !== selected?.id) {
          const index = featureIndex(hovered.id);
          if (index >= 0) setFeatureColor(index, brighten(featHex(placements[index].feature), 0.55));
        }
      },
      focus: focusPayload,
      mountSidebar,
      selectionLabel: payload => {
        if (payload?.type === 'contig') return payload.id;
        if (payload?.type === 'feature') return featureById.get(payload.id)?.gene || payload.id;
        return '—';
      },
      update: dt => {
        dust.rotation.y += dt * 0.03;
        dust.rotation.x += dt * 0.011;
        halo.material.opacity = 0.75 + Math.sin(performance.now() * 0.0012) * 0.15;
        // LOD: contig names + bp labels belong to the overview; hide them when
        // zoomed in close enough to read individual hits
        const overview = layoutKind !== 'circular' ||
          host.camera.position.distanceTo(host.controls.target) >= LOD_LABEL_DISTANCE;
        for (const label of lodLabels) label.visible = labelsOn && overview;
        // keep the floating selection label sized for the current zoom
        if (selLabel?.visible && selected?.type === 'feature') {
          const dist = host.camera.position.distanceTo(selLabel.position);
          const k = clamp(dist / 27, 0.10, 2.4);
          selLabel.scale.set((selLabel.userData.worldWidth || 4) * k, 0.42 * k, 1);
        }
      },
      tooltip: payload => {
        if (payload?.type === 'contig') {
          const contig = sorted.find(item => item.id === payload.id);
          const rank = rankById.get(contig.id) + 1;
          return `<div class="tt-name">${escapeHtml(contig.id)}</div>
            <div class="tt-sub">#${rank} · ${formatBp(contig.length)} · GC ${contig.gc}%</div>
            <div class="tt-sub">draft contig · circular layout only</div>`;
        }
        if (payload?.type === 'feature') {
          const feature = featureById.get(payload.id);
          return `<div class="tt-name">${escapeHtml(feature.gene)}</div>
            <div class="tt-sub">${escapeHtml(feature.database)} · ${escapeHtml(feature.contig)}</div>
            <div class="tt-sub">${feature.start + 1}–${feature.end} · ${feature.strand}</div>`;
        }
        return '';
      },
      inspect: payload => {
        if (payload?.type === 'contig') {
          const contig = sorted.find(item => item.id === payload.id);
          const hits = featureByContig.get(contig.id) || [];
          const rank = rankById.get(contig.id) + 1;
          return `<div class="detail-title">${escapeHtml(contig.id)}</div>
            <p class="detail-subtitle">draft assembly contig · ${escapeHtml(contig.name)}</p>
            <div class="metric-grid"><div><span>长度</span><b>${formatBp(contig.length)}</b></div><div><span>长度排名</span><b>#${rank}</b></div><div><span>GC</span><b>${contig.gc}%</b></div><div><span>筛查命中</span><b>${hits.length}</b></div></div>
            <dl class="kv"><dt>拓扑</dt><dd>draft contig（未声明闭合）</dd><dt>GC bins</dt><dd>${contig.track?.pos?.length || 0}</dd><dt>命中基因</dt><dd>${hits.map(hit => escapeHtml(hit.gene)).join(', ') || '—'}</dd></dl>
            <p class="detail-footnote">圈图是 draft contigs 的常见可视化布局，不代表该 contig 已闭合。线性视图可从左侧 contig 列表选择并居中查看。</p>`;
        }
        if (payload?.type === 'feature') {
          const feature = featureById.get(payload.id);
          return `<div class="detail-title">${escapeHtml(feature.gene)}</div>
            <p class="detail-subtitle">${feature.kind === 'amr' ? 'CARD 耐药命中' : 'VFDB 毒力命中'} · ${escapeHtml(feature.database)}</p>
            <div class="metric-grid"><div><span>Identity</span><b>${feature.identity ?? '—'}%</b></div><div><span>Coverage</span><b>${feature.coverage ?? '—'}%</b></div><div><span>长度</span><b>${formatBp(feature.end - feature.start)}</b></div><div><span>链</span><b>${escapeHtml(feature.strand)}</b></div></div>
            <dl class="kv"><dt>Contig</dt><dd>${escapeHtml(feature.contig)}</dd><dt>坐标</dt><dd>${feature.start + 1}–${feature.end}</dd><dt>产物</dt><dd>${escapeHtml(feature.product || '—')}</dd></dl>`;
        }
        return '';
      },
    };
  },
};
