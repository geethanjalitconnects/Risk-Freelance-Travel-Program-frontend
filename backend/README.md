# VConnects Travel: backend

Django + Django REST Framework + PostgreSQL + JWT backend for the React frontend in
`../vconnects-travel`.

## Setup (Windows, Git Bash or PowerShell)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env          # then set DATABASE_URL, DJANGO_SECRET_KEY, ADMIN_URL
```

Create the database once (PostgreSQL 17 is on port 5432 on this machine):

```bash
"/c/Program Files/PostgreSQL/17/bin/createdb.exe" -U postgres -p 5432 vconnects
```

Then:

```bash
.venv/Scripts/python manage.py migrate                 # creates the "Verification reviewers" group too
.venv/Scripts/python manage.py seed_geo                # the 14 cities and their routes (reference data)
.venv/Scripts/python manage.py fetch_route_distances   # optional: real road distances (needs ORS_API_KEY)
.venv/Scripts/python manage.py seed_admin              # the first admin, from ADMIN_USERNAME / ADMIN_PASSWORD
.venv/Scripts/python manage.py runserver               # http://127.0.0.1:8000
```

The database starts empty: there is no sample data. `seed_geo` only loads the city list the
app needs to work.

- API: `http://127.0.0.1:8000/api/v1/`
- Interactive docs (Swagger): `http://127.0.0.1:8000/api/docs/`
- Admin: `http://127.0.0.1:8000/<ADMIN_URL>` (development default: `/vct-admin/`)

## Tests

```bash
.venv/Scripts/python manage.py test
```

The tests run on whatever `DATABASE_URL` points to. Pointing it at
`sqlite:///test.sqlite3` also works for a quick run without PostgreSQL.

### Risk-model parity

`apps/risk/scoring.py` is a port of the frontend's `src/lib/risk.js`, and it must return
identical output. `scripts/risk_parity/generate.mjs` runs the frontend code (reading it only)
and writes `apps/risk/tests/fixtures/js_parity.json`. The parity test compares the Python model
against it case by case. Re-run the generator if `risk.js` or `cities.js` changes:

```bash
node scripts/risk_parity/generate.mjs
```

## API conventions (chosen for compatibility with the React code)

- Response keys are camelCase (`seatsLeft`, `durationMin`). Request bodies may be camelCase.
- Ride fields `from` / `to` are city codes (`MAA`). Inputs also accept city names.
- Datetimes are sent and returned as `"YYYY-MM-DDTHH:mm"` in Asia/Kolkata time, the same strings
  the frontend builds. Dates are `"YYYY-MM-DD"`.
- Risk objects have the exact shape `RiskBreakdown` renders:
  `{score, band:{key,label,max}, components[], tips[], profile}`.
