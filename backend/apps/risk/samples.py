"""Sample profiles for the Risk program calculator, copied from frontend src/data/rides.js.

All drivers here are fictional. They exist only so the calculator on /risk-program can show how
the driver and vehicle factors move the score; they are not users and cannot be booked.
"""

SAMPLE_DRIVERS = [
    {"id": "d1", "name": "Karthik Raman", "gender": "M", "rating": 4.9, "trips": 212, "verified_id": True, "verified_license": True, "since": 2021, "langs": ["Tamil", "English", "Hindi"], "bio": "Weekend rides home and back. Quiet driver, good playlists."},
    {"id": "d2", "name": "Meera Nair", "gender": "F", "rating": 4.8, "trips": 148, "verified_id": True, "verified_license": True, "since": 2022, "langs": ["Malayalam", "English", "Tamil"], "bio": "Commutes between Kochi and Coimbatore every week."},
    {"id": "d3", "name": "Arjun Reddy", "gender": "M", "rating": 4.6, "trips": 64, "verified_id": True, "verified_license": False, "since": 2023, "langs": ["Telugu", "English", "Hindi"], "bio": "Software engineer, drives a company-leased SUV."},
    {"id": "d4", "name": "Sana Sheikh", "gender": "F", "rating": 4.95, "trips": 301, "verified_id": True, "verified_license": True, "since": 2020, "langs": ["Hindi", "English", "Marathi"], "bio": "Mumbai to Pune regular. Women-only rides on request."},
    {"id": "d5", "name": "Vikram Patil", "gender": "M", "rating": 4.3, "trips": 22, "verified_id": False, "verified_license": True, "since": 2024, "langs": ["Marathi", "Hindi"], "bio": "New to VConnects, driving for a decade."},
    {"id": "d6", "name": "Lakshmi Iyer", "gender": "F", "rating": 4.85, "trips": 97, "verified_id": True, "verified_license": True, "since": 2022, "langs": ["Tamil", "English"], "bio": "Teacher. Never drives after dark."},
    {"id": "d7", "name": "Rohit Gowda", "gender": "M", "rating": 4.7, "trips": 120, "verified_id": True, "verified_license": True, "since": 2021, "langs": ["Kannada", "English", "Hindi"], "bio": "Bengaluru to Mysuru most Fridays."},
    {"id": "d8", "name": "Imran Qureshi", "gender": "M", "rating": None, "trips": 3, "verified_id": False, "verified_license": False, "since": 2026, "langs": ["Hindi", "Telugu"], "bio": "Just joined. Still collecting ratings."},
    {"id": "d9", "name": "Divya Krishnan", "gender": "F", "rating": 4.75, "trips": 56, "verified_id": True, "verified_license": True, "since": 2023, "langs": ["Tamil", "English"], "bio": "Chennai to Puducherry beach runs."},
    {"id": "d10", "name": "Suresh Babu", "gender": "M", "rating": 4.5, "trips": 180, "verified_id": True, "verified_license": True, "since": 2020, "langs": ["Tamil", "Telugu", "English"], "bio": "Long-haul regular, always on time."},
]

SAMPLE_VEHICLES = [
    {"model": "Maruti Suzuki Swift", "year": 2022, "features": ["airbags", "abs", "gps"]},
    {"model": "Hyundai Creta", "year": 2023, "features": ["airbags", "abs", "dashcam", "gps", "firstaid"]},
    {"model": "Toyota Innova Crysta", "year": 2019, "features": ["airbags", "abs", "firstaid"]},
    {"model": "Tata Nexon", "year": 2023, "features": ["airbags", "abs", "dashcam"]},
    {"model": "Honda City", "year": 2017, "features": ["airbags", "abs"]},
    {"model": "Maruti Suzuki Alto", "year": 2012, "features": []},
    {"model": "Kia Seltos", "year": 2022, "features": ["airbags", "abs", "dashcam", "firstaid"]},
]
