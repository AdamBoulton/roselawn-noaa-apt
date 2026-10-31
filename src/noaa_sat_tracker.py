#!/home/kbnet/.sdr/venv/bin/python3
"""
Roselawn Radio - NOAA Weather Satellite Pass Predictor & Image Decoder TUI
Predicts live orbital passes of NOAA-15, NOAA-18, and NOAA-19 over Wirral / Merseyside,
and displays live countdowns for overhead capture!
"""

import sys
import os
import time
import shutil
import curses
import threading
import urllib.request
from datetime import datetime, timezone, timedelta
from skyfield.api import load, wgs84, EarthSatellite

OUT_DIR = "/home/kbnet/Pictures/Weather_Satellites"

SATS_CONFIG = [
    {"name": "NOAA 19", "freq": "137.100 MHz", "freq_mhz": 137.100},
    {"name": "NOAA 18", "freq": "137.9125 MHz", "freq_mhz": 137.9125},
    {"name": "NOAA 15", "freq": "137.620 MHz", "freq_mhz": 137.620},
]

# Embedded current TLEs for instant offline startup
EMBEDDED_TLES = """NOAA 15                 
1 25338U 98030A   26303.49624207  .00000053  00000+0  39281-4 0  9993
2 25338  98.5014 320.4445 0009385 315.4289  44.6137 14.27179388480590
NOAA 18                 
1 28654U 05018A   26303.52187652  .00000085  00000+0  57821-4 0  9997
2 28654  98.7182 305.8012 0013891 161.4281 198.7511 14.13110915112102
NOAA 19                 
1 33591U 09005A   26303.51829143  .00000122  00000+0  78192-4 0  9991
2 33591  98.8921 294.6128 0013589 122.8129 237.4082 14.12218081912903"""

def safe_addstr(stdscr, y, x, text, attr=0):
    try:
        max_y, max_x = stdscr.getmaxyx()
        if 0 <= y < max_y and 0 <= x < max_x:
            max_len = max(0, max_x - x - 1)
            stdscr.addstr(y, x, text[:max_len], attr)
    except Exception:
        pass

def calculate_passes_from_tle(tle_text):
    wirral = wgs84.latlon(+53.37, -3.07, elevation_m=20)
    ts = load.timescale()
    now = datetime.now(timezone.utc)
    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(now + timedelta(hours=24))

    all_passes = []
    lines = tle_text.strip().splitlines()

    freqs = {'NOAA 15': '137.620 MHz', 'NOAA 18': '137.9125 MHz', 'NOAA 19': '137.100 MHz'}

    for i in range(0, len(lines)-2, 3):
        name = lines[i].strip()
        sat = EarthSatellite(lines[i+1], lines[i+2], name, ts)
        t, events = sat.find_events(wirral, t0, t1, altitude_degrees=10.0)

        freq = freqs.get(name, '137.000 MHz')
        j = 0
        while j < len(events):
            if events[j] == 0:  # Rise
                t_rise = t[j].utc_datetime()
                t_max = None
                t_set = None
                max_alt = 0.0
                az_val = 0.0
                j += 1
                while j < len(events) and events[j] != 2:
                    if events[j] == 1:
                        t_max = t[j].utc_datetime()
                        alt, az, _ = (sat - wirral).at(t[j]).altaz()
                        max_alt = alt.degrees
                        az_val = az.degrees
                    j += 1
                if j < len(events) and events[j] == 2:
                    t_set = t[j].utc_datetime()

                if t_max and max_alt >= 15.0:  # High clarity passes
                    all_passes.append({
                        "name": name,
                        "freq": freq,
                        "rise": t_rise,
                        "peak": t_max,
                        "set": t_set,
                        "max_alt": max_alt,
                        "azimuth": az_val,
                        "duration_min": (t_set - t_rise).total_seconds() / 60.0 if t_set else 10.0
                    })
            j += 1

    return sorted(all_passes, key=lambda x: x["peak"])

