# Location search (Google Places): setup, test plan, edge cases and cost

From/To fields on Search and Publish use Google Places through our backend. The key never reaches
the browser. Code: `apps/places/` (backend), `src/components/LocationAutocomplete.jsx` (frontend).

## Setup

| Step | Where |
|---|---|
| Enable **Places API (New)** and **Geocoding API** for the key's project | Google Cloud Console → APIs & Services → Library |
| Key restrictions: *Application* = none or your server's IP (not "HTTP referrers"); *API* = Places API (New) + Geocoding API | Credentials → the key |
| Set a **budget alert** and per-API **quotas** (see Cost) | Billing → Budgets; APIs → Quotas |
| `GOOGLE_MAPS_API_KEY=...` and `PLACES_ENABLED=True` | `backend/.env` |
| `python manage.py migrate`, restart the backend | `backend/` with `.venv313` active |
| Schedule `python manage.py refresh_place_cache` **daily** | cron / Task Scheduler (keeps Google coordinates under 30 days) |
| Check the key: `python manage.py places_probe Tambaram --details` (1 billed call) | prints suggestions + area, never the key |

Settings (all optional): `PLACES_PRIMARY_TYPES` (default `(regions)`), `PLACES_CACHE_SECONDS` (600),
`PLACES_SEARCH_RADIUS_KM` (25), `PLACES_COORDINATE_DAYS` (29, capped at 29),
`THROTTLE_PLACES_AUTOCOMPLETE` (60/min), `THROTTLE_PLACES_DETAILS` (20/min), `THROTTLE_PLACES_REVERSE` (10/min).

## How a search is billed

| User action | Google calls | Notes |
|---|---|---|
| Typing in one field | 1 Autocomplete per pause (≥3 letters, 400 ms debounce) | Same text within 10 min: answered from cache, free |
| Picking a suggestion | 1 Place Details (Essentials: `id,addressComponents,location`) | Closes the session: autocomplete requests 13+ in that session are free |
| Picking a **recent place** or a **Popular** chip | none | Server uses its cached place (≤29 days); refreshes once if expired |
| "Use my current location" | 1 Geocoding (reverse) | No Place Details needed |
| Publishing / searching with picked places | none | Coordinates come from the cache |
| Daily `refresh_place_cache` | 1 Place Details per place of an upcoming ride older than 26 days | Usually a handful a day |

Watch real numbers in **Django admin → Places → Places usage** (per day: `autocomplete`,
`autocomplete_cached`, `details`, `details_cached`, `reverse`, `error`).

## Cost estimate (Google India price list, checked Nov 2026; re-check before launch)

| SKU (India) | Free / month | Then per 1,000 |
|---|---|---|
| Autocomplete Requests | 70,000 | $0.85 |
| Autocomplete Session Usage | unlimited | $0 |
| Place Details Essentials | 70,000 | $1.50 |
| Geocoding | 70,000 | $1.50 |

Assumptions per search: 2 fields × ~4 autocomplete requests + 2 details; 30% of picks come from
recent places / Popular chips (no calls); 10% of searches use current location (1 geocode
instead of typing the From field).

| Searches / month | Autocomplete | Details | Geocoding | Estimated cost |
|---|---|---|---|---|
| 5,000 | ~26,000 | ~6,500 | ~500 | **$0** |
| 20,000 | ~105,000 | ~26,000 | ~2,000 | **≈ $30** (35k autocomplete over the free cap) |
| 50,000 | ~260,000 | ~65,000 | ~5,000 | **≈ $160** (190k autocomplete over the free cap) |

Suggested guard rails: a Google Cloud budget alert at ₹3,000/month, and a quota on
"Autocomplete requests per day" (e.g. 10,000) so a bug or abuse can't run up a bill.
`PLACES_ENABLED=False` switches the feature off instantly (fields then show "Location search is
unavailable"; there is no city-list fallback any more).

## Manual test checklist

Run with the backend and frontend up, `PLACES_ENABLED=True`, DevTools → Network open.

**Search page / Home**
1. Type `ta`: "Type at least 3 letters", no network call. Type `tam`: one call after a short pause.
2. Type `tambaram` quickly: earlier calls show *cancelled*; one call after you stop typing.
3. Suggestions show a main line (e.g. *Tambaram*) and a secondary line (district, state), with "Google Maps" at the bottom.
4. Keyboard only: Tab into the field, ↓/↑ moves, Enter picks (does not submit), Esc closes.
5. Pick a place: one `/places/details` call; the hint under the field shows "District, State".
6. Type text without picking, click away: "Please pick a place from the suggestions." Search refuses.
7. Same place in both fields: "must be different places".
8. Swap button swaps both picks.
9. Search a route with a ride ~5–20 km away: the ride shows with "N km from your place". ~40 km away: not shown.
10. Clear a field and focus it: "Use my current location" (From field) and your recent places; picking a recent place makes **no** `/places/details` call. "Clear recent" empties the list.
11. "Use my current location": allow → field fills with your area. Deny → "Location permission was denied…".
12. Home "Popular" chips appear once rides are published, and open the search.

**Publish**
13. Pick From/To: the pickup dropdown's first option is the picked place; the area's meeting points (added in admin → Geo → Areas) follow. Fare range and risk preview appear.
14. Same area both ends (e.g. two places in the same taluk): "Pick a destination in a different area".
15. Edit a published ride without changing places: places are kept; change only the note → saves.
16. Edit and change the destination: new fare range applies; dropoff resets to the new place.

**Admin**
17. Geo → Areas lists the areas created by picks; add a meeting point, it appears in Publish.
18. Places → Places usage counts rise as you test; Cached places shows `fetched_at`.

## Edge cases (what the user sees)

| Situation | Behaviour | Covered by automated test |
|---|---|---|
| Slow network | Spinner; older requests cancelled; only the latest answer shown | abort logic (manual check 2) |
| No results | "No places found. Try a nearby town or area." | manual |
| Google down / timeout (5 s) | "Location search is unavailable right now. Please try again in a moment." | yes |
| Key missing or `PLACES_ENABLED=False` | same message, no Google call | yes |
| Key wrong / API not enabled (403) | same message; `error` counter rises; key never logged | yes |
| Quota exceeded (429 / OVER_QUERY_LIMIT) | same message | yes |
| Too many requests from one user | HTTP 429 from our throttle | yes |
| Place outside India | "Only places in India are supported." | yes |
| Place without state / location | "We couldn't recognise that place…" | yes |
| Picked place ID no longer valid (404) | "That place couldn't be found. Please search again." | yes |
| Cached coordinates older than 29 days | re-fetched on next use; deleted by the daily job | yes |
| Location permission denied / unavailable | message, user types instead | manual |
| Geolocation on plain `http://` (not localhost) | browser blocks it; option fails with a message | manual (works on HTTPS) |
| Same taluk name in two states | two separate areas | yes |

## Open items

- **Legal counsel**: storing the picked place name as the ride's pickup text; storing taluk / district /
  state names taken from Google's address data; the 10-minute autocomplete cache; distance (km)
  computed from Google coordinates. Details in the Phase 0 / Phase 3 reports.
- **Taluk detection** depends on what Google returns for Indian places: run `places_probe` on a few
  real places (Tambaram, Madurantakam, Avadi, a village) and check the "area" line.
- **Production cache**: the default per-process memory cache is fine for development; use Redis or the
  database cache in production so autocomplete caching and throttles are shared across workers.
- The Risk program demo page still uses its own 14 sample cities (static demo, not booking).
