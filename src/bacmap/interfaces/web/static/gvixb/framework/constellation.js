import * as THREE from '../vendor/three.module.js';
import {
  makeLabel, makePillLabel, makeCallout, makeRingTexture, makeDotTexture, makeDotSprite, escapeHtml,
  disposeHierarchy,
} from './primitives.js';
import { clamp } from './algorithms.js';

/**
 * Network "constellation" renderer shared by graph-like views (MST, radial
 * phylogeny): the visual language of the reference network video —
 * solid flat dots, hairline edges blended into a haze, category decks floating
 * on a horizontal disc seen at a low pitch, pill tags, a callout box + ring on
 * the selection, and a few decorative light pulses.
 *
 * Coordinates are supplied by the view. Deck height (Y) encodes category
 * membership only; colour, glow and pulses carry no statistics.
 */

/** Warm-on-dark categorical palette of the reference video. */
export const NETWORK_PALETTE = ['#ff7a1a', '#f5e6c8', '#ff4d2e', '#f2c14e', '#d8dde8', '#ffae42', '#e8705a', '#c9b38a'];
export const NETWORK_NEUTRAL = '#aab3c5';
export const NETWORK_ACCENT = '#ff7a1a';

const backOut = t => { const s = 1.70158; const x = t - 1; return 1 + (s + 1) * x * x * x + s * x * x; };
const PULSE_COUNT = 12;

