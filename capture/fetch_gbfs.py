#!/usr/bin/env python3
import os
import io
import logging
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

GBFS_BASE = "https://gbfs.citibikenyc.com/gbfs/2"
STATION_INFO_URL = f"{GBFS_BASE}/en/station_information.json"
STATION_STATUS_URL = f"{GBFS_BASE}/en/station_status.json"

EDT = timezone(timedelta(hours=-4))

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["REPO"]
RELEASE_TAG = os.environ["RELEASE_TAG"]

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def fetch_json(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; citibike-gbfs-research/1.0)"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_station_information():
    data = fetch_json(STATION_INFO_URL)
    df = pd.DataFrame(data["data"]["stations"])
    keep = ["station_id", "name", "lat", "lon", "capacity", "region_id"]
    return df[[c for c in keep if c in df.columns]].copy()


def fetch_station_status():
    data = fetch_json(STATION_STATUS_URL)
    ts_server = data.get("last_updated")
    df = pd.DataFrame(data["data"]["stations"])
    keep = [
        "station_id",
        "num_bikes_available",
        "num_ebikes_available",
        "num_bikes_disabled",
        "num_docks_available",
        "num_docks_disabled",
        "is_installed",
        "is_renting",
        "is_returning",
        "last_reported",
    ]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["feed_last_updated"] = ts_server
    return df


def get_release_id(tag):
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code == 404:
        log.error(f"Release '{tag}' not found. Create it on GitHub first.")
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()["id"]


def upload_asset(release_id, filename, data):
    url = (
        f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets"
        f"?name={filename}"
    )
    resp = requests.post(
        url,
        headers={**HEADERS, "Content-Type": "application/octet-stream"},
        data=data,
        timeout=60,
    )
    resp.raise_for_status()
    log.info(f"Uploaded: {resp.json().get('browser_download_url', '')}")


def main():
    now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    ts_str = now_utc.strftime("%Y%m%d_%H%M_UTC")
    filename = f"citibike_{ts_str}.parquet"

    log.info(f"Capture: {now_utc.isoformat()} → {filename}")

    info = fetch_station_information()
    status = fetch_station_status()
    df = status.merge(info, on="station_id", how="left")
    df["captured_utc"] = now_utc.isoformat()
    df["captured_edt"] = now_utc.astimezone(EDT).isoformat()

    log.info(f"Stations: {len(df)}")

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    parquet_bytes = buf.getvalue()
    log.info(f"Parquet size: {len(parquet_bytes):,} bytes")

    release_id = get_release_id(RELEASE_TAG)
    upload_asset(release_id, filename, parquet_bytes)
    log.info("Done.")


if __name__ == "__main__":
    main()
