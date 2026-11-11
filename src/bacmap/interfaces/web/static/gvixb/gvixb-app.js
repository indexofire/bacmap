import * as THREE from './vendor/three.module.js';
import { createAnalysisFramework } from './framework/analysis-framework.js';
import { assemblyView } from './views/assembly-view.js';
import { phyloView } from './views/phylo-view.js';
import { mstView } from './views/mst-view.js';
import { circularAnnotationView } from './views/circular-annotation-view.js';

const mount = document.getElementById('app');
const canvas = document.getElementById('scene');
const definitions = {
  assembly: assemblyView, phylo: phyloView, mst: mstView, circle: circularAnnotationView,
};
const definition = definitions[mount.dataset.view];
if (!definition) throw new Error(`未知 gvixb 视图：${mount.dataset.view}`);

// One result, one endpoint. The bacmap route—not a client-side demo selector—sets it.
const selectedView = { ...definition, dataUrl: mount.dataset.endpoint };
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setClearColor(0x05070d, 1);

const framework = createAnalysisFramework({ renderer, canvas, views: [selectedView] });
const clock = new THREE.Clock();

function resize() {
  const width = window.innerWidth, height = window.innerHeight;
  renderer.setSize(width, height);
  framework.resize();
}
window.addEventListener('resize', resize);
resize();
framework.activate(selectedView.id);

function animate() {
  requestAnimationFrame(animate);
  framework.tick(clock.getDelta());
}
animate();

// Read-only diagnostics for local integration tests and support.
window.__gvixb = {
  debug: () => framework.debug(),
  pickAt: (x, y) => { const payload = framework.pickAt(x, y); return payload ? { id: payload.id } : null; },
};