- Auth: `Authorization: Bearer <access token>` (simplejwt).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/health` | - | Liveness check |
| POST | `/api/v1/auth/otp/send` | - | `{phone}`: text a 6-digit code (printed to the console when DEBUG is on) |
| POST | `/api/v1/auth/otp/verify` | - | `{phone, code}`: returns `{access, refresh, isNewUser, user}`; creates the account on first sign-in |
| POST | `/api/v1/auth/refresh` | - | `{refresh}`: returns new access and refresh tokens |
| POST | `/api/v1/auth/logout` | - | `{refresh}`: revoke the refresh token |
| GET / PATCH | `/api/v1/me` | yes | Profile: `name, gender, bio, langs`; includes `driverVerification` status |
| GET / POST | `/api/v1/me/contacts` | yes | Trusted contacts (max 5) |
| DELETE | `/api/v1/me/contacts/<id>` | yes | Remove a contact |
| GET / POST | `/api/v1/me/driver-verification` | yes | Driver verification status / submit documents (multipart) |
| GET | `/api/v1/cities` | - | Cities with meeting points |
| GET | `/api/v1/cities/<code>` | - | One city |
| GET | `/api/v1/fares/quote` | - | `from, to`: `{km, minFare, maxFare, ratePerKm, maxIncreasePercent}` |
| GET | `/api/v1/risk/config` | - | Risk bands and vehicle feature labels |
| GET | `/api/v1/risk/samples` | - | Sample drivers/vehicles for the calculator |
| POST | `/api/v1/risk/score` | - | Calculator: `{from, to, depart, sampleDriver?, sampleVehicle?}` |
| POST | `/api/v1/risk/preview` | optional | Publish preview: `{from, to, depart, vehicle?}`, returns `{km, durationMin, minFare, maxFare, risk}` |
| GET | `/api/v1/rides/search` | optional | `from, to, date, seats, sort, womenOnly, travelWith, daytime, maxRisk`. Only approved drivers' rides |
| POST | `/api/v1/rides` | approved driver | Publish a ride (403 with a `verification_*` code otherwise) |
| GET | `/api/v1/rides/mine` | yes | Rides I published, with `listed` (false while not approved) |
| GET | `/api/v1/rides/<id>` | optional | Ride detail, with `isOwn`, `myBookingId`, `canBook`, `cannotBookCode/Reason`, `hasBookings` |
| PATCH | `/api/v1/rides/<id>` | approved driver | Edit a ride |
| DELETE | `/api/v1/rides/<id>` | driver | Remove a ride (409 if it has bookings) |
| GET / POST | `/api/v1/bookings` | yes | My bookings (live first) / book: `{rideId, seats}` |
| GET | `/api/v1/bookings/<id>` | yes | One booking with trip state and trip log |
| POST | `/api/v1/bookings/<id>/cancel` | yes | Cancel before the trip starts |
| POST | `/api/v1/bookings/<id>/start` | yes | Start the protected trip |
| POST | `/api/v1/bookings/<id>/checkins` | yes | `{key}`: `pickup`, `mid`, `near`, in order |
| POST | `/api/v1/bookings/<id>/missed` | yes | Simulate a missed check-in. **Only when DEBUG is on**, 404 otherwise |
| POST | `/api/v1/bookings/<id>/share` | yes | Create the live-trip link and text it to trusted contacts |
| POST | `/api/v1/bookings/<id>/sos` | yes | Raise SOS: logged and texted to trusted contacts |
| POST | `/api/v1/bookings/<id>/complete` | yes | "I've arrived" |
| POST | `/api/v1/bookings/<id>/rate` | yes | `{stars}` 1-5, once, after completion |
| POST | `/api/v1/me/driver-verification/documents/<kind>` | yes | Upload one new or replacement document (`file`) |

### Admin dashboard API (`/api/admin/`, admin token only)

| Method | Path | Purpose |
|---|---|---|
| POST | `login` | `{username, password}` → `{token, expiresAt, admin}`. Rate-limited, and axes locks out repeated failures |
| POST | `logout` / `password` | End all sessions / `{currentPassword, newPassword}` (required at first sign-in) |
| GET | `me`, `queue?status=&q=&page=` | The signed-in admin; the review queue with counts |
| GET | `review/<userId>` | Submission, documents with review status, history, emails |
| GET | `documents/<docId>/file` | The decrypted document (logged, never cached) |
| POST | `review/<userId>/documents/<docId>/approve` / `reject` | Per-document decision (`reject` needs `{reason}`) |
| POST | `review/<userId>/approve` / `reject` / `request-resubmit` / `revoke` | Profile decisions |
| POST | `emails/<id>/retry` | Send a failed email again |
| GET | `audit?action=&user=&page=` | Audit log (role `admin` only) |

Booking objects match the frontend's `bookRide()` shape: `rideId, ride, riskScore, riskBand,
seats, total, createdAt, status, trip{startedAt, checkins, missed, shared, sos}, events[{t, type,
text}], rating, completedAt`. Timestamps are epoch milliseconds. Refusals return
`{detail, code}` with 409, where `code` is one of `own_ride, departed, already_booked, full,
seats, travel_with, unavailable, invalid_state, out_of_order, already_checked_in, already_rated`.

Trusted contacts are texted through the same `SMS_BACKEND` as sign-in codes (printed to the
console in DEBUG), after the database commit. A failed SMS never undoes the SOS. Contacts whose
number can't be put in international format are skipped.

## Driver verification

A user can publish or edit rides only when their verification is **approved** by an admin.

- **Submission** (`POST /me/driver-verification`, multipart): `vehicleNumber`, `idType`
  (`aadhaar`, `pan`, `voter_id`, `passport`), `licenceFront`, `licenceBack`, `idFront`, optional
  `idBack`, and `aadhaarMasked=true` for Aadhaar. JPG, PNG or PDF up to 5 MB each. The type is
  checked from the file contents, not its name.
- **Statuses:** `not_submitted`, `pending`, `approved`, `rejected` (with reason),
  `resubmit_requested` (with reason), `revoked` (with reason). Every change is kept in the status
  history and the admin audit log.
- **Review:** each document is approved or rejected (a reason is required) on its own. The profile
  can be approved only once every document is approved. With a rejected document, the reviewer
  asks the driver to re-upload (`resubmit_requested`). Once every rejected document is replaced,
  the submission goes back to `pending`.
- **Re-uploads:** an approved driver who uploads a new or replacement document goes back to
  `pending` and can't publish or edit rides until re-approved. Rejected and revoked users submit
  everything again.
- **Emails:** approved, rejected and re-upload requested each send one email (templates in
  `apps/verification/templates/emails/verification/`). It goes to the email the driver gives
  when submitting, and is sent after the decision is saved. A failed email never undoes the
  decision. It shows as "Email failed" in the dashboard, with a Retry button, and
  `manage.py retry_failed_emails` (schedule it every 5 minutes) retries it with backoff.
- **Visibility:** rides of drivers who aren't approved (pending, rejected, revoked, deactivated)
  are hidden from search. Rides that already have bookings stay visible to those passengers. The
  **Verified** badge (`driver.verified`) appears only while approved. The vehicle number is shown
  only to the driver and to passengers with a booking.
- **Aadhaar:** only the official masked copy is accepted. The driver declares it is masked, and
  the reviewer must confirm masking before approving. Rejecting an unmasked copy deletes the ID
  documents at once. No OCR is used, and the full Aadhaar number is never handled.

### Document security

- **Encryption at rest:** documents are encrypted with Fernet (AES + HMAC) using
  `DOCUMENT_ENCRYPTION_KEYS`. Generate a key with `manage.py generate_document_key`.
  - To rotate, put a new key first and keep the old ones until old files are replaced.
  - **Losing all keys makes the documents unreadable.**
- **Storage:** encrypted files are kept in `PRIVATE_MEDIA_ROOT` under random names, with no user
  id, document type or original file name in the name. This folder is never served.
- **Admin access only:** documents can be opened only through an admin view that checks the
  `view_documents` permission and decrypts on demand. Its responses are never cached.
- **Audit:** every opening is logged (who, which document, when, IP) in the *Document access
  log*, which superusers can view.
- **Not exposed:** documents never appear in API responses, list views or logs, and ID numbers
  are never collected.
- **Retention:** run `manage.py purge_verification_documents` daily. It deletes the documents of
  rejected or revoked submissions, and of deactivated accounts, after `DOCUMENT_RETENTION_DAYS`
  (30). Approved documents are kept while the account is active.

## Fares

- **Settings:** one record, edited in the admin under *Fare settings*:
  - rate per km (Rs 15)
  - minimum fare floor (Rs 50)
  - rounding step (Rs 10)
  - maximum increase (50%)
- **Range per seat:** the minimum is `rate × km`, rounded up to the step and never below the
  floor. The maximum is `minimum × 1.5`, rounded down, and never below the minimum.
- **Enforcement:** the range is checked when a ride is published, and when an edit changes the
  fare or the route. Existing rides keep their fare until they are edited. Once a ride has
  bookings its fare is locked.

## Road distances (OpenRouteService)

- **Source:** distances come from `RouteProfile.km`. `fetch_route_distances` fills them once from
  the OpenRouteService distance matrix, with one request for all 91 city pairs, inside the free
  plan.
- **Setup:** set `ORS_API_KEY` from a free account at openrouteservice.org. The app never calls
  ORS while serving requests.
- **Fallback:** if the key is missing or the API fails, the existing estimates (straight line ×
  1.28) are kept.
- **Manual edits:** a distance typed in by an admin is marked *manual* and kept on later fetches.
- **Credit:** route data © OpenStreetMap contributors.

## Admin dashboard (React app)

At `/#/admin/login` in the React app: lazy-loaded, never linked from the user UI. Routes are
`/admin/queue`, `/admin/review/:userId` (where every review decision happens) and `/admin/audit`.

