from __future__ import annotations

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import pandas as pd
from sklearn.cluster import DBSCAN
import numpy as np
from datetime import datetime, timezone
from math import cos, radians, sin, asin, sqrt
from pathlib import Path
import requests

app = Flask(__name__)
CORS(app)

DATA_PATH = Path(__file__).with_name("fir_data.csv")
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
NOMINATIM_UA = "crime-hotspot-ai/1.0 (demo; contact: local)"


def _load_fir() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    # Normalize/ensure types
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "time" in df.columns:
        df["time"] = pd.to_numeric(df["time"], errors="coerce")
    for col in ("latitude", "longitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).copy()
    return df


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Great-circle distance between two points on Earth
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _season_for_month(m: int) -> str:
    # Simple India-friendly season buckets (adjust anytime)
    if m in (12, 1, 2):
        return "winter"
    if m in (3, 4, 5):
        return "summer"
    if m in (6, 7, 8, 9):
        return "monsoon"
    return "post-monsoon"


def _time_bucket(hour: int) -> str:
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "afternoon"
    if 17 <= hour <= 20:
        return "evening"
    return "night"


def _risk_multiplier(time_bucket: str, day_of_week: int, season: str) -> float:
    # Manual logic (easy to explain + tweak)
    tb = {
        "morning": 0.95,
        "afternoon": 1.0,
        "evening": 1.15,
        "night": 1.30,
    }.get(time_bucket, 1.0)

    # Fri/Sat slightly higher
    dow = 1.10 if day_of_week in (4, 5) else 1.0

    # Monsoon / festival-ish months can be higher for some crimes; keep conservative
    seas = {
        "winter": 1.05,
        "summer": 1.0,
        "monsoon": 1.10,
        "post-monsoon": 1.03,
    }.get(season, 1.0)
    return tb * dow * seas


def _dbscan_hotspots(df: pd.DataFrame, eps_deg: float = 0.01, min_samples: int = 3) -> pd.DataFrame:
    coords = df[["latitude", "longitude"]].to_numpy()
    if len(coords) == 0:
        df = df.copy()
        df["cluster"] = np.array([], dtype=int)
        return df
    db = DBSCAN(eps=eps_deg, min_samples=min_samples).fit(coords)
    out = df.copy()
    out["cluster"] = db.labels_
    return out


def _cluster_centroids(df: pd.DataFrame) -> list[dict]:
    # Return centroids with density and top crime types
    hotspots = df[df["cluster"] != -1].copy()
    if hotspots.empty:
        return []

    rows: list[dict] = []
    for cluster_id, g in hotspots.groupby("cluster"):
        lat = float(g["latitude"].mean())
        lon = float(g["longitude"].mean())
        density = int(len(g))
        top_types = (
            g["crime_type"].value_counts().head(3).index.tolist()
            if "crime_type" in g.columns
            else []
        )
        rows.append(
            {
                "cluster": int(cluster_id),
                "latitude": lat,
                "longitude": lon,
                "density": density,
                "top_crime_types": top_types,
                # heuristic radius (km) based on density
                "radius_km": float(min(1.2, 0.35 + 0.08 * density)),
            }
        )
    return rows


def _compute_risk_zones(
    lat: float,
    lon: float,
    crime_type: str | None,
    when: datetime,
    df: pd.DataFrame,
) -> dict:
    hour = when.hour
    day_of_week = when.weekday()  # Mon=0
    season = _season_for_month(when.month)
    bucket = _time_bucket(hour)
    mult = _risk_multiplier(bucket, day_of_week, season)

    if crime_type and crime_type.lower() != "all" and "crime_type" in df.columns:
        df = df[df["crime_type"].str.lower() == crime_type.lower()].copy()

    clustered = _dbscan_hotspots(df)
    zones = _cluster_centroids(clustered)

    # Score nearby zones higher; keep in 0..100
    scored = []
    for z in zones:
        d = _haversine_km(lat, lon, z["latitude"], z["longitude"])
        proximity = max(0.0, 1.0 - (d / max(z["radius_km"], 0.1)))
        base = min(1.0, (z["density"] / 12.0))
        score01 = min(1.0, (0.15 + 0.85 * (0.55 * base + 0.45 * proximity)) * mult)
        score = int(round(score01 * 100))
        level = "low" if score < 35 else "medium" if score < 65 else "high"
        scored.append(
            {
                **z,
                "distance_km": float(round(d, 3)),
                "score": score,
                "level": level,
            }
        )

    # sort by score desc
    scored.sort(key=lambda x: (x["score"], x["density"]), reverse=True)
    return {
        "context": {
            "time_bucket": bucket,
            "day_of_week": day_of_week,
            "season": season,
            "multiplier": float(round(mult, 3)),
            "crime_type": crime_type or "all",
        },
        "zones": scored[:40],
    }


def _route_detour(start: tuple[float, float], end: tuple[float, float], zones: list[dict]) -> list[list[float]]:
    # Lightweight safe-route: if direct path is too close to any high zone, add one detour point.
    # This is intentionally simple and explainable; can be upgraded later to A* or OSRM.
    slat, slon = start
    elat, elon = end
    route: list[list[float]] = [[slat, slon]]

    # pick the most problematic zone near the segment (approx: near start-midpoint)
    mid = ((slat + elat) / 2.0, (slon + elon) / 2.0)
    candidates = [z for z in zones if z.get("level") == "high"]
    if candidates:
        candidates.sort(key=lambda z: _haversine_km(mid[0], mid[1], z["latitude"], z["longitude"]))
        z = candidates[0]
        # detour offset perpendicular-ish in lat/lon space
        detour_lat = z["latitude"] + 0.006
        detour_lon = z["longitude"] - 0.006
        route.append([detour_lat, detour_lon])

    route.append([elat, elon])
    return route

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/commuter")
def commuter():
    return render_template("commuter.html")


@app.route("/patrol")
def patrol():
    return render_template("patrol.html")


@app.route("/api/crimes")
def api_crimes():
    df = _load_fir()
    return jsonify(df.fillna("").to_dict(orient="records"))


@app.route("/api/hotspots")
def api_hotspots():
    df = _load_fir()
    clustered = _dbscan_hotspots(df)
    zones = _cluster_centroids(clustered)
    return jsonify(zones)


@app.route("/api/risk")
def api_risk():
    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
    except ValueError:
        return jsonify({"error": "lat/lon required"}), 400

    crime_type = request.args.get("crime_type")
    # Optional: allow client to pass local hour/day/season; by default use server now (UTC->local-ish)
    now = datetime.now(timezone.utc).astimezone()
    df = _load_fir()
    result = _compute_risk_zones(lat, lon, crime_type, now, df)
    return jsonify(result)


@app.route("/api/route")
def api_route():
    try:
        slat = float(request.args.get("start_lat", ""))
        slon = float(request.args.get("start_lon", ""))
        elat = float(request.args.get("end_lat", ""))
        elon = float(request.args.get("end_lon", ""))
    except ValueError:
        return jsonify({"error": "start_lat/start_lon/end_lat/end_lon required"}), 400

    crime_type = request.args.get("crime_type")
    now = datetime.now(timezone.utc).astimezone()
    df = _load_fir()
    risk = _compute_risk_zones(slat, slon, crime_type, now, df)
    route = _route_detour((slat, slon), (elat, elon), risk["zones"])
    return jsonify({"route": route, "risk_context": risk["context"]})


@app.route("/api/stats")
def api_stats():
    df = _load_fir()
    if df.empty:
        return jsonify({"by_hour": {}, "by_day": {}, "by_type": {}, "by_season": {}})

    df2 = df.copy()
    df2["hour"] = df2["time"].fillna(0).astype(int).clip(0, 23)
    df2["dow"] = df2["date"].dt.weekday.fillna(0).astype(int)
    df2["month"] = df2["date"].dt.month.fillna(1).astype(int)
    df2["season"] = df2["month"].apply(_season_for_month)

    by_hour = df2["hour"].value_counts().sort_index().to_dict()
    by_day = df2["dow"].value_counts().sort_index().to_dict()
    by_type = df2["crime_type"].value_counts().to_dict() if "crime_type" in df2.columns else {}
    by_season = df2["season"].value_counts().to_dict()

    return jsonify(
        {
            "by_hour": {str(k): int(v) for k, v in by_hour.items()},
            "by_day": {str(k): int(v) for k, v in by_day.items()},
            "by_type": {str(k): int(v) for k, v in by_type.items()},
            "by_season": {str(k): int(v) for k, v in by_season.items()},
        }
    )


@app.route("/api/geocode")
def api_geocode():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "q required"}), 400

    try:
        r = requests.get(
            f"{NOMINATIM_BASE}/search",
            params={"q": q, "format": "jsonv2", "limit": 5},
            headers={"User-Agent": NOMINATIM_UA},
            timeout=8,
        )
        r.raise_for_status()
        results = r.json()
        out = []
        for item in results:
            out.append(
                {
                    "display_name": item.get("display_name"),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "type": item.get("type"),
                }
            )
        return jsonify({"query": q, "results": out})
    except Exception as e:
        return jsonify({"error": "geocode_failed", "detail": str(e)}), 502


@app.route("/api/reverse")
def api_reverse():
    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
    except ValueError:
        return jsonify({"error": "lat/lon required"}), 400

    try:
        r = requests.get(
            f"{NOMINATIM_BASE}/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2"},
            headers={"User-Agent": NOMINATIM_UA},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        return jsonify(
            {
                "lat": lat,
                "lon": lon,
                "display_name": data.get("display_name"),
                "address": data.get("address"),
            }
        )
    except Exception as e:
        return jsonify({"error": "reverse_failed", "detail": str(e)}), 502


if __name__ == "__main__":
    # For local development. For production, run behind a WSGI server.
    import os

    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)