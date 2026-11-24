# VConnects: carpooling with a travel risk program

One Vite + React frontend that combines:

- the existing app and its **Django API integration** (`src/lib/api.js`, `auth.js`, `ridesApi.js`, `verificationApi.js`),
- the **3D car** home page (`DrivingCar.jsx`, `lib/carScene.js`, `lib/carMotion.js`, `public/models/car.glb`),
- new pages: About, How it works, Safety centre, Help & FAQ, Contact, Terms, Privacy and a signed-in Dashboard.

## Run it

```bash
npm install
cp .env.example .env     # set VITE_API_URL to your Django API
npm run dev              # http://localhost:5173
npm run build            # production build in dist/
```

Node 18+. The Django API must be running (default `http://127.0.0.1:8000/api/v1`) and must allow this
origin in its CORS settings. Search, rides, bookings, sign-in (OTP), profile and verification all go through it.

## Routes (hash router)

`/` Home (3D car) · `/search` · `/ride/:id` · `/publish` · `/edit/:id` · `/trips` · `/risk-program` ·
`/profile` · `/login` · `/verification` · `/dashboard` · `/how-it-works` · `/safety` · `/about` ·
`/help` · `/contact` · `/terms` · `/privacy`

## Notes

- The Contact page has no API endpoint, so it opens a mail draft to `VITE_SUPPORT_EMAIL`. Add an endpoint and
  post to it from `src/pages/Contact.jsx` when ready.
- Terms and Privacy are starter text. Have them reviewed before launch.
- The car model is the three.js Ferrari 458 demo glTF by vicent091 (MIT, keep attribution). To use another model see
  `src/lib/carScene.js` (wheel nodes `wheel_fl/fr/rl/rr`).
- The home page still shows a still photo if WebGL is unavailable.