- **First admin:** `manage.py seed_admin` reads `ADMIN_USERNAME` / `ADMIN_PASSWORD` and hashes the
  password with Argon2. Running it again does nothing if the admin exists. The admin must change
  the password at first sign-in, in the dashboard and in the Django admin.
- **Separate auth:** admin tokens are signed with `ADMIN_JWT_SECRET` (with their own audience and
  type) and kept in sessionStorage under their own key. User tokens get 401 on `/api/admin/*`, and
  admin tokens get 401 on `/api/v1/*`. Signing out or changing the password ends every session.
- **Roles:** `admin` (superuser) or `reviewer` (staff in *Verification reviewers*). Only admins
  see the audit log.

## Django admin

At `/<ADMIN_URL>`. Only staff can log in, with a phone number or the seeded username. Driver
verifications are read-only here, with a link to the dashboard's review page.

| Screen | What it does |
|---|---|
| **Driver verifications** | Read-only. Filter by status, search by phone, name or vehicle number. The detail page shows status history and documents (each opening logged), with a link to review in the dashboard. |
| Document access log | Read-only audit of document openings (superusers) |
| Fare settings | The single fare record |
| Users | Search by phone, filter by gender and verification status, deactivate or reactivate. Deactivating blocks sign-in, revokes tokens, hides the user's unbooked rides and cancels their upcoming bookings. |
| Rides | Read-only. Filter by status, date and who can travel. *Cancel selected rides* cancels their bookings and writes to each passenger's trip log. |
| Bookings | Read-only, with check-ins and trip log |
| Cities, routes | Reference data and route distances |
| Axes | Failed admin logins and lockouts (superusers can unlock) |

