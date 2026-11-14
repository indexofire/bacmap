import * as THREE from '../vendor/three.module.js';

export const PALETTE = ['#53e6ff', '#6d8bff', '#45d69b', '#f2c14e', '#ff8a3d', '#ed6a9a', '#a78bfa', '#75b9be'];

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[ch]);
}

export const fmt = (value) => Number(value || 0).toLocaleString('en-US');
export const formatBp = (value) => value >= 1e6 ? `${(value / 1e6).toFixed(2)} Mb` : `${(value / 1e3).toFixed(1)} kb`;

export function groupColors(groups, palette = PALETTE) {
  const map = new Map();
  [...new Set(groups.filter(Boolean))].sort().forEach((group, i) => map.set(group, palette[i % palette.length]));
  return map;
}

/** Canvas labels remain crisp and are sized by their actual glyph bounds. */
export function makeLabel(text, { color = '#c3cdf0', height = 0.38, fontSize = 28, align = 'left' } = {}) {
  const canvas = document.createElement('canvas');
  const font = `600 ${fontSize}px ui-monospace, "Cascadia Code", Menlo, monospace`;
  let ctx = canvas.getContext('2d');
  ctx.font = font;
  const padding = 8;
  const width = Math.max(2, Math.ceil(ctx.measureText(String(text)).width) + padding * 2);
  const h = Math.ceil(fontSize * 1.35);
  canvas.width = width;
  canvas.height = h;
  ctx = canvas.getContext('2d');
  ctx.font = font;
  ctx.fillStyle = color;
  ctx.textBaseline = 'middle';
  ctx.textAlign = align;
  ctx.fillText(String(text), align === 'left' ? padding : width / 2, h / 2);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false, depthTest: false });
  const sprite = new THREE.Sprite(material);
  const worldWidth = height * width / h;
  sprite.scale.set(worldWidth, height, 1);
  sprite.center.set(align === 'left' ? 0 : 0.5, 0.5);
  sprite.renderOrder = 20;
  sprite.userData.worldWidth = worldWidth;
  return sprite;
}

export function cylinderBetween(a, b, radius, material, radialSegments = 10) {
  const start = a.isVector3 ? a : new THREE.Vector3(a.x, a.y, a.z || 0);
  const end = b.isVector3 ? b : new THREE.Vector3(b.x, b.y, b.z || 0);
  const delta = end.clone().sub(start);
  const length = Math.max(0.0001, delta.length());
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, length, radialSegments, 1, false), material);
  mesh.position.copy(start).add(end).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize());
  return mesh;
}

export function lineFromPoints(points, color = 0x6d8bff, opacity = 0.5) {
  return new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(points.map(p => p.isVector3 ? p : new THREE.Vector3(p.x, p.y, p.z || 0))),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity }),
  );
}

/**
 * Vertex / instance colour buffers are interpreted as LINEAR-space by three.js.
 * Writing raw sRGB fractions there makes every colour render washed-out, so
 * convert explicitly.
 */
export function srgbToLinear(c) {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function hexRgb(hex) {
  return [
    srgbToLinear(((hex >> 16) & 255) / 255),
    srgbToLinear(((hex >> 8) & 255) / 255),
    srgbToLinear((hex & 255) / 255),
  ];
}

export function pushTri(pos, col, a, b, c, rgb) {
  for (const v of [a, b, c]) { pos.push(v[0], v[1], v[2]); col.push(rgb[0], rgb[1], rgb[2]); }
}

/** Append a flat annular sector (ring segment) to vertex-colour buffers. */
export function addAnnularSector(pos, col, r0, r1, a0, a1, z, rgb, cx = 0, cy = 0) {
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

/** Pack accumulated position/colour arrays into a flat double-sided mesh. */
export function sectorMeshFromArrays(pos, col, { transparent = false, opacity = 1 } = {}) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide, transparent, opacity,
  }));
}

export function circlePoints(r, z, seg = 320, cx = 0, cy = 0) {
  const pts = [];
  for (let i = 0; i < seg; i++) {
    const a = (i / seg) * Math.PI * 2;
    pts.push(new THREE.Vector3(cx + Math.cos(a) * r, cy - Math.sin(a) * r, z));
  }
  return pts;
}

