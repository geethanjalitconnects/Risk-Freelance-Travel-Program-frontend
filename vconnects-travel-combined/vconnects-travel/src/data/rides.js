import { CITIES, cityByCode, cityByName, meetingPoints, roadKm } from './cities.js';
import { hashString, mulberry32 } from '../lib/seed.js';
import { addMinutes, toIsoLocal } from '../lib/format.js';
import { scoreTrip } from '../lib/risk.js';

// All drivers below are fictional.
export const DRIVERS = [
  { id: 'd1', name: 'Karthik Raman', gender: 'M', rating: 4.9, trips: 212, verifiedId: true, verifiedLicense: true, since: 2021, langs: ['Tamil', 'English', 'Hindi'], bio: 'Weekend rides home and back. Quiet driver, good playlists.' },
  { id: 'd2', name: 'Meera Nair', gender: 'F', rating: 4.8, trips: 148, verifiedId: true, verifiedLicense: true, since: 2022, langs: ['Malayalam', 'English', 'Tamil'], bio: 'Commutes between Kochi and Coimbatore every week.' },
  { id: 'd3', name: 'Arjun Reddy', gender: 'M', rating: 4.6, trips: 64, verifiedId: true, verifiedLicense: false, since: 2023, langs: ['Telugu', 'English', 'Hindi'], bio: 'Software engineer, drives a company-leased SUV.' },
  { id: 'd4', name: 'Sana Sheikh', gender: 'F', rating: 4.95, trips: 301, verifiedId: true, verifiedLicense: true, since: 2020, langs: ['Hindi', 'English', 'Marathi'], bio: 'Mumbai to Pune regular. Women-only rides on request.' },
  { id: 'd5', name: 'Vikram Patil', gender: 'M', rating: 4.3, trips: 22, verifiedId: false, verifiedLicense: true, since: 2024, langs: ['Marathi', 'Hindi'], bio: 'New to VConnects, driving for a decade.' },
  { id: 'd6', name: 'Lakshmi Iyer', gender: 'F', rating: 4.85, trips: 97, verifiedId: true, verifiedLicense: true, since: 2022, langs: ['Tamil', 'English'], bio: 'Teacher. Never drives after dark.' },
  { id: 'd7', name: 'Rohit Gowda', gender: 'M', rating: 4.7, trips: 120, verifiedId: true, verifiedLicense: true, since: 2021, langs: ['Kannada', 'English', 'Hindi'], bio: 'Bengaluru to Mysuru most Fridays.' },
  { id: 'd8', name: 'Imran Qureshi', gender: 'M', rating: null, trips: 3, verifiedId: false, verifiedLicense: false, since: 2026, langs: ['Hindi', 'Telugu'], bio: 'Just joined. Still collecting ratings.' },
  { id: 'd9', name: 'Divya Krishnan', gender: 'F', rating: 4.75, trips: 56, verifiedId: true, verifiedLicense: true, since: 2023, langs: ['Tamil', 'English'], bio: 'Chennai to Puducherry beach runs.' },
  { id: 'd10', name: 'Suresh Babu', gender: 'M', rating: 4.5, trips: 180, verifiedId: true, verifiedLicense: true, since: 2020, langs: ['Tamil', 'Telugu', 'English'], bio: 'Long-haul regular, always on time.' },
];

export const VEHICLES = [
  { model: 'Maruti Suzuki Swift', year: 2022, features: ['airbags', 'abs', 'gps'] },
  { model: 'Hyundai Creta', year: 2023, features: ['airbags', 'abs', 'dashcam', 'gps', 'firstaid'] },
  { model: 'Toyota Innova Crysta', year: 2019, features: ['airbags', 'abs', 'firstaid'] },
  { model: 'Tata Nexon', year: 2023, features: ['airbags', 'abs', 'dashcam'] },
  { model: 'Honda City', year: 2017, features: ['airbags', 'abs'] },
  { model: 'Maruti Suzuki Alto', year: 2012, features: [] },
  { model: 'Kia Seltos', year: 2022, features: ['airbags', 'abs', 'dashcam', 'firstaid'] },
];