**Access control:**
- Add a staff user (`is_staff`) to the **Verification reviewers** group, which is created by a
  migration. Reviewers see the verification screens only, with permission to review and open
  documents. They get no access to users, rides, bookings or fares.
- Superusers can do everything.

**Notifications:** when an admin cancels a ride, a line is always written to each passenger's
trip log. SMS can be plugged in later by adding a notifier to `RIDE_CANCELLED_NOTIFIERS` (a
ready-made `apps.bookings.notifications.sms_ride_cancelled` exists), once the SMS provider and
templates are approved.

## Security

**Already in place:**
- **Login lockout:** [django-axes](https://django-axes.readthedocs.io/) locks a username + IP
  after `AXES_FAILURE_LIMIT` (5) failed admin logins, for `AXES_COOLOFF_MINUTES` (30). Unlock
  early under *Axes* in the admin or with `manage.py axes_reset`.
- **Admin location:** the admin is on a path from `ADMIN_URL`, and `prod.py` refuses the default.
- **Passwords and sessions:** staff passwords must be 12+ characters and not common. Admin
  sessions last 8 hours and end when the browser closes.
- **Production settings** (`prod.py`):
  - HTTPS redirect, HSTS (1 year) and secure cookies
  - `X-Frame-Options: DENY`, `nosniff` and a referrer policy
  - startup refuses a missing secret key, SMS backend or encryption key
- **Deactivated accounts:** their login tokens are rejected (`CHECK_USER_IS_ACTIVE`).
- **Uploads:** files are kept in memory only, so no unencrypted temporary files are written to
  disk.
- **Secrets never shown:** OTP codes exist only as keyed hashes and are never shown. Share
  tokens and documents never appear in list views.

**Recommended before going live:**
1. **Two-factor sign-in for staff:** add `django-otp` with TOTP authenticator apps and require
   it for every admin.
2. **Network restriction:** put the admin behind a VPN or an IP allowlist, ideally on a separate
   subdomain (for example `admin.vconnects.in`) that only serves the admin.
3. **Reverse proxy:** behind a proxy, set `AXES_IPWARE_PROXY_COUNT` so lockouts use the real
   client IP, and set `CSRF_TRUSTED_ORIGINS`.
4. **Private document storage:** use a private object-storage bucket (S3 or similar, no public
   access, server-side encryption) instead of local disk, and back it up together with the
   encryption keys.
5. **Key management:** keep `DOCUMENT_ENCRYPTION_KEYS` and `DJANGO_SECRET_KEY` in a secrets
   manager, never in the repository. Write down a key-rotation procedure.
6. **Monitoring:** alert on lockouts, on unusual document access (for example many documents
   opened by one reviewer in a short time) and on admin logins from new IPs. Review the document
   access log regularly.
7. **Least privilege:** give most staff the reviewer group only, keep superusers few, and review
   group membership regularly.
8. **Scheduling:** run `purge_verification_documents` daily, and keep the
   `axes_reset_failure_logs` / `clearsessions` housekeeping on a schedule.

## Layout

```
config/            settings (base/dev/prod), urls, admin title
common/            JS-compatible maths helpers, health view, admin login tests
apps/accounts/     User, OTP sign-in (otp.py, sms.py), /me, trusted contacts, deactivate (services.py)
apps/verification/ driver verification: models, encrypted storage (crypto.py, storage.py),
                   rules (services.py), API, admin review screens, retention command
apps/fares/        fare settings (single record), fare range rules, /fares/quote
apps/geo/          City, MeetingPoint, RouteProfile, seed_geo, fetch_route_distances (ORS)
apps/risk/         scoring.py (port of risk.js), sample profiles, /risk endpoints
apps/rides/        Ride, publish/edit/remove/search, booking eligibility and gender-lock rules
apps/bookings/     Booking, CheckIn, TripEvent; booking + trip lifecycle, alerts, notifications
apps/adminpanel/   admin dashboard API: admin tokens, roles, audit log, seed_admin
scripts/           risk parity fixture generator
```