/** Radial-gradient sprite used for glow lenses and halos. */
export function makeRadialSprite(size, stops, blending = THREE.AdditiveBlending) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
  for (const [pos, col] of stops) gradient.addColorStop(pos, col);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 256, 256);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(canvas), transparent: true, depthWrite: false, blending,
  }));
  sprite.scale.set(size, size, 1);
  return sprite;
}

/** Soft round sprite texture for particles; shared per-material and disposed with it. */
function softParticleTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.35, 'rgba(255,255,255,0.55)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/**
 * Texture for the flat "video-style" sample dots: a crisp solid core with a
 * tight soft rim, drawn once per view and shared by every dot sprite.
 */
export function makeDotTexture({ halo: haloAlpha = 0.35, spread = 1, crisp = false, rim = false } = {}) {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const mid = size / 2;
  // the solid core always spans 62 % of the sprite so the dot's visible size
  // stays constant; the halo grows from the core edge by `spread` × the rest
  const core = ctx.createRadialGradient(mid, mid, 0, mid, mid, mid * 0.62);
  core.addColorStop(0, 'rgba(255,255,255,1)');
  core.addColorStop(crisp ? 0.92 : 0.72, 'rgba(255,255,255,1)');
  core.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(mid, mid, mid * 0.62, 0, Math.PI * 2);
  ctx.fill();
  // a dark rim at the core edge keeps same-colour dots that overlap from
  // merging into one blob — important for flat sprite dots
  if (rim) {
    ctx.strokeStyle = 'rgba(5,9,17,0.42)';
    ctx.lineWidth = size * 0.045;
    ctx.beginPath();
    ctx.arc(mid, mid, mid * 0.59, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (haloAlpha > 0 && spread > 0) {
    const outer = mid * (0.62 + 0.38 * Math.min(1, spread));
    const halo = ctx.createRadialGradient(mid, mid, mid * 0.55, mid, mid, outer);
    halo.addColorStop(0, `rgba(255,255,255,${haloAlpha})`);
    halo.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, size, size);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/**
 * Camera-facing flat dot, the node style of the reference video: a 2D round
 * marker floating in 3D space rather than a shaded sphere. `size` is the world
 * diameter; the shared `texture` comes from makeDotTexture() per view.
 */
export function makeDotSprite({ color, size, texture, blending = THREE.AdditiveBlending }) {
  const material = new THREE.SpriteMaterial({
    map: texture, color, transparent: true, depthWrite: false,
    blending, fog: true,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(size, size, 1);
  sprite.userData.dotSize = size;
  sprite.renderOrder = 10;
  return sprite;
}

/** Rounded rectangle path on a 2D canvas context. */
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

function canvasSprite(canvas, worldHeight, center = [0.5, 0.5]) {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: texture, transparent: true, depthWrite: false, depthTest: false,
  }));
  const worldWidth = worldHeight * canvas.width / canvas.height;
  sprite.scale.set(worldWidth, worldHeight, 1);
  sprite.center.set(center[0], center[1]);
  sprite.renderOrder = 22;
  sprite.userData.worldWidth = worldWidth;
  sprite.userData.worldHeight = worldHeight;
  return sprite;
}

/**
 * Pill-shaped tag (dark fill, thin outline) used for cluster / deck names,
 * the floating tag style of the reference network video.
 */
export function makePillLabel(text, { color = '#c3cdf0', border = 'rgba(195,205,240,0.55)', height = 0.42, fontSize = 26 } = {}) {
  const font = `500 ${fontSize}px ui-monospace, "Cascadia Code", Menlo, monospace`;
  const canvas = document.createElement('canvas');
  let ctx = canvas.getContext('2d');
  ctx.font = font;
  const padX = Math.round(fontSize * 0.7), h = Math.ceil(fontSize * 1.75);
  canvas.width = Math.max(h, Math.ceil(ctx.measureText(String(text)).width) + padX * 2);
  canvas.height = h;
  ctx = canvas.getContext('2d');
  roundRect(ctx, 1.5, 1.5, canvas.width - 3, h - 3, (h - 3) / 2);
  ctx.fillStyle = 'rgba(8,11,20,0.82)';
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = border;
  ctx.stroke();
  ctx.font = font;
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(String(text), canvas.width / 2, h / 2 + 1);
  return canvasSprite(canvas, height);
}

/**
 * Selection callout: a dark box with an accent border, a title line and a
 * dimmer accent subtitle. Anchored at its bottom-left corner by default.
 */
export function makeCallout(title, subtitle = '', { accent = '#ff8a3d', height = 1.0, center = [0, 0] } = {}) {
  const titleFont = '500 30px ui-monospace, "Cascadia Code", Menlo, monospace';
  const subFont = '500 21px ui-monospace, "Cascadia Code", Menlo, monospace';
  const canvas = document.createElement('canvas');
  let ctx = canvas.getContext('2d');
  ctx.font = titleFont;
  const tw = ctx.measureText(String(title)).width;
  ctx.font = subFont;
  const sw = ctx.measureText(String(subtitle)).width;
  canvas.width = Math.ceil(Math.max(tw, sw) + 44);
  canvas.height = subtitle ? 100 : 66;
  ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(8,10,16,0.92)';
  ctx.fillRect(2, 2, canvas.width - 4, canvas.height - 4);
  ctx.lineWidth = 3;
  ctx.strokeStyle = accent;
  ctx.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
  ctx.textBaseline = 'middle';
  ctx.font = titleFont;
  ctx.fillStyle = '#eef2ff';
  ctx.fillText(String(title), 22, subtitle ? 36 : canvas.height / 2);
  if (subtitle) {
    ctx.font = subFont;
    ctx.fillStyle = accent;
    ctx.fillText(String(subtitle), 22, 72);
  }
  return canvasSprite(canvas, height * canvas.height / 100, center);
}

/** Thin ring texture (selection halo around a dot). */
export function makeRingTexture() {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.strokeStyle = 'rgba(255,255,255,1)';
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2 - 5, 0, Math.PI * 2);
  ctx.stroke();
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/**
 * Ambient dust field: a deterministic cloud of soft points that gives the
 * scene spatial depth. Purely decorative — carries no data meaning.
 * Pixel-sized stars (no size attenuation) stay crisp at any camera distance.
 */
export function makeDustField({ count = 800, radius = 58, color = 0x8fa3d8, size = 2.2, opacity = 0.5 } = {}) {
  const positions = new Float32Array(count * 3);
  let seed = 20240611;
  const rand = () => {
    // Mulberry32: stable per-mount particle cloud, no Math.random jitter.
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  for (let i = 0; i < count; i++) {
    const u = rand() * 2 - 1;
    const theta = rand() * Math.PI * 2;
    const r = radius * Math.cbrt(rand());
    const s = Math.sqrt(Math.max(0, 1 - u * u));
    positions[i * 3] = r * s * Math.cos(theta);
    positions[i * 3 + 1] = r * s * Math.sin(theta) * 0.72;
    positions[i * 3 + 2] = r * u;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    color, size, map: softParticleTexture(), transparent: true, opacity,
    depthWrite: false, sizeAttenuation: false, blending: THREE.AdditiveBlending,
  });
  const points = new THREE.Points(geometry, material);
  points.name = 'dust-field';
  points.renderOrder = -5;
  points.frustumCulled = false;
  return points;
}

export function disposeHierarchy(root) {
  if (!root) return;
  const geometries = new Set(), materials = new Set(), textures = new Set();
  root.traverse(object => {
    if (object.geometry) geometries.add(object.geometry);
    const mats = Array.isArray(object.material) ? object.material : (object.material ? [object.material] : []);
    for (const material of mats) {
      materials.add(material);
      for (const key of ['map', 'alphaMap', 'emissiveMap']) if (material[key]) textures.add(material[key]);
    }
  });
  for (const texture of textures) texture.dispose();
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
  root.clear();
}

export function metadataRows(metadata, keys) {
  return keys.map(([key, label]) => {
    const value = metadata?.[key];
    if (value === undefined || value === null || value === '') return '';
    return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`;
  }).join('');
}