const DEPARTURE_HOURS = [5, 6, 7, 9, 11, 13, 15, 17, 19, 21, 22, 23];
const MINUTES = [0, 15, 30, 45];

export function generateRides(fromCity, toCity, date) {
  const rng = mulberry32(hashString(`${fromCity.code}-${toCity.code}-${date}`));
  const km = roadKm(fromCity, toCity);
  const durationMin = Math.max(30, Math.round(((km / 58) * 60) / 5) * 5);
  const count = 3 + Math.floor(rng() * 4);

  const hours = [...DEPARTURE_HOURS];
  for (let i = hours.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [hours[i], hours[j]] = [hours[j], hours[i]];
  }
  const picked = hours.slice(0, count).sort((a, b) => a - b);

  return picked.map((hour, i) => {
    const minute = MINUTES[Math.floor(rng() * MINUTES.length)];
    const depart = `${date}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    const driver = DRIVERS[Math.floor(rng() * DRIVERS.length)];
    const vehicle = VEHICLES[Math.floor(rng() * VEHICLES.length)];
    const seatsTotal = 3 + Math.floor(rng() * 2);
    const seatsLeft = 1 + Math.floor(rng() * seatsTotal);
    const price = Math.max(80, Math.round((km * (2.4 + rng() * 0.9)) / 10) * 10);
    const fromPoints = meetingPoints(fromCity);
    const toPoints = meetingPoints(toCity);
    return {
      id: `${fromCity.code}~${toCity.code}~${date}~${i}`,
      source: 'generated',
      from: fromCity.code,
      to: toCity.code,
      date,
      depart,
      durationMin,
      arrive: addMinutes(depart, durationMin),
      km,
      price,
      seatsTotal,
      seatsLeft,
      driver,
      vehicle,
      pickup: fromPoints[Math.floor(rng() * fromPoints.length)],
      dropoff: toPoints[Math.floor(rng() * toPoints.length)],
      womenOnly: driver.gender === 'F' && rng() > 0.55,
      ac: rng() > 0.15,
      bags: ['Backpack only', 'One cabin bag', 'One large bag'][Math.floor(rng() * 3)],
      notes: ['', 'One tea stop on the way.', 'Please be at the pickup 10 minutes early.', 'Music is low-volume, conversation welcome.'][Math.floor(rng() * 4)],
    };
  });
}

const seatsBooked = (rideId, bookings) =>
  bookings
    .filter((b) => b.rideId === rideId && b.status !== 'cancelled')
    .reduce((sum, b) => sum + b.seats, 0);

export function enrichRide(ride, bookings = []) {
  const left = Math.max(0, ride.seatsLeft - seatsBooked(ride.id, bookings));
  const risk = scoreTrip({
    fromCode: ride.from,
    toCode: ride.to,
    depart: ride.depart,
    driver: ride.driver,
    vehicle: ride.vehicle,
  });
  return { ...ride, seatsLeft: left, risk };
}

export function searchRides({ from, to, date, seats = 1 }, published = [], bookings = []) {
  const f = cityByName(from);
  const t = cityByName(to);
  if (!f || !t || f.code === t.code || !date) return [];
  const cutoff = toIsoLocal(new Date(Date.now() + 30 * 60000));
  const all = [
    ...generateRides(f, t, date),
    ...published.filter((r) => r.from === f.code && r.to === t.code && r.date === date),
  ];
  return all
    .filter((r) => r.depart > cutoff)
    .map((r) => enrichRide(r, bookings))
    .filter((r) => r.seatsLeft >= seats)
    .sort((a, b) => a.depart.localeCompare(b.depart));
}

export function getRide(id, published = [], bookings = []) {
  if (!id) return null;
  if (id.startsWith('pub-')) {
    const r = published.find((p) => p.id === id);
    return r ? enrichRide(r, bookings) : null;
  }
  const [fromCode, toCode, date, idx] = id.split('~');
  const f = cityByCode(fromCode);
  const t = cityByCode(toCode);
  if (!f || !t || !date) return null;
  const ride = generateRides(f, t, date)[Number(idx)];
  return ride ? enrichRide(ride, bookings) : null;
}

