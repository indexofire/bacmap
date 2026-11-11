import * as THREE from '../vendor/three.module.js';

export const PALETTE = ['#53e6ff', '#6d8bff', '#45d69b', '#f2c14e', '#ff8a3d', '#ed6a9a', '#a78bfa', '#75b9be'];

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[ch]);
}

export const fmt = (value) => Number(value || 0).toLocaleString('en-US');
export const formatBp = (value) => value >= 1e6 ? `${(value / 1e6).toFixed(2)} Mb` : `${(value / 1e3).toFixed(1)} kb`;

export function groupColors(groups) {
  const map = new Map();
  [...new Set(groups.filter(Boolean))].sort().forEach((group, i) => map.set(group, PALETTE[i % PALETTE.length]));
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
