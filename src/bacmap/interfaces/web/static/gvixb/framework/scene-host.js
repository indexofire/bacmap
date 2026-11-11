import * as THREE from '../vendor/three.module.js';
import { OrbitControls } from '../vendor/OrbitControls.js';
import { EffectComposer } from '../vendor/postprocessing/EffectComposer.js';
import { RenderPass } from '../vendor/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '../vendor/postprocessing/UnrealBloomPass.js';
import { OutputPass } from '../vendor/postprocessing/OutputPass.js';
import { disposeHierarchy } from './primitives.js';

/**
 * Shared runtime for analytical visualization plugins.
 * The original genome view and this host reuse one WebGLRenderer, but own
 * separate scenes/cameras so their lifecycle cannot corrupt each other.
 */
export class SceneHost {
  constructor({ renderer, canvas, onHover, onSelect, onReady, onReadout }) {
    this.renderer = renderer;
    this.canvas = canvas;
    this.onHover = onHover || (() => {});
    this.onSelect = onSelect || (() => {});
    this.onReady = onReady || (() => {});
    this.onReadout = onReadout || (() => {});
    this.active = false;
    this.view = null;
    this.definition = null;
    this.pickables = [];
    this.cameraAnim = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x05070d);
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.05, 500);
    this.camera.position.set(0, 3, 26);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.minDistance = 3;
    this.controls.maxDistance = 120;
    this.controls.autoRotateSpeed = 0.45;
    this.controls.enabled = false;

    this.composer = new EffectComposer(renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.composer.addPass(new UnrealBloomPass(new THREE.Vector2(1, 1), 0.24, 0.30, 0.84));
    this.composer.addPass(new OutputPass());

    this.scene.add(new THREE.HemisphereLight(0xa9c2ff, 0x080b13, 2.1));
    const key = new THREE.DirectionalLight(0xf2f5ff, 2.8);
    key.position.set(4, 9, 14);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x53e6ff, 1.3);
    rim.position.set(-10, -3, 7);
    this.scene.add(rim);

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this._bindEvents();
  }

  _bindEvents() {
    let down = null;
    let lastDown = null;
    this.canvas.addEventListener('pointerdown', event => {
      if (!this.active) return;
      down = { x: event.clientX, y: event.clientY };
      lastDown = down;
    });
    this.canvas.addEventListener('pointermove', event => {
      if (!this.active || !this.view) return;
      if (down && Math.hypot(event.clientX - down.x, event.clientY - down.y) > 4) {
        this.onHover(null, event);
        return;
      }
      const payload = this.pick(event.clientX, event.clientY);
      this.onHover(payload, event);
    });
    this.canvas.addEventListener('pointerleave', event => {
      if (!this.active) return;
      down = null;
      this.onHover(null, event);
    });
    this.canvas.addEventListener('pointerup', () => { down = null; });
    this.canvas.addEventListener('click', event => {
      if (!this.active || !this.view) return;
      if (lastDown && Math.hypot(event.clientX - lastDown.x, event.clientY - lastDown.y) > 5) return;
      const payload = this.pick(event.clientX, event.clientY);
      this.view.select?.(payload);
      this.onSelect(payload);
      lastDown = null;
    });
    this.canvas.addEventListener('dblclick', event => {
      if (!this.active || !this.view) return;
      const payload = this.pick(event.clientX, event.clientY);
      if (payload) this.view.focus?.(payload);
    });
  }

  _visible(object) {
    for (let current = object; current; current = current.parent) if (!current.visible) return false;
    return true;
  }

  pick(clientX, clientY) {
    if (!this.view || !this.pickables.length) return null;
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const objects = this.pickables.filter(object => object.parent && this._visible(object));
    const hits = this.raycaster.intersectObjects(objects, false);
    if (!hits.length) return null;
    const hit = hits[0];
    const resolver = hit.object.userData.pickFor;
    return resolver ? resolver(hit.instanceId) : hit.object.userData.pick || null;
  }

  registerPickable(object, payload) {
    object.userData.pick = payload;
    this.pickables.push(object);
    return object;
  }

  unregisterPickable(object) {
    const index = this.pickables.indexOf(object);
    if (index >= 0) this.pickables.splice(index, 1);
  }

  async mount(definition, data) {
    this.clearView();
    this.definition = definition;
    this.root = new THREE.Group();
    this.root.name = `view:${definition.id}`;
    this.scene.add(this.root);
    const context = {
      THREE,
      scene: this.scene,
      root: this.root,
      camera: this.camera,
      controls: this.controls,
      data,
      host: this,
      registerPickable: (object, payload) => this.registerPickable(object, payload),
    };
    this.view = await definition.create(context);
    this.active = true;
    this.controls.enabled = true;
    this.resetCamera();
    this.onReady(this.view, definition, data);
  }

  clearView() {
    this.cameraAnim = null;
    this.controls.autoRotate = false;
    this.onHover(null, null);
    if (this.view?.dispose) this.view.dispose();
    if (this.root) {
      this.scene.remove(this.root);
      disposeHierarchy(this.root);
    }
    this.root = null;
    this.view = null;
    this.definition = null;
    this.pickables = [];
  }

  deactivate() {
    this.active = false;
    this.controls.enabled = false;
    this.controls.autoRotate = false;
    this.cameraAnim = null;
    this.onHover(null, null);
  }

  setCamera(position, target = new THREE.Vector3()) {
    this.cameraAnim = null;
    this.camera.position.copy(position);
    this.controls.target.copy(target);
    this.camera.lookAt(target);
    this.controls.update();
  }

  flyTo(position, target, duration = 0.7) {
    this.controls.autoRotate = false;
    this.cameraAnim = {
      fromPosition: this.camera.position.clone(), toPosition: position.clone(),
      fromTarget: this.controls.target.clone(), toTarget: target.clone(),
      elapsed: 0, duration,
    };
  }

  resetCamera() {
    if (!this.view) return;
    this.cameraAnim = null;
    if (this.view.resetCamera) this.view.resetCamera();
    else this.setCamera(new THREE.Vector3(0, 3, 26), new THREE.Vector3());
  }

  resize(width = window.innerWidth, height = window.innerHeight) {
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
    this.composer.setSize(width, height);
  }

  tick(dt) {
    if (!this.active) return;
    if (this.cameraAnim) {
      const anim = this.cameraAnim;
      anim.elapsed += dt;
      const t = Math.min(1, anim.elapsed / anim.duration);
      const eased = 1 - Math.pow(1 - t, 3);
      this.camera.position.lerpVectors(anim.fromPosition, anim.toPosition, eased);
      this.controls.target.lerpVectors(anim.fromTarget, anim.toTarget, eased);
      if (t >= 1) this.cameraAnim = null;
    }
    this.controls.update();
    this.view?.update?.(dt);
    this.composer.render();
    const distance = this.camera.position.distanceTo(this.controls.target);
    this.onReadout({ zoom: `${(24 / Math.max(0.001, distance)).toFixed(1)}×` });
  }

  exportPng(filename = 'bacmap-3d.png') {
    this.composer.render();
    const link = document.createElement('a');
    link.download = filename;
    link.href = this.canvas.toDataURL('image/png');
    link.click();
  }
}
