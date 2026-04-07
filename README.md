<<<<<<< HEAD
# crime-hotspot-ai
=======
# Crime Hotspot AI (Flask + Leaflet)

Mobile-friendly website that:
- Detects crime hotspots from FIR-like data (DBSCAN clustering)
- Computes an explainable risk score using **time of day**, **day of week**, and **season**
- Uses **browser location** to show nearby risk zones + alerts
- Generates a simple “safe route” detour around high-risk zones
- Provides two sections: **Commuter** (simple + safe routes) and **Patrol** (more intel)

## Setup

From the project folder:

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Then open:
- `http://localhost:5000/` (home)
- `http://localhost:5000/commuter` (commuter mode)
- `http://localhost:5000/patrol` (patrol command center)

If port `5000` is busy, set a port:

```bash
set PORT=5050
python app.py
```

## Data

`fir_data.csv` is a dummy dataset. Columns:
- `latitude`, `longitude`
- `crime_type`
- `date` (YYYY-MM-DD)
- `time` (0–23 hour)
- `ipc` (section number; acts like NDPS/Arms are represented by `crime_type`)

## API (used by the website)

- `GET /api/risk?lat=...&lon=...&crime_type=all`
- `GET /api/route?start_lat=...&start_lon=...&end_lat=...&end_lon=...&crime_type=all`
- `GET /api/hotspots`
- `GET /api/stats`

## Notes

- Geolocation is requested by the browser; if denied, the app uses a fallback city center.
- The safe-route logic is intentionally simple and explainable; it can be upgraded later (A*/OSRM).

>>>>>>> 51a8dbe (Initial commit: crime hotspot web app)