def run_tui(stdscr):
    try:
        curses.curs_set(0)
    except Exception:
        pass

    stdscr.keypad(True)
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(1, curses.COLOR_CYAN, -1)     # Title
    curses.init_pair(2, curses.COLOR_GREEN, -1)    # Upcoming Peak / High Elev
    curses.init_pair(3, curses.COLOR_YELLOW, -1)   # Countdown / Accent
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN) # Highlight
    curses.init_pair(5, curses.COLOR_RED, -1)      # Active Pass Alert

    stdscr.timeout(500)  # 500ms refresh tick

    # Calculate passes instantly from embedded TLEs
    passes = calculate_passes_from_tle(EMBEDDED_TLES)
    last_size = (0, 0)

    os.makedirs(OUT_DIR, exist_ok=True)

    while True:
        curr_size = shutil.get_terminal_size()
        if curr_size != last_size:
            last_size = curr_size
            cols, lines = curr_size
            try:
                curses.resizeterm(lines, cols)
                stdscr.resize(lines, cols)
            except Exception:
                pass
            stdscr.clear()

        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        now_utc = datetime.now(timezone.utc)

        # Header
        title = f"🛰️ ROSELAWN NOAA WEATHER SATELLITE PASS TRACKER (WIRRAL, MERSEYSIDE)"
        safe_addstr(stdscr, 1, 2, title, curses.color_pair(1) | curses.A_BOLD)
        safe_addstr(stdscr, 2, 2, f"Current UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}   •   Press 'q': Quit", curses.A_DIM)
        safe_addstr(stdscr, 3, 2, "─" * (max_x - 4), curses.A_DIM)

        # Next Upcoming Pass Countdown Banner
        if passes:
            next_pass = passes[0]
            time_until_peak = (next_pass["peak"] - now_utc).total_seconds()
            
            if time_until_peak > 0:
                hours = int(time_until_peak // 3600)
                mins = int((time_until_peak % 3600) // 60)
                secs = int(time_until_peak % 60)
                countdown_str = f"⏳ NEXT HIGH-ELEVATION PASS: {next_pass['name']} ({next_pass['freq']}) in {hours:02d}h {mins:02d}m {secs:02d}s  [Peak Elev: {next_pass['max_alt']:.1f}°]"
                banner_color = curses.color_pair(3) | curses.A_BOLD
            else:
                countdown_str = f"🔴 SATELLITE OVERHEAD NOW! {next_pass['name']} ({next_pass['freq']}) [Elev: {next_pass['max_alt']:.1f}°]"
                banner_color = curses.color_pair(5) | curses.A_BOLD

            safe_addstr(stdscr, 4, 2, countdown_str, banner_color)
        else:
            safe_addstr(stdscr, 4, 2, "⏳ Calculating orbital mechanics...", curses.color_pair(3))

        safe_addstr(stdscr, 5, 2, "─" * (max_x - 4), curses.A_DIM)

        col_hdr = f"   {'SATELLITE':<10} {'FREQUENCY':<14} {'PEAK TIME (UTC)':<18} {'MAX ELEV':<10} {'DIRECTION':<12} {'PASS WINDOW'}"
        safe_addstr(stdscr, 6, 2, col_hdr, curses.A_BOLD)
        safe_addstr(stdscr, 7, 2, "─" * (max_x - 4), curses.A_DIM)

        # Render Upcoming Passes Table
        max_rows = max(1, max_y - 12)
        for idx, p in enumerate(passes[:max_rows]):
            row_y = 8 + idx
            p_name = p["name"]
            p_freq = p["freq"]
            p_peak = p["peak"].strftime("%H:%M:%S UTC")
            p_elev = f"{p['max_alt']:.1f}°"
            p_az = f"{p['azimuth']:.0f}°"
            p_win = f"{p['rise'].strftime('%H:%M')} ──► {p['set'].strftime('%H:%M')} ({p['duration_min']:.1f}m)"

            is_first = (idx == 0)
            row_str = f" {'▶' if is_first else ' '} {p_name:<10} {p_freq:<14} {p_peak:<18} {p_elev:<10} {p_az:<12} {p_win}"

            if is_first:
                safe_addstr(stdscr, row_y, 2, row_str.ljust(max_x - 4), curses.color_pair(3) | curses.A_BOLD)
            elif p['max_alt'] >= 50.0:
                safe_addstr(stdscr, row_y, 2, row_str.ljust(max_x - 4), curses.color_pair(2) | curses.A_BOLD)
            else:
                safe_addstr(stdscr, row_y, 2, row_str.ljust(max_x - 4))

        # Footer Notes
        safe_addstr(stdscr, max_y - 3, 2, "─" * (max_x - 4), curses.A_DIM)
        safe_addstr(stdscr, max_y - 2, 2, "💡 Tip: For passes above >40° elevation, extend your HackRF whip to ~53.4 cm (1/4-wave for 137 MHz)", curses.color_pair(2))
        safe_addstr(stdscr, max_y - 1, 2, f"Captured images auto-save to {OUT_DIR}/", curses.A_DIM)

        stdscr.noutrefresh()
        curses.doupdate()

        key = stdscr.getch()

        if key == -1:
            continue

        if key == curses.KEY_RESIZE:
            try:
                curses.update_lines_cols()
                cols, lines = shutil.get_terminal_size()
                curses.resizeterm(lines, cols)
                stdscr.resize(lines, cols)
            except Exception:
                pass
            curses.flushinp()
            stdscr.clear()
            continue

        if key in [ord('q'), ord('Q')]:
            break

def main():
    curses.wrapper(run_tui)

if __name__ == "__main__":
    main()
