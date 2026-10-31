#!/usr/bin/env python3
"""Predict Meteor-M N2-3/N2-4 LRPT passes over Roselawn (Wirral).

Fresh TLEs are downloaded from CelesTrak and cached. Old elements are rejected
rather than silently presenting unreliable pass predictions.
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skyfield.api import EarthSatellite, load, wgs84

SITE_LATITUDE = 53.37
SITE_LONGITUDE = -3.07
SITE_ELEVATION_M = 20
LRPT_FREQUENCY_MHZ = 137.900
LOOKAHEAD_HOURS = 24
MAX_TLE_AGE_DAYS = 7

SATELLITES = {
    "METEOR-M2-3": 57166,
    "METEOR-M2-4": 59051,
}
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={catalog}&FORMAT=tle"
CACHE_DIR = Path.home() / ".cache" / "roselawn-radio" / "tle"


@dataclass(frozen=True)
class TLE:
    name: str
    catalog: int
    line1: str
    line2: str
    epoch: datetime
    source: str

    @property
    def age_days(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - self.epoch).total_seconds() / 86400.0)


def tle_epoch(line1: str) -> datetime:
    """Decode the epoch field from a two-line element set."""
    field = line1[18:32]
    year_two_digits = int(field[:2])
    year = 2000 + year_two_digits if year_two_digits < 57 else 1900 + year_two_digits
    day_of_year = float(field[2:])
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1.0)


def parse_tle(text: str, catalog: int, source: str) -> TLE:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index in range(len(lines) - 1):
        line1, line2 = lines[index], lines[index + 1]
        if line1.startswith("1 ") and line2.startswith("2 "):
            try:
                found_catalog = int(line1[2:7])
            except ValueError:
                continue
            if found_catalog != catalog:
                continue
            candidate_name = lines[index - 1] if index > 0 else ""
            if candidate_name.startswith(("1 ", "2 ")):
                candidate_name = ""
            name = candidate_name or next(
                (key for key, value in SATELLITES.items() if value == catalog),
                f"METEOR-{catalog}",
            )
            return TLE(name, catalog, line1, line2, tle_epoch(line1), source)
    raise ValueError(f"No valid TLE for NORAD catalogue number {catalog} in response")


def load_tle(catalog: int) -> TLE:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{catalog}.tle"
    request = urllib.request.Request(
        TLE_URL.format(catalog=catalog),
        headers={"User-Agent": "RoselawnRadio/1.0 (satellite pass prediction)"},
    )

    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read().decode("utf-8")
        tle = parse_tle(body, catalog, "CelesTrak (live)")
        if tle.age_days > MAX_TLE_AGE_DAYS:
            raise ValueError(
                f"CelesTrak returned a {tle.age_days:.1f}-day-old TLE for {catalog}"
            )
        cache_path.write_text(body, encoding="utf-8")
        return tle
    except (OSError, urllib.error.URLError, UnicodeDecodeError, ValueError) as live_error:
        if not cache_path.exists():
            raise RuntimeError(
                f"Could not download TLE for {catalog}, and no cached TLE exists: {live_error}"
            ) from live_error
        cached = parse_tle(cache_path.read_text(encoding="utf-8"), catalog, "local cache")
        if cached.age_days > MAX_TLE_AGE_DAYS:
            raise RuntimeError(
                f"Live TLE download failed and cached TLE for {catalog} is "
                f"{cached.age_days:.1f} days old (maximum {MAX_TLE_AGE_DAYS} days). "
                "Check the internet connection; refusing to use stale orbital data."
            ) from live_error
        print(
            f"WARNING: using cached TLE for {cached.name} ({cached.age_days:.1f} days old): "
            f"{live_error}",
            file=sys.stderr,
        )
        return cached


def calculate_passes(
    hours: float = LOOKAHEAD_HOURS,
    min_elevation: float = 20.0,
    satellite_filter: str | None = None,
) -> list[dict]:
    """Return upcoming passes above min_elevation, ordered by AOS."""
    now = datetime.now(timezone.utc)
    ts = load.timescale(builtin=True)
    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(now + timedelta(hours=hours))
    observer = wgs84.latlon(
        SITE_LATITUDE, SITE_LONGITUDE, elevation_m=SITE_ELEVATION_M
    )
    passes: list[dict] = []
    loaded = 0

    for name, catalog in SATELLITES.items():
        if satellite_filter and name != satellite_filter:
            continue
        try:
            tle = load_tle(catalog)
            satellite = EarthSatellite(tle.line1, tle.line2, name, ts)
            loaded += 1
            times, events = satellite.find_events(
                observer, t0, t1, altitude_degrees=10.0
            )
            rise_time = None
            peak_time = None
            peak_elevation = 0.0
            peak_azimuth = 0.0

            for event_time, event in zip(times, events):
                event_utc = event_time.utc_datetime().astimezone(timezone.utc)
                if event == 0:
                    rise_time = event_utc
                    peak_time = None
                    peak_elevation = 0.0
                    peak_azimuth = 0.0
                elif event == 1 and rise_time is not None:
                    peak_time = event_utc
                    altitude, azimuth, _ = (satellite - observer).at(event_time).altaz()
                    peak_elevation = float(altitude.degrees)
                    peak_azimuth = float(azimuth.degrees)
                elif event == 2 and rise_time is not None:
                    if peak_time is not None and peak_elevation >= min_elevation:
                        passes.append(
                            {
                                "satellite": name,
                                "catalog": catalog,
                                "frequency_mhz": LRPT_FREQUENCY_MHZ,
                                "rise": rise_time,
                                "peak": peak_time,
                                "set": event_utc,
                                "max_elevation": peak_elevation,
                                "azimuth": peak_azimuth,
                                "tle_source": tle.source,
                                "tle_age_days": tle.age_days,
                            }
                        )
                    rise_time = None
                    peak_time = None
        except Exception as exc:
            print(f"WARNING: could not calculate {name}: {exc}", file=sys.stderr)

    if loaded == 0:
        raise RuntimeError("No current Meteor TLEs could be loaded; cannot predict passes.")
    return sorted(passes, key=lambda item: item["rise"])


def print_passes(passes: list[dict]) -> None:
    if not passes:
        print("No passes meet the elevation threshold in the selected look-ahead window.")
        return
    print("ROSELAWN RADIO — METEOR-M LRPT PASSES")
    print(
        f"Site: {SITE_LATITUDE:.4f}, {SITE_LONGITUDE:.4f} | "
        f"Frequency: {LRPT_FREQUENCY_MHZ:.3f} MHz | Times: UTC"
    )
    print("-" * 104)
    print(
        f"{'SATELLITE':<16} {'AOS':<19} {'PEAK':<19} {'LOS':<19} "
        f"{'MAX EL':>7} {'AZ':>6} {'TLE':>8}"
    )
    for item in passes:
        print(
            f"{item['satellite']:<16} "
            f"{item['rise']:%Y-%m-%d %H:%M:%S} "
            f"{item['peak']:%Y-%m-%d %H:%M:%S} "
            f"{item['set']:%Y-%m-%d %H:%M:%S} "
            f"{item['max_elevation']:6.1f}° "
            f"{item['azimuth']:5.0f}° "
            f"{item['tle_age_days']:6.1f}d"
        )
    print("-" * 104)
    print("AOS/LOS are calculated at 10° elevation; max elevation is the pass culmination.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Predict current Meteor-M N2-3/N2-4 LRPT passes over the Wirral."
    )
    parser.add_argument("--hours", type=float, default=LOOKAHEAD_HOURS)
    parser.add_argument("--min-elevation", type=float, default=20.0)
    parser.add_argument("--satellite", choices=tuple(SATELLITES))
    args = parser.parse_args()
    try:
        passes = calculate_passes(args.hours, args.min_elevation, args.satellite)
        print_passes(passes)
    except Exception as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
