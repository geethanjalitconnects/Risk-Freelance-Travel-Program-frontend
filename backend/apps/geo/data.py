"""Sample areas for tests only (apps.geo.testing), copied from frontend src/data/cities.js.

"coast" drives the seasonal weather model: east = north-east monsoon (Oct-Dec),
west = south-west monsoon (Jun-Sep), inland = milder.
"""

CITIES = [
    {"code": "MAA", "name": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lng": 80.2707, "coast": "east"},
    {"code": "PNY", "name": "Puducherry", "state": "Puducherry", "lat": 11.9416, "lng": 79.8083, "coast": "east"},
    {"code": "VLR", "name": "Vellore", "state": "Tamil Nadu", "lat": 12.9165, "lng": 79.1325, "coast": "east"},
    {"code": "SLM", "name": "Salem", "state": "Tamil Nadu", "lat": 11.6643, "lng": 78.146, "coast": "east"},
    {"code": "TRZ", "name": "Tiruchirappalli", "state": "Tamil Nadu", "lat": 10.7905, "lng": 78.7047, "coast": "east"},
    {"code": "IXM", "name": "Madurai", "state": "Tamil Nadu", "lat": 9.9252, "lng": 78.1198, "coast": "east"},
    {"code": "CBE", "name": "Coimbatore", "state": "Tamil Nadu", "lat": 11.0168, "lng": 76.9558, "coast": "east"},
    {"code": "TIR", "name": "Tirupati", "state": "Andhra Pradesh", "lat": 13.6288, "lng": 79.4192, "coast": "east"},
    {"code": "BLR", "name": "Bengaluru", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946, "coast": "inland"},
    {"code": "MYS", "name": "Mysuru", "state": "Karnataka", "lat": 12.2958, "lng": 76.6394, "coast": "inland"},
    {"code": "HYD", "name": "Hyderabad", "state": "Telangana", "lat": 17.385, "lng": 78.4867, "coast": "inland"},
    {"code": "COK", "name": "Kochi", "state": "Kerala", "lat": 9.9312, "lng": 76.2673, "coast": "west"},
    {"code": "PNQ", "name": "Pune", "state": "Maharashtra", "lat": 18.5204, "lng": 73.8567, "coast": "west"},
    {"code": "BOM", "name": "Mumbai", "state": "Maharashtra", "lat": 19.076, "lng": 72.8777, "coast": "west"},
]

# Same three points, same order, as meetingPoints() in cities.js. The first is the default.
MEETING_POINT_SUFFIXES = ["Central Bus Stand", "Railway Station", "Airport Road Junction"]
