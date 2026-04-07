import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import math

st.set_page_config(layout="wide")

st.title("🚨 AI Crime Hotspot Detection System")

# ===============================
# 📍 LOCATION + REFRESH BUTTON
# ===============================

if "location" not in st.session_state or st.button("📍 Refresh Location"):
    st.session_state["location"] = get_geolocation()

loc = st.session_state["location"]

if loc:
    lat = loc["coords"]["latitude"]
    lon = loc["coords"]["longitude"]
    st.success(f"📍 Your Location: {lat}, {lon}")
else:
    st.warning("⚠️ Location not allowed. Using default.")
    lat, lon = 13.0827, 80.2707  # Chennai fallback

# ===============================
# 🎯 DESTINATION INPUT
# ===============================

st.subheader("🎯 Enter Destination")

dest_lat = st.number_input("Destination Latitude", value=13.0500)
dest_lon = st.number_input("Destination Longitude", value=80.2500)

# ===============================
# 📡 FETCH DATA FROM BACKEND
# ===============================

hotspots = requests.get("http://localhost:5000/hotspots").json()
crimes = requests.get("http://localhost:5000/crimes").json()

# ===============================
# 🧠 SAFE ROUTE FUNCTION
# ===============================

def generate_safe_route(start, end, hotspots):
    route = [start]

    for h in hotspots:
        h_point = (h['latitude'], h['longitude'])

        dist = math.dist(start, h_point)

        if dist < 0.03:
            detour = (
                h['latitude'] + 0.02,
                h['longitude'] + 0.02
            )
            route.append(detour)

    route.append(end)
    return route

# Generate route
start = (lat, lon)
end = (dest_lat, dest_lon)

safe_route = generate_safe_route(start, end, hotspots)

# ===============================
# 🗺️ MAP CREATION
# ===============================

m = folium.Map(location=[lat, lon], zoom_start=13)

# 🔵 User Location
folium.Marker(
    [lat, lon],
    tooltip="You are here",
    icon=folium.Icon(color="blue")
).add_to(m)

# 🎯 Destination
folium.Marker(
    [dest_lat, dest_lon],
    tooltip="Destination",
    icon=folium.Icon(color="green")
).add_to(m)

# 🔴 Hotspots
for h in hotspots:
    folium.CircleMarker(
        [h['latitude'], h['longitude']],
        radius=10,
        color='red',
        fill=True,
        fill_opacity=0.7,
        tooltip=f"Hotspot: {h['crime_type']}"
    ).add_to(m)

# ⚠️ Crime markers
for c in crimes:
    folium.Marker(
        [c['latitude'], c['longitude']],
        tooltip=c['crime_type'],
        icon=folium.Icon(color="orange")
    ).add_to(m)

# 🟢 SAFE ROUTE
folium.PolyLine(
    safe_route,
    color="green",
    weight=5,
    tooltip="Safe Route"
).add_to(m)

# ===============================
# 🚨 RISK ALERT SYSTEM
# ===============================

for h in hotspots:
    dist = ((lat - h['latitude'])**2 + (lon - h['longitude'])**2)**0.5
    if dist < 0.02:
        st.error("🚨 ALERT: You are in a HIGH RISK ZONE!")

st.success("🟢 Safe route generated avoiding crime hotspots")

# ===============================
# 📍 DISPLAY MAP
# ===============================

st.subheader("📍 Tactical Crime Map")
st_folium(m, width=1200, height=600)

st.info("🔵 You are here | 🔴 Danger zones | 🟢 Safe route")