import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { carMotion, clampProgress } from './carMotion.js';

// Demonstration car: the Three.js "Ferrari 458" glTF by vicent091 (three.js examples, MIT).
// Swap MODEL_URL for any sedan .glb whose wheels are nodes named wheel_fl / wheel_fr / wheel_rl / wheel_rr
// (axle along the node's local X, origin at the hub). See WHEEL_NODES below to rename.
export const MODEL_URL = '/models/car.glb';
const WHEEL_NODES = [
  { name: 'wheel_fl', front: true },
  { name: 'wheel_fr', front: true },
  { name: 'wheel_rl', front: false },
  { name: 'wheel_rr', front: false },
];

// White "clay" look like the reference: every material becomes matte light grey.
const CLAY = {
  Body_Color: { color: 0xe6e6e4, roughness: 0.42, clearcoat: 0.4, clearcoatRoughness: 0.35 },
  Tires: { color: 0x6c6c6c, roughness: 0.95 },
  metal_gray: { color: 0xd0d0d0, roughness: 0.45, metalness: 0.15 },
  metal_chrome: { color: 0xeeeeee, roughness: 0.3, metalness: 0.2 },
  Glass_Gray: { color: 0x9ea3a9, roughness: 0.2 },
};
const CLAY_DEFAULT = { color: 0xbcbcbc, roughness: 0.7 };

function clayMaterial(source) {
  const spec = CLAY[source.name] ?? CLAY_DEFAULT;
  return new THREE.MeshPhysicalMaterial({ metalness: 0, ...spec });
}

function shadowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, 'rgba(0,0,0,0.38)');
  g.addColorStop(0.55, 'rgba(0,0,0,0.16)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function createCarScene(host, { modelUrl = MODEL_URL, dracoPath = '/draco/', reduce = false, onReady } = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  } catch {
   host.dataset.fallback = 'true'; // No WebGL: show the still photo instead.
return { setProgress() {}, dispose() {} };// The still photo fallback stays visible without WebGL.
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.domElement.setAttribute('aria-hidden', 'true');
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environment = pmrem.fromScene(new RoomEnvironment(), 0.04);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.5;
  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(-4, 8, -5);
  scene.add(key, new THREE.HemisphereLight(0xffffff, 0xcfcfcf, 0.35));

  const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 80);
  const focus = new THREE.Vector3(0, 0.55, 0.17);
  const wheels = [];
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(3.4, 6.4),
    new THREE.MeshBasicMaterial({ map: shadowTexture(), transparent: true, depthWrite: false }),
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(0, 0.004, 0.17);
  scene.add(shadow);

  let disposed = false;
  let progress = 0;
  let target = 0;
  let frame = 0;
  let aspect = 1;

  const render = () => renderer.render(scene, camera);
  const pose = (motion) => {
    const az = THREE.MathUtils.degToRad(motion.az);
    const el = THREE.MathUtils.degToRad(motion.el);
    // Portrait / narrow boxes need the camera further back to keep the whole car in frame.
    const fit = Math.min(2.2, Math.max(1, 1.4 / aspect));
    const d = motion.dist * fit;
    camera.position.set(
      focus.x + d * Math.cos(el) * Math.sin(az),
      focus.y + d * Math.sin(el),
      focus.z - d * Math.cos(el) * Math.cos(az),
    );
    camera.lookAt(focus);
    wheels.forEach(({ node, base, front }) => {
      // Order YXZ: steer about the vertical axis, roll about the axle (local X). Forward is -Z.
      node.rotation.set(base - motion.wheelRotation, front ? motion.steering : 0, 0);
    });
  };
  const apply = () => {
    progress += (target - progress) * (reduce ? 1 : 0.075);
    if (Math.abs(target - progress) < 0.0001) progress = target;
    const motion = carMotion(reduce ? 0 : progress);
    pose(motion);
    host.dataset.progress = progress.toFixed(4);
    host.dataset.wheelRotation = motion.wheelRotation.toFixed(4);
    render();
    frame = progress === target ? 0 : requestAnimationFrame(apply);
  };
  const setProgress = (value, immediate = false) => {
    target = clampProgress(value);
    if (immediate) progress = target;
    if (immediate) apply();
    else if (!frame) frame = requestAnimationFrame(apply);
  };
  const resize = () => {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) return;
    aspect = width / height;
    camera.aspect = aspect;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
    apply();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(host);

  const draco = new DRACOLoader().setDecoderPath(dracoPath);
  const loader = new GLTFLoader().setDRACOLoader(draco);
  loader.load(
    modelUrl,
    (gltf) => {
      if (disposed) return;
      const car = gltf.scene;
      const materials = new Map();
      car.traverse((object) => {
        if (!object.isMesh) return;
        const source = object.material;
        if (!materials.has(source)) materials.set(source, clayMaterial(source));
        object.material = materials.get(source);
      });
      WHEEL_NODES.forEach(({ name, front }) => {
        const node = car.getObjectByName(name);
        if (!node) return;
        const base = node.rotation.x; // the model's own starting angle about the axle
        node.rotation.order = 'YXZ';
        wheels.push({ node, base, front });
      });
      const box = new THREE.Box3().setFromObject(car);
      focus.set((box.min.x + box.max.x) / 2, (box.max.y - box.min.y) * 0.45, (box.min.z + box.max.z) / 2);
      shadow.position.z = focus.z;
      scene.add(car);
      host.dataset.ready = 'true';
      resize();
      onReady?.();
    },
    undefined,() => { if (!disposed) host.dataset.fallback = 'true'; },
  );
  resize();

  return {
    setProgress,
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      draco.dispose();
      scene.traverse((object) => {
        if (!object.isMesh) return;
        object.geometry.dispose();
        object.material.map?.dispose();
        object.material.dispose();
      });
      environment.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      delete host.dataset.ready;
    },
  };
}
