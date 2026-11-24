import { cityByCode, cityWeatherRisk, roadKm } from '../data/cities.js';
import { hashString } from './seed.js';

// Illustrative trip-risk model. Every input is simulated for the demo.
// Score runs 0-100, where LOWER is safer.
export const BANDS = [
  { key: 'low', label: 'Low', max: 30 },
  { key: 'moderate', label: 'Moderate', max: 50 },
  { key: 'elevated', label: 'Elevated', max: 70 },
  { key: 'high', label: 'High', max: 101 },
];

export const bandFor = (score) => BANDS.find((b) => score < b.max);

export const VEHICLE_FEATURES = {
  airbags: 'Airbags',
  abs: 'ABS brakes',
  dashcam: 'Dashcam',
  gps: 'GPS tracker',
  firstaid: 'First-aid kit',
};

const clamp = (n, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, n));

export function routeProfile(fromCode, toCode) {
  const from = cityByCode(fromCode);
  const to = cityByCode(toCode);
  const key = [fromCode, toCode].sort().join('-');
  const h = hashString(key);
  const km = roadKm(from, to);
  return {
    km,
    hours: km / 58,
    incidentIndex: Math.round((2 + (h % 700) / 100) * 10) / 10, // 2.0 - 9.0
    highwayShare: 55 + ((h >>> 3) % 40),
    ghatSections: (h >>> 5) % 3,
  };
}

export function driverRisk(driver) {
  if (!driver) return { value: 30, detail: 'Assumes a verified driver (no driver selected).' };
  let v = 70;
  const notes = [];
  if (driver.verifiedId) {
    v -= 22;
    notes.push('ID verified');
  } else notes.push('ID not verified');
  if (driver.verifiedLicense) {
    v -= 18;
    notes.push('licence verified');
  } else notes.push('licence not verified');
  if (driver.rating) {
    v -= (clamp(driver.rating, 3, 5) - 3) * 8;
    notes.push(`${driver.rating.toFixed(1)} rating`);
  } else notes.push('no ratings yet');
  if (driver.trips >= 100) v -= 8;
  else if (driver.trips >= 25) v -= 4;
  notes.push(`${driver.trips} trips`);
  return { value: clamp(v, 8, 95), detail: notes.join(', ') + '.' };
}

export function vehicleRisk(vehicle) {
  if (!vehicle) return { value: 40, detail: 'Assumes a typical vehicle (none selected).' };
  let v = 75;
  const feats = (vehicle.features || []).filter((f) => VEHICLE_FEATURES[f]);
  v -= feats.length * 10;
  const age = new Date().getFullYear() - Number(vehicle.year || new Date().getFullYear());
  if (age <= 5) v -= 10;
  else if (age > 12) v += 10;
  const featText = feats.length ? feats.map((f) => VEHICLE_FEATURES[f]).join(', ') : 'no safety extras listed';
  return { value: clamp(v, 10, 95), detail: `${age <= 0 ? 'New' : age + '-year-old'} vehicle, ${featText}.` };
}

export function scoreTrip({ fromCode, toCode, depart, driver, vehicle }) {
  const from = cityByCode(fromCode);
  const to = cityByCode(toCode);
  const profile = routeProfile(fromCode, toCode);
  const start = new Date(depart);
  const startHour = start.getHours() + start.getMinutes() / 60;

  // Share of the drive that falls at night or dusk, sampled every 15 minutes.
  const steps = Math.max(1, Math.ceil(profile.hours * 4));
  let night = 0;
  let dusk = 0;
  for (let i = 0; i < steps; i++) {
    const h = (startHour + i / 4) % 24;
    if (h >= 22 || h < 5) night++;
    else if ((h >= 19 && h < 22) || (h >= 5 && h < 6.5)) dusk++;
  }
  const nightShare = night / steps;
  const duskShare = dusk / steps;
  const timeValue = clamp(12 + nightShare * 80 + duskShare * 30);

  const hrs = profile.hours;
  const fatigueValue = clamp(hrs <= 4 ? 10 : hrs <= 7 ? 10 + (hrs - 4) * 10 : 40 + (hrs - 7) * 12, 0, 95);

  const month = start.getMonth();
  const weatherValue = Math.max(cityWeatherRisk(from, month), cityWeatherRisk(to, month));

  const d = driverRisk(driver);
  const v = vehicleRisk(vehicle);

  const components = [
    {
      key: 'route',
      label: 'Route',
      weight: 0.25,
      value: Math.round(profile.incidentIndex * 10),
      detail: `Incident index ${profile.incidentIndex}/10, ${profile.highwayShare}% highway${
        profile.ghatSections ? `, ${profile.ghatSections} ghat/hill section${profile.ghatSections > 1 ? 's' : ''}` : ''
      }.`,
    },
    {
      key: 'time',
      label: 'Time of day',
      weight: 0.2,
      value: Math.round(timeValue),
      detail:
        nightShare > 0
          ? `${Math.round(nightShare * 100)}% of the drive is between 10 pm and 5 am.`
          : duskShare > 0
          ? `${Math.round(duskShare * 100)}% of the drive is at dusk or dawn.`
          : 'The whole drive is in daylight.',
    },
    {
      key: 'driver',
      label: 'Driver',
      weight: 0.2,
      value: Math.round(d.value),
      detail: d.detail,
    },
    {
      key: 'weather',
      label: 'Weather',
      weight: 0.15,
      value: Math.round(weatherValue),
      detail: weatherValue >= 50 ? 'Heavy seasonal rain likely along this route.' : weatherValue >= 25 ? 'Some seasonal rain possible.' : 'No major seasonal weather risk.',
    },
    {
      key: 'fatigue',
      label: 'Drive length',
      weight: 0.1,
      value: Math.round(fatigueValue),
      detail: `${profile.km} km, about ${Math.floor(hrs)}h ${Math.round((hrs % 1) * 60)}m of driving.`,
    },
    {
      key: 'vehicle',
      label: 'Vehicle',
      weight: 0.1,
      value: Math.round(v.value),
      detail: v.detail,
    },
  ];

  const score = Math.round(components.reduce((sum, c) => sum + c.value * c.weight, 0));

  const tips = [];
  if (nightShare > 0.25) tips.push('Share the live trip with a trusted contact and agree on a lit mid-way stop.');
  if (weatherValue >= 50) tips.push('Rain is likely: allow extra time and ask the driver to keep to a safe speed.');
  if (fatigueValue >= 45) tips.push('Long drive: plan a break about every two hours.');
  if (components[0].value >= 60) tips.push('This corridor has a higher incident index. Keep check-ins switched on.');
  if (d.value >= 50) tips.push('Driver has thin verification history. A verified-ID, verified-licence driver lowers risk.');
  if (v.value >= 55) tips.push('Few safety features listed. Confirm seat belts work for every seat before you set off.');
  tips.push('Start the trip in My trips to get scheduled check-ins and one-tap SOS.');

  return { score, band: bandFor(score), components, tips, profile };
}
