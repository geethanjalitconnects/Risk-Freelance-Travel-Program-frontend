export const clampProgress = (value) => Math.max(0, Math.min(1, value));

// Wheel radius of the 3D car (metres) and how far it drives over the whole scroll journey.
export const WHEEL_RADIUS = 0.358;
export const JOURNEY_DISTANCE = 18;

// Camera views the scroll passes through, like the SPARQ reference:
// front 3/4 -> top-down -> rear 3/4 -> low side -> front 3/4.
// az: 0 = in front of the car, +90 = car's right side, 180 = behind. el: degrees above ground.
const VIEWS = [
  { p: 0.0, az: -38, el: 13, dist: 7.2 },
  { p: 0.15, az: -30, el: 20, dist: 7.2 },
  { p: 0.3, az: -8, el: 80, dist: 10.2 },
  { p: 0.42, az: 15, el: 82, dist: 10.2 },
  { p: 0.58, az: 150, el: 34, dist: 8.5 },
  { p: 0.78, az: 285, el: 9, dist: 7.6 },
  { p: 1.0, az: 322, el: 14, dist: 7.2 },
];

const ease = (t) => t * t * (3 - 2 * t);

// Everything is a pure function of scroll progress, so scrolling back plays it in reverse
// (camera moves back and the wheels roll backwards).
export function carMotion(progress) {
  const p = clampProgress(progress);
  let i = 0;
  while (i < VIEWS.length - 2 && p > VIEWS[i + 1].p) i += 1;
  const a = VIEWS[i];
  const b = VIEWS[i + 1];
  const t = ease(clampProgress((p - a.p) / (b.p - a.p)));
  const mix = (k) => a[k] + (b[k] - a[k]) * t;
  return {
    az: mix('az'),
    el: mix('el'),
    dist: mix('dist'),
    steering: Math.sin(p * Math.PI * 4) * 0.3,
    // Rolling angle (rad), positive = rolling forward. Distance / radius, so wheels match the travel.
    wheelRotation: (p * JOURNEY_DISTANCE) / WHEEL_RADIUS,
  };
}