export function createConstellation({
  root, host, registerPickable, nodes, edges, layers,
  accent = NETWORK_ACCENT, showLabels = true, showEdgeLabels = false, sidebarNote = '',
  decks: drawDecks = layers.size > 1, heightAxis = null, legendTitle = '分组图层 · Decks',
  legendNote = null, pulsesOn: initialPulses = true, glow: initialGlow = 0.2, edgeAlpha: initialEdgeAlpha = 0.6,
  sizeScale: initialSizeScale = 1,
}) {
  const ownPickables = [];
  const pick = (object, payload) => { ownPickables.push(object); return registerPickable(object, payload); };
  const scene = new THREE.Group();
  scene.name = 'constellation';
  root.add(scene);
  const deckGroup = new THREE.Group(), edgeLabelGroup = new THREE.Group();
  const nodeGroup = new THREE.Group(), labelGroup = new THREE.Group(), overlay = new THREE.Group();
  overlay.name = 'constellation-overlay';
  scene.add(deckGroup, nodeGroup, labelGroup, edgeLabelGroup, overlay);
  labelGroup.visible = showLabels;
  edgeLabelGroup.visible = showEdgeLabels;

  // glow 0..1 drives the dot halo (alpha + width) and the bloom pass together
  const dotTextureFor = g => makeDotTexture({ halo: 0.32 * g, spread: g, crisp: g < 0.35, rim: true });
  let glow = clamp(Number(initialGlow) || 0, 0, 1);
  let dotTexture = dotTextureFor(glow);
  const ringTexture = makeRingTexture();
  const hiddenLayers = new Set();
  const layerVisible = key => !hiddenLayers.has(key);
  const nodeVisible = i => layerVisible(nodes[i].layer);
  let edgeFilter = null;
  const edgeVisible = i => nodeVisible(edges[i].source) && nodeVisible(edges[i].target)
    && (!edgeFilter || edgeFilter(edges[i]));
  const layerOrder = key => layers.get(key)?.order ?? 0;

  // ---- nodes: flat solid dots, normal blending so overlaps occlude --------
  const dots = nodes.map((node, i) => {
    const color = new THREE.Color(node.color);
    const dot = makeDotSprite({ color, size: node.size, texture: dotTexture, blending: THREE.NormalBlending });
    dot.position.copy(node.position);
    dot.userData.baseColor = color.clone();
    dot.userData.pickPriority = 1;
    dot.scale.setScalar(0.001);
    nodeGroup.add(pick(dot, node.payload));
    return dot;
  });

  const nodeLabels = nodes.map((node, i) => {
    if (!node.label) return null;
    const color = new THREE.Color(node.color).lerp(new THREE.Color('#ffffff'), 0.35).getStyle();
    const label = makeLabel(node.label, { color, height: node.hub ? 0.34 : 0.27, fontSize: 22, align: 'center' });
    label.position.copy(node.position).add(new THREE.Vector3(0, node.size * 0.55 + 0.2, 0));
    label.material.opacity = 0;
    labelGroup.add(label);
    return label;
  });

  // ---- edges: one LineSegments, RGBA vertex colours, additive haze --------
  // dense graphs pile many additive hairlines on top of each other
  const density = clamp(1.1 - edges.length / 2500, 0.55, 1);
  let edgeAlpha = clamp(Number(initialEdgeAlpha) || 0, 0.05, 1);
  const edgePositions = new Float32Array(edges.length * 6);
  const edgeColors = new Float32Array(edges.length * 8);
  edges.forEach((edge, i) => {
    const a = nodes[edge.source].position, b = nodes[edge.target].position;
    edgePositions.set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6);
  });
  const edgeGeometry = new THREE.BufferGeometry();
  edgeGeometry.setAttribute('position', new THREE.BufferAttribute(edgePositions, 3));
  edgeGeometry.setAttribute('color', new THREE.BufferAttribute(edgeColors, 4));
  const edgeMaterial = new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const edgeLines = new THREE.LineSegments(edgeGeometry, edgeMaterial);
  edgeLines.name = 'edges';
  edgeLines.userData.pickFor = (_, hit) => {
    const i = Math.floor((hit?.index ?? -1) / 2);
    if (!edges[i] || !edgeVisible(i)) return null;
    // every edge ends inside a dot: a hit within an endpoint's dot means the
    // user aimed at the node, not at the hairline leaving it
    const point = hit.pointOnLine || hit.point;
    for (const end of [edges[i].source, edges[i].target]) {
      if (point && point.distanceTo(nodes[end].position) <= nodes[end].size * 0.6) return nodes[end].payload;
    }
    return edges[i].payload ?? null;
  };
  scene.add(pick(edgeLines, null));

  let edgeColorFn = edge => [nodes[edge.source].color, nodes[edge.target].color];
  const tmpA = new THREE.Color(), tmpB = new THREE.Color();
  function writeEdgeColors() {
    edges.forEach((edge, i) => {
      const pair = edgeColorFn(edge, i);
      const [ca, cb] = Array.isArray(pair) ? pair : [pair, pair];
      tmpA.set(ca); tmpB.set(cb);
      const alpha = edgeVisible(i) ? edgeAlpha * density : 0;
      edgeColors.set([tmpA.r, tmpA.g, tmpA.b, alpha, tmpB.r, tmpB.g, tmpB.b, alpha], i * 8);
    });
    edgeGeometry.getAttribute('color').needsUpdate = true;
  }
  writeEdgeColors();

  const edgeLabels = edges.map(edge => {
    if (!edge.label) return null;
    const a = nodes[edge.source].position, b = nodes[edge.target].position;
    const label = makeLabel(edge.label, { color: '#c9b38a', height: 0.22, fontSize: 19, align: 'center' });
    label.position.copy(a).lerp(b, 0.5).add(new THREE.Vector3(0, 0.2, 0));
    label.material.opacity = 0;
    edgeLabelGroup.add(label);
    return label;
  });

  // ---- decks: dashed ring + pill tag per category (only when > 1 deck) ----
  const decks = new Map();
  if (drawDecks) {
    for (const [key, layer] of layers) {
      const members = nodes.filter(node => node.layer === key);
      if (!members.length) continue;
      const cx = members.reduce((s, n) => s + n.position.x, 0) / members.length;
      const cz = members.reduce((s, n) => s + n.position.z, 0) / members.length;
      const radius = Math.max(1.2, ...members.map(n => Math.hypot(n.position.x - cx, n.position.z - cz))) + 0.6;
      const points = [];
      for (let k = 0; k <= 128; k++) {
        const a = (k / 128) * Math.PI * 2;
        points.push(new THREE.Vector3(cx + Math.cos(a) * radius, layer.height, cz + Math.sin(a) * radius));
      }
      const ring = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineDashedMaterial({
        color: layer.color, dashSize: 0.22, gapSize: 0.2, transparent: true, opacity: 0, depthWrite: false,
      }));
      ring.computeLineDistances();
      const pill = makePillLabel(`${key} · ${layer.count}`, {
        color: layer.color, border: new THREE.Color(layer.color).getStyle().replace('rgb', 'rgba').replace(')', ',0.6)'),
        height: 0.4, fontSize: 24,
      });
      pill.position.set(cx, layer.height + 0.6, cz);
      pill.material.opacity = 0;
      deckGroup.add(ring, pill);
      decks.set(key, { ring, pill });
    }
  }

  // ---- height axis: required whenever Y encodes a numeric quantity -------
  if (heightAxis && nodes.length) {
    const xs = nodes.map(n => n.position.x), zs = nodes.map(n => n.position.z);
    const ax = Math.min(...xs) - 1.6, az = Math.max(...zs) + 0.4;
    const { y0, y1, ticks = [], label = '' } = heightAxis;
    const axisColor = '#8f97a8';
    deckGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(ax, y0, az), new THREE.Vector3(ax, y1, az),
    ]), new THREE.LineBasicMaterial({ color: axisColor, transparent: true, opacity: 0.6 })));
    for (const tick of ticks) {
      deckGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(ax - 0.18, tick.y, az), new THREE.Vector3(ax + 0.18, tick.y, az),
      ]), new THREE.LineBasicMaterial({ color: axisColor, transparent: true, opacity: 0.6 })));
      const text = makeLabel(tick.text, { color: '#aab3c5', height: 0.24, fontSize: 20, align: 'center' });
      text.position.set(ax - 0.75, tick.y, az);
      deckGroup.add(text);
    }
    if (label) {
      const title = makePillLabel(label, { color: '#d8dde8', height: 0.36, fontSize: 22 });
      title.position.set(ax, Math.max(y0, y1) + 0.7, az);
      deckGroup.add(title);
    }
  }

  // ---- decorative pulses: symmetric streaks from an edge midpoint ---------
  const pulseCount = Math.min(PULSE_COUNT, edges.length);
  const pulsePositions = new Float32Array(pulseCount * 12);
  const pulseColors = new Float32Array(pulseCount * 16);
  const pulseGeometry = new THREE.BufferGeometry();
  pulseGeometry.setAttribute('position', new THREE.BufferAttribute(pulsePositions, 3));
  pulseGeometry.setAttribute('color', new THREE.BufferAttribute(pulseColors, 4));
  const pulseLines = new THREE.LineSegments(pulseGeometry, new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  pulseLines.frustumCulled = false;
  scene.add(pulseLines);
  let seed = 1337;
  const rand = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296;
  const pulses = Array.from({ length: pulseCount }, () => ({ edge: -1, t: 0, dur: 1, delay: 0 }));
  function respawn(pulse) {
    pulse.edge = -1;
    for (let k = 0; k < 8 && edges.length; k++) {
      const i = Math.floor(rand() * edges.length);
      if (edgeVisible(i)) { pulse.edge = i; break; }
    }
    pulse.t = 0;
    pulse.dur = 0.5 + rand() * 0.5;
    pulse.delay = rand() * 1.1;
  }
  pulses.forEach(respawn);
  let pulsesOn = initialPulses;

  // ---- selection marks: accent ring + callout + incident-edge highlight ---
  const ring = new THREE.Sprite(new THREE.SpriteMaterial({
    map: ringTexture, color: accent, transparent: true, depthWrite: false, depthTest: false,
  }));
  ring.renderOrder = 21;
  ring.visible = false;
  overlay.add(ring);
  let callout = null, highlight = null;
  let selectedNode = -1, selectedEdge = -1, hoveredNode = -1;
  let calloutAnchor = null;

  function clearMarks() {
    ring.visible = false;
    if (callout) {
      overlay.remove(callout);
      callout.material.map.dispose();
      callout.material.dispose();
      callout = null;
    }
    if (highlight) {
      overlay.remove(highlight);
      highlight.geometry.dispose();
      highlight.material.dispose();
      highlight = null;
    }
    if (burst) {
      overlay.remove(burst.lines);
      burst.lines.geometry.dispose();
      burst.lines.material.dispose();
      for (const sprite of burst.sparks) { overlay.remove(sprite); sprite.material.dispose(); }
      burst = null;
    }
    calloutAnchor = null;
  }

  function buildHighlight(edgeIndices, colour = '#fff4e0') {
    const visible = edgeIndices.filter(edgeVisible);
    if (!visible.length) return;
    const positions = new Float32Array(visible.length * 6);
    visible.forEach((e, k) => positions.set(edgePositions.subarray(e * 6, e * 6 + 6), k * 6));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    highlight = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({
      color: new THREE.Color(colour).lerp(new THREE.Color('#ffffff'), 0.25), transparent: true, opacity: 0.55, depthWrite: false,
    }));
    highlight.renderOrder = 15;
    overlay.add(highlight);
  }

  // ---- selection burst: fast streaks leaving the selected node along each
  // of its edges (interaction feedback only — not a direction in the data)
  const BURST_TRAVEL = 0.34, BURST_TAIL = 0.3, BURST_PERIOD = BURST_TRAVEL * 2 + 0.2, MAX_STREAKS = 160;
  const SPARKS = [[0, 1], [0.07, 0.62], [0.14, 0.36]];   // [lag along edge, relative size]
  const sparkTexture = makeDotTexture({ halo: 0.85, spread: 1 });
  let burst = null;
  function buildBurst(streaks, colour) {
    if (!streaks.length) return;
    const positions = new Float32Array(streaks.length * 6);
    const colors = new Float32Array(streaks.length * 8);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 4));
    const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    lines.frustumCulled = false;
    lines.renderOrder = 16;
    overlay.add(lines);
    const tint = new THREE.Color(colour).lerp(new THREE.Color('#ffffff'), 0.6);
    const sparks = streaks.flatMap(() => SPARKS.map(([lag, rel]) => {
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: sparkTexture, color: tint, transparent: true, depthWrite: false, depthTest: false,
        blending: THREE.AdditiveBlending,
      }));
      sprite.renderOrder = 23;
      sprite.userData.lag = lag;
      sprite.userData.rel = rel;
      overlay.add(sprite);
      return sprite;
    }));
    burst = { lines, sparks, streaks, colour: tint, t: 0 };
  }
  function updateBurst(dt) {
    if (!burst) return;
    burst.t += dt;
    const cycle = burst.t % BURST_PERIOD;
    const { r, g, b } = burst.colour;
    const positions = burst.lines.geometry.getAttribute('position');
    const colors = burst.lines.geometry.getAttribute('color');
    const p = new THREE.Vector3(), q = new THREE.Vector3();
    const state = burst.streaks.map(([from, to, delay, strength]) => {
      const phase = (cycle - delay) / BURST_TRAVEL;
      const travel = phase >= 0 && phase <= 1;
      const head = travel ? 1 - (1 - phase) * (1 - phase) : 0;
      return { from, to, travel, head, tail: Math.max(0, head - BURST_TAIL), alpha: travel ? (1 - phase * 0.35) * strength : 0 };
    });
    state.forEach(({ from, to, head, tail, alpha }, k) => {
      p.copy(from).lerp(to, tail);
      q.copy(from).lerp(to, head);
      positions.array.set([p.x, p.y, p.z, q.x, q.y, q.z], k * 6);
      colors.array.set([r, g, b, alpha * 0.12, r, g, b, alpha], k * 8);
    });
    positions.needsUpdate = true;
    colors.needsUpdate = true;
    // sparks keep a roughly constant on-screen size
    const size = clamp(host.camera.position.distanceTo(host.controls.target) * 0.02, 0.25, 0.9);
    burst.sparks.forEach((sprite, k) => {
      const { from, to, travel, head, alpha } = state[Math.floor(k / SPARKS.length)];
      sprite.position.copy(from).lerp(to, Math.max(0, head - sprite.userData.lag));
      sprite.visible = travel && head > sprite.userData.lag;
      sprite.material.opacity = alpha;
      sprite.scale.setScalar(size * sprite.userData.rel * (0.6 + 0.4 * alpha));
    });
  }

  function showCallout(anchor, title, subtitle) {
    if (!title) return;
    callout = makeCallout(title, subtitle, { accent, height: 0.9, center: [1.06, -0.25] });
    overlay.add(callout);
    calloutAnchor = anchor.clone();
    callout.position.copy(calloutAnchor);
  }

  let sizeMul = clamp(Number(initialSizeScale) || 1, 0.1, 6);
  const dotScale = i => {
    const size = nodes[i].size * sizeMul;
    if (i === selectedNode) return size * 1.35;
    if (i === hoveredNode) return size * 1.2;
    return size;
  };

  function selectNode(i, { title, subtitle } = {}) {
    clearMarks();
    selectedNode = nodeVisible(i) ? i : -1;
    selectedEdge = -1;
    if (selectedNode < 0) return;
    ring.visible = true;
    ring.position.copy(nodes[i].position);
    const incident = edges.map((edge, e) => (edge.source === i || edge.target === i ? e : -1)).filter(e => e >= 0 && edgeVisible(e));
    buildHighlight(incident, nodes[i].color);
    // wave 1: along every edge of the node; wave 2: onward from each
    // neighbour along its other edges (away from the selection), dimmer
    const streaks = [];
    const neighbours = [];
    for (const e of incident) {
      const other = edges[e].source === i ? edges[e].target : edges[e].source;
      streaks.push([nodes[i].position, nodes[other].position, 0, 1]);
      neighbours.push(other);
    }
    for (const n of neighbours) {
      for (let e = 0; e < edges.length && streaks.length < MAX_STREAKS; e++) {
        const edge = edges[e];
        if ((edge.source !== n && edge.target !== n) || !edgeVisible(e)) continue;
        const next = edge.source === n ? edge.target : edge.source;
        if (next === i) continue;
        streaks.push([nodes[n].position, nodes[next].position, BURST_TRAVEL * 0.8, 0.55]);
      }
    }
    buildBurst(streaks, nodes[i].color);
    showCallout(nodes[i].position, title, subtitle);
    if (introDone) dots.forEach((dot, k) => dot.scale.setScalar(dotScale(k)));
  }

  function selectEdge(e, { title, subtitle } = {}) {
    clearMarks();
    selectedNode = -1;
    selectedEdge = edges[e] && edgeVisible(e) ? e : -1;
    if (selectedEdge < 0) return;
    buildHighlight([e], nodes[edges[e].source].color);
    const mid = edgeMidpoint(e);
    buildBurst([[mid, nodes[edges[e].source].position, 0, 1], [mid, nodes[edges[e].target].position, 0, 1]], nodes[edges[e].source].color);
    showCallout(edgeMidpoint(e), title, subtitle);
    if (introDone) dots.forEach((dot, k) => dot.scale.setScalar(dotScale(k)));
  }

  function clearSelection() {
    clearMarks();
    selectedNode = selectedEdge = -1;
    if (introDone) dots.forEach((dot, k) => dot.scale.setScalar(dotScale(k)));
  }

  function hoverNode(i) {
    hoveredNode = Number.isInteger(i) && i >= 0 ? i : -1;
    if (introDone) dots.forEach((dot, k) => dot.scale.setScalar(dotScale(k)));
  }

  function edgeMidpoint(e) {
    const edge = edges[e];
    return nodes[edge.source].position.clone().lerp(nodes[edge.target].position, 0.5);
  }

  // ---- layer visibility (sidebar legend) ----------------------------------
  let labelsOn = showLabels, edgeLabelsOn = showEdgeLabels;
  function applyVisibility() {
    dots.forEach((dot, i) => { dot.visible = nodeVisible(i); });
    nodeLabels.forEach((label, i) => { if (label) label.visible = nodeVisible(i); });
    edgeLabels.forEach((label, i) => { if (label) label.visible = edgeVisible(i); });
    for (const [key, deck] of decks) deck.ring.visible = deck.pill.visible = layerVisible(key);
    writeEdgeColors();
    pulses.forEach(pulse => { if (pulse.edge >= 0 && !edgeVisible(pulse.edge)) respawn(pulse); });
    if (selectedNode >= 0 && !nodeVisible(selectedNode)) clearSelection();
    if (selectedEdge >= 0 && !edgeVisible(selectedEdge)) clearSelection();
    renderDeckList();
  }

  // ---- sidebar: deck legend + live yaw/pitch readout ---------------------
  let sidebarEl = null, readoutEl = null, readoutClock = 0, floatEl = null;
  function renderDeckList() {
    const box = floatEl?.querySelector?.('[data-role="decks"]');
    if (!box) return;
    box.innerHTML = [...layers.values()].map(layer => `
      <button class="rep-row${layerVisible(layer.group) ? ' on' : ''}" data-layer="${escapeHtml(layer.group)}">
        <div class="rname"><span><i style="display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px;background:${escapeHtml(layer.color)}"></i>${escapeHtml(layer.group)}</span><span class="rlen">${layer.count}</span></div>
      </button>`).join('');
    box.querySelectorAll('.rep-row').forEach(btn => btn.addEventListener('click', () => {
      const key = [...layers.keys()].find(k => String(k) === btn.dataset.layer);
      if (key === undefined) return;
      if (hiddenLayers.has(key)) hiddenLayers.delete(key);
      else if (hiddenLayers.size < layers.size - 1) hiddenLayers.add(key);
      applyVisibility();
    }));
  }

  function mountSidebar(el) {
    sidebarEl = el;
    const single = layers.size <= 1;
    // the layer legend floats over the scene, just right of the sidebar's
    // top corner (position derived from the sidebar rect, host-agnostic)
    if (!single) {
      floatEl = document.createElement('div');
      floatEl.className = 'gvixb-float-legend';
      floatEl.innerHTML = `
        <div class="blk-head"><span class="t">${escapeHtml(legendTitle)}</span><span class="n">${layers.size}</span></div>
        <div data-role="decks"></div>
        <p class="gene-note">${escapeHtml(legendNote ?? '纵向高度只表示分组归属，不表示数值。点击行可隐藏 / 显示该层。')}</p>`;
      document.body.appendChild(floatEl);
    }
    el.innerHTML = `
      <div class="blk side-info">
        <button type="button" class="desc-icon readout-icon" aria-label="视图读数与说明">≡</button>
        <div class="desc-pop side-pop">
          <div class="side-readout" data-role="readout"></div>
          ${single ? '<p>数据未提供多个分组：全部节点位于同一平面。</p>' : ''}
          ${sidebarNote ? `<p>${escapeHtml(sidebarNote)}</p>` : ''}
        </div>
      </div>`;
    readoutEl = el.querySelector('[data-role="readout"]');
    positionLegend();
    renderDeckList();
  }

  function positionLegend() {
    // anchor to the sidebar *panel* (el is an inner container of it), so the
    // legend's top edge lines up with the panel's, 20 px to its right
    const panel = sidebarEl?.closest?.('aside') || sidebarEl;
    const host = panel?.getBoundingClientRect?.();
    if (!floatEl || !host) return;
    floatEl.style.top = `${host.top}px`;
    floatEl.style.left = `${host.right + 20}px`;
  }

  function updateReadout() {
    positionLegend();
    if (!readoutEl) return;
    const offset = host.camera.position.clone().sub(host.controls.target);
    const dist = Math.max(0.0001, offset.length());
    const yaw = ((Math.atan2(offset.x, offset.z) * 180 / Math.PI) + 360) % 360;
    const pitch = Math.asin(clamp(offset.y / dist, -1, 1)) * 180 / Math.PI;
    readoutEl.textContent = `yaw ${yaw.toFixed(1)}° · pitch ${pitch.toFixed(1)}° · ${nodes.length} nodes · ${edges.length} edges`;
  }

  // ---- per-frame: intro, pulses, constant-size marks ----------------------
  const nodeDelay = i => 0.1 + layerOrder(nodes[i].layer) * 0.18 + (i / Math.max(1, nodes.length)) * 0.6;
  const EDGE_T0 = 0.5, EDGE_DUR = 1.0, LABEL_T0 = 1.4, LABEL_DUR = 0.5, INTRO_END = 2.0;
  let elapsed = 0, introDone = false;

  function updatePulses(dt) {
    if (!pulsesOn) { pulseLines.visible = false; return; }
    pulseLines.visible = true;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), m = new THREE.Vector3();
    const c = new THREE.Color();
    pulses.forEach((pulse, p) => {
      pulse.delay -= dt;
      let alpha = 0, head = 0, tail = 0;
      if (pulse.edge >= 0 && pulse.delay <= 0) {
        pulse.t += dt / pulse.dur;
        if (pulse.t >= 1) respawn(pulse);
        head = clamp(pulse.t, 0, 1);
        tail = Math.max(0, head - 0.24);
        alpha = Math.sin(Math.PI * head) * 0.95;
      }
      if (pulse.edge >= 0) {
        const edge = edges[pulse.edge];
        a.copy(nodes[edge.source].position);
        b.copy(nodes[edge.target].position);
        m.copy(a).lerp(b, 0.5);
        c.set(nodes[edge.source].color).lerp(new THREE.Color('#ffffff'), 0.55);
      }
      const p0 = m.clone().lerp(a, tail), p1 = m.clone().lerp(a, head);
      const p2 = m.clone().lerp(b, tail), p3 = m.clone().lerp(b, head);
      pulsePositions.set([p0.x, p0.y, p0.z, p1.x, p1.y, p1.z, p2.x, p2.y, p2.z, p3.x, p3.y, p3.z], p * 12);
      for (let k = 0; k < 4; k++) pulseColors.set([c.r, c.g, c.b, (k % 2 ? alpha : alpha * 0.15)], p * 16 + k * 4);
    });
    pulseGeometry.getAttribute('position').needsUpdate = true;
    pulseGeometry.getAttribute('color').needsUpdate = true;
  }

  function update(dt) {
    if (!introDone) {
      elapsed += dt;
      dots.forEach((dot, i) => {
        const t = clamp((elapsed - nodeDelay(i)) / 0.45, 0, 1);
        dot.scale.setScalar(Math.max(0.001, dotScale(i) * backOut(t)));
      });
      const edgeT = clamp((elapsed - EDGE_T0) / EDGE_DUR, 0, 1);
      edgeMaterial.opacity = edgeT;
      for (const deck of decks.values()) {
        deck.ring.material.opacity = edgeT * 0.28;
        deck.pill.material.opacity = edgeT;
      }
      const labelT = clamp((elapsed - LABEL_T0) / LABEL_DUR, 0, 1);
      for (const label of nodeLabels) if (label) label.material.opacity = labelT;
      for (const label of edgeLabels) if (label) label.material.opacity = labelT;
      if (elapsed >= INTRO_END) {
        introDone = true;
        dots.forEach((dot, i) => dot.scale.setScalar(dotScale(i)));
        edgeMaterial.opacity = 1;
      }
    }
    updatePulses(introDone ? dt : 0);
    // atmospheric depth cueing: nodes shrink slightly and fade with distance,
    // which restores the 3D feel for flat dots and declutters dense far-field
    if (introDone) {
      const ref = Math.max(1e-3, host.camera.position.distanceTo(host.controls.target));
      for (let i = 0; i < dots.length; i++) {
        const d = host.camera.position.distanceTo(nodes[i].position);
        const rel = d / ref;
        dots[i].material.opacity = clamp(1.5 - rel * 0.78, 0.22, 1);
        dots[i].scale.setScalar(dotScale(i) * Math.pow(ref / Math.max(d, 1e-3), 0.5));
        const label = nodeLabels[i];
        if (label) label.material.opacity = clamp(1.3 - rel * 0.55, 0.3, 1);
      }
    }
    updateBurst(dt);

    // marks keep a roughly constant on-screen size
    if (ring.visible && selectedNode >= 0) {
      const dist = host.camera.position.distanceTo(ring.position);
      ring.scale.setScalar(Math.max(nodes[selectedNode].size * sizeMul * 2.4, dist * 0.06));
    }
    if (callout && calloutAnchor) {
      const dist = host.camera.position.distanceTo(calloutAnchor);
      const k = clamp(dist / 22, 0.25, 3);
      callout.scale.set(callout.userData.worldWidth * k, callout.userData.worldHeight * k, 1);
    }
    readoutClock -= dt;
    if (readoutClock <= 0) { readoutClock = 0.2; updateReadout(); }
  }

  function setGlow(value) {
    glow = clamp(Number(value) || 0, 0, 1);
    const previous = dotTexture;
    dotTexture = dotTextureFor(glow);
    for (const dot of dots) { dot.material.map = dotTexture; dot.material.needsUpdate = true; }
    previous.dispose();
    host.setBloom?.({ strength: 0.03 + 0.42 * glow, radius: 0.15 + 0.3 * glow, threshold: 0.72 - 0.2 * glow });
  }
  setGlow(glow);

  return {
    nodePosition: i => nodes[i]?.position || null,
    edgeMidpoint,
    selectNode, selectEdge, clearSelection, hoverNode,
    setLabels: value => { labelsOn = !!value; labelGroup.visible = labelsOn; },
    setEdgeLabels: value => { edgeLabelsOn = !!value; edgeLabelGroup.visible = edgeLabelsOn; },
    setPulses: value => { pulsesOn = !!value; },
    setGlow,
    setEdgeAlpha: value => { edgeAlpha = clamp(Number(value) || 0, 0.05, 1); writeEdgeColors(); },
    // display-only filter (e.g. hide branches with distance > N, GrapeTree
    // style): filtered edges go fully transparent, lose labels/picking and
    // are skipped by pulses and selection bursts; nodes stay in place.
    setEdgeFilter: fn => { edgeFilter = typeof fn === 'function' ? fn : null; applyVisibility(); },
    // uniform size coefficient (GrapeTree "node size" knob): rescales every dot
    // without a rebuild; also rescales the selection ring via update()
    setSizeScale: value => {
      sizeMul = clamp(Number(value) || 1, 0.1, 6);
      if (introDone) dots.forEach((dot, i) => dot.scale.setScalar(dotScale(i)));
    },
    recolorEdges: fn => { edgeColorFn = fn; writeEdgeColors(); },
    mountSidebar,
    update,
    dispose: () => {
      for (const object of ownPickables) host.unregisterPickable(object);
      ownPickables.length = 0;
      root.remove(scene);
      disposeHierarchy(scene);
      sparkTexture.dispose();
      floatEl?.remove();
      sidebarEl = readoutEl = floatEl = null;
    },
    debug: () => ({
      nodes: nodes.length, edges: edges.length, decks: decks.size,
      hiddenLayers: [...hiddenLayers], selectedNode, selectedEdge, labelsOn, edgeLabelsOn,
    }),
  };
}
