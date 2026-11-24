// Generates apps/risk/tests/fixtures/js_parity.json from the frontend's own risk model.
// Reads the frontend source only; never writes to it.
//
//   node scripts/risk_parity/generate.mjs
//
// Re-run whenever src/lib/risk.js or src/data/cities.js change in the frontend.
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, '../../../vconnects-travel/src');
const out = resolve(here, '../../apps/risk/tests/fixtures/js_parity.json');

const { scoreTrip, routeProfile } = await import(pathToFileURL(resolve(frontend, 'lib/risk.js')).href);
const { CITIES } = await import(pathToFileURL(resolve(frontend, 'data/cities.js')).href);
const { DRIVERS, VEHICLES } = await import(pathToFileURL(resolve(frontend, 'data/rides.js')).href);

const pick = ({ verifiedId, verifiedLicense, rating, trips }) => ({ verifiedId, verifiedLicense, rating, trips });
const drivers = [
  null,
  ...DRIVERS.map(pick),
  { verifiedId: false, verifiedLicense: false, rating: null, trips: 0 }, // Publish page newcomer
  { verifiedId: true, verifiedLicense: true, rating: null, trips: 0 },
  { verifiedId: true, verifiedLicense: false, rating: 3.2, trips: 30 },
  { verifiedId: false, verifiedLicense: true, rating: 2.5, trips: 99 },
  { verifiedId: true, verifiedLicense: true, rating: 5, trips: 100 },
];
const year = new Date().getFullYear();
const vehicles = [
  null,
  ...VEHICLES.map(({ year, features }) => ({ year, features })),
  { year, features: [] },
  { year: year + 1, features: ['airbags'] },
  { year: year - 13, features: ['airbags', 'gps'] },
  { year: 1999, features: ['abs', 'dashcam', 'gps', 'firstaid', 'airbags'] },
];
const times = ['00:00', '00:30', '04:45', '05:15', '06:00', '06:29', '10:00', '16:50', '18:45', '19:30', '21:00', '22:30', '23:59'];

// Small deterministic PRNG so the fixture is stable between runs.
let seed = 12345;
const rnd = (n) => {
  seed = (Math.imul(seed, 1103515245) + 12345) >>> 0;
  return (seed >>> 8) % n;
};

const pairs = [];
for (const a of CITIES) for (const b of CITIES) if (a.code !== b.code) pairs.push([a.code, b.code]);

const cases = [];
const add = (from, to) => {
  const month = String(1 + rnd(12)).padStart(2, '0');
  const depart = `2026-${month}-15T${times[rnd(times.length)]}`;
  const driver = drivers[rnd(drivers.length)];
  const vehicle = vehicles[rnd(vehicles.length)];
  cases.push({ input: { from, to, depart, driver, vehicle }, output: scoreTrip({ fromCode: from, toCode: to, depart, driver, vehicle }) });
};
pairs.forEach(([a, b]) => add(a, b)); // every ordered pair at least once
for (let i = 0; i < 320; i++) add(...pairs[rnd(pairs.length)]);

const routes = [];
for (let i = 0; i < CITIES.length; i++)
  for (let j = i + 1; j < CITIES.length; j++) {
    const [a, b] = [CITIES[i].code, CITIES[j].code].sort();
    routes.push({ a, b, ...routeProfile(a, b) });
  }

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify({ year, routes, cases }));
console.log(`Wrote ${cases.length} cases and ${routes.length} routes to ${out}`);
