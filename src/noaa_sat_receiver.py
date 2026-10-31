#!/home/kbnet/.sdr/venv/bin/python3
"""
Roselawn Radio - Real-Time NOAA Weather Satellite Receiver & APT Image Recorder
Automated Receiver tuned for NOAA-18 (137.9125 MHz) & NOAA-19 (137.100 MHz) Passes Tonight over Wirral.
Streams live 2400 Hz APT audio to speakers while recording raw 48 kHz PCM WAV files
and decoding live cloud imagery to ~/Pictures/Weather_Satellites/.
"""

import sys
import os
import time
import wave
import shutil
import curses
import select
import subprocess
import argparse
import numpy as np
from scipy import signal

OUT_DIR = "/home/kbnet/Pictures/Weather_Satellites"

def safe_addstr(stdscr, y, x, text, attr=0):
    try:
        max_y, max_x = stdscr.getmaxyx()
        if 0 <= y < max_y and 0 <= x < max_x:
            max_len = max(0, max_x - x - 1)
            stdscr.addstr(y, x, text[:max_len], attr)
    except Exception:
        pass

def run_tui(stdscr):
    try:
        curses.curs_set(0)
    except Exception:
        pass

    stdscr.keypad(True)
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(1, curses.COLOR_CYAN, -1)     # Title
    curses.init_pair(2, curses.COLOR_GREEN, -1)    # Active Receiving
    curses.init_pair(3, curses.COLOR_YELLOW, -1)   # Accent / Info
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN) # Highlight
    curses.init_pair(5, curses.COLOR_RED, -1)      # High Signal Alert

    stdscr.timeout(100)

    os.makedirs(OUT_DIR, exist_ok=True)

    # Satellite Pass Schedule Tonight
    passes_schedule = [
        {"sat": "NOAA 15", "freq": 137.6200, "start_time": "18:21", "peak_time": "18:27", "end_time": "18:33", "elev": "72.2° (OVERHEAD)"},
        {"sat": "NOAA 19", "freq": 137.1000, "start_time": "05:45", "peak_time": "05:51", "end_time": "05:57", "elev": "74.2° (OVERHEAD)"},
        {"sat": "NOAA 18", "freq": 137.9125, "start_time": "05:49", "peak_time": "05:55", "end_time": "06:01", "elev": "38.6°"},
    ]

    current_pass_idx = 0  # Default to NOAA 15 (137.6200 MHz) for 18:21 UTC Overhead Pass!
    active_pass = passes_schedule[current_pass_idx]

    # Start HackRF APT Satellite Demodulator Engine
    freq_mhz = active_pass["freq"]
    freq_hz = int(freq_mhz * 1e6)
    iq_rate = 2000000
    audio_rate = 48000

    subprocess.run(["pkill", "-9", "-f", "hackrf_transfer"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "aplay"], stderr=subprocess.DEVNULL)
    time.sleep(0.1)

    ts_str = time.strftime("%Y%m%d_%H%M%S")
    wav_path = os.path.join(OUT_DIR, f"NOAA_{active_pass['sat'].replace(' ', '')}_{freq_mhz:.4f}MHz_{ts_str}.wav")

    hackrf_cmd = [
        "hackrf_transfer",
        "-f", str(freq_hz),
        "-s", str(iq_rate),
        "-l", "24",          # Clean LNA gain to prevent ADC saturation from FM towers
        "-v", "20",          # Clean VGA gain
        "-a", "0",           # RF AMP OFF (prevents wideband intermodulation overload)
        "-r", "-"
    ]

    if shutil.which("pw-cat"):
        aplay_cmd = ["pw-cat", "-p", "--rate", str(audio_rate), "--format", "s16", "--channels", "1", "-"]
    elif shutil.which("paplay"):
        aplay_cmd = ["paplay", "--raw", f"--rate={audio_rate}", "--format=s16le", "--channels=1"]
    else:
        aplay_cmd = ["aplay", "-D", "default", "-r", str(audio_rate), "-f", "S16_LE", "-c", "1", "-q"]

    hackrf_proc = subprocess.Popen(hackrf_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    aplay_proc = subprocess.Popen(aplay_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    wf_out = wave.open(wav_path, "wb")
    wf_out.setnchannels(1)
    wf_out.setsampwidth(2)
    wf_out.setframerate(audio_rate)

    chunk_samples = 200000
    chunk_bytes = chunk_samples * 2
    prev_iq = 0.0 + 0.0j

    # 36 kHz FIR Bandpass Filter for APT 137 MHz FM Signal
    numtaps = 31
    fir_apt = signal.firwin(numtaps, 36e3, fs=100000).astype(np.float32)
    zi_audio = np.zeros(numtaps - 1, dtype=np.float32)

    # 2400 Hz Subcarrier Filter for NOAA Satellite Subcarrier SNR
    b_2400, a_2400 = signal.butter(4, [2300 / 50000, 2500 / 50000], btype="bandpass")
    zi_sub = np.zeros(max(len(a_2400), len(b_2400)) - 1, dtype=np.float32)

    rec_start_time = time.time()
    last_size = (0, 0)

    try:
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

            rlist, _, _ = select.select([hackrf_proc.stdout], [], [], 0.05)
            if not rlist:
                if hackrf_proc.poll() is not None:
                    time.sleep(0.5)
                    hackrf_proc = subprocess.Popen(hackrf_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                raw_bytes = b""
            else:
                raw_bytes = hackrf_proc.stdout.read(chunk_bytes)

            raw_data = np.frombuffer(raw_bytes, dtype=np.int8)
            i_raw = raw_data[0::2].astype(np.float32) / 128.0
            q_raw = raw_data[1::2].astype(np.float32) / 128.0

            n_even = (len(i_raw) // 20) * 20
            if n_even < 20:
                continue

            i_raw = i_raw[:n_even]
            q_raw = q_raw[:n_even]

            # Decimate raw IQ 2.0MHz -> 100kHz (factor of 20)
            i_dec = i_raw.reshape(-1, 20).mean(axis=1)
            q_dec = q_raw.reshape(-1, 20).mean(axis=1)
            iq_dec = i_dec + 1j * q_dec

            # FM Demodulation
            iq_prev = np.empty_like(iq_dec)
            iq_prev[0] = prev_iq
            iq_prev[1:] = iq_dec[:-1]
            prev_iq = iq_dec[-1]

            demod = np.angle(iq_dec * np.conj(iq_prev))

            # 2400 Hz APT Satellite Subcarrier SNR Calculation
            subcarrier_filt, zi_sub = signal.lfilter(b_2400, a_2400, demod, zi=zi_sub)
            sub_pwr = float(np.std(subcarrier_filt))
            total_pwr = float(np.std(demod))
            sub_ratio = sub_pwr / (total_pwr + 1e-6)
            snr_db = min(30.0, max(0.0, (sub_ratio - 0.008) * 500.0))

            # Filter APT audio
            audio_filt, zi_audio = signal.lfilter(fir_apt, 1.0, demod, zi=zi_audio)

            # Resample 100kHz -> 48kHz
            audio_48k = audio_filt[::2]

            # Scale Audio
            audio_scaled = audio_48k * 18000.0
            audio_clipped = np.clip(audio_scaled, -32767, 32767).astype(np.int16)

            # Output to speakers & record to WAV file
            is_muted = os.path.exists("/tmp/fm_mute.flag")
            if not is_muted:
                aplay_proc.stdin.write(audio_clipped.tobytes())
                aplay_proc.stdin.flush()
            else:
                silence = np.zeros_like(audio_clipped).tobytes()
                aplay_proc.stdin.write(silence)
                aplay_proc.stdin.flush()

            wf_out.writeframes(audio_clipped.tobytes())

            # Header
            mute_tag = "MUTE" if is_muted else "LIVE"
            title = f"🛰️ ROSELAWN LIVE NOAA SATELLITE RECEIVER & RECORDER  [{mute_tag}]"
            safe_addstr(stdscr, 1, 2, title, curses.color_pair(1) | curses.A_BOLD)
            safe_addstr(stdscr, 2, 2, f"Target: {active_pass['sat']} ({freq_mhz:.4f} MHz)  •  Peak Elevation: {active_pass['elev']}  •  'n': Next Sat  •  'm': Mute  •  'q': Quit", curses.A_DIM)
            safe_addstr(stdscr, 3, 2, "─" * (max_x - 4), curses.A_DIM)

            # Live Reception Status
            elapsed_sec = int(time.time() - rec_start_time)
            m_val, s_val = elapsed_sec // 60, elapsed_sec % 60

            safe_addstr(stdscr, 4, 2, f"🔴 ACTIVE CAPTURE IN PROGRESS: {active_pass['sat']} ({freq_mhz:.4f} MHz)   [{m_val:02d}:{s_val:02d}]", curses.color_pair(5) | curses.A_BOLD)
            safe_addstr(stdscr, 5, 2, f"Saved File: {os.path.basename(wav_path)}", curses.color_pair(3))

            # Live Signal Strength (RSSI Meter)
            bars_len = int(min(25, snr_db / 1.2))
            meter_bar = "█" * bars_len + "░" * (25 - bars_len)
            safe_addstr(stdscr, 7, 2, f"137 MHz Signal SNR: [{meter_bar}]  {snr_db:.1f} dB", curses.color_pair(2) | curses.A_BOLD)

            # Sound Profile Hint
            if snr_db >= 10.0:
                hint_str = "🔊 SOUND PROFILE: Strong 2400 Hz APT Sync Pulse Active! ('Tick-Tock' Satellite Beep)"
                color_h = curses.color_pair(2) | curses.A_BOLD
            else:
                hint_str = "📡 Waiting for satellite to break horizon... Keep whip antenna extended to ~53.4 cm!"
                color_h = curses.color_pair(3)

            safe_addstr(stdscr, 9, 2, hint_str, color_h)

            # Schedule Table
            safe_addstr(stdscr, 11, 2, "─" * (max_x - 4), curses.A_DIM)
            safe_addstr(stdscr, 12, 2, "📅 TONIGHT'S NOAA PASS SCHEDULE FOR WIRRAL, MERSEYSIDE:", curses.color_pair(1) | curses.A_BOLD)

            for p_idx, p_item in enumerate(passes_schedule):
                is_curr = (p_idx == current_pass_idx)
                row_str = f"   {'▶' if is_curr else ' '} {p_item['sat']:<10} {p_item['freq']:<12.4f} MHz   Window: {p_item['start_time']} ──► {p_item['end_time']} GMT   Peak: {p_item['peak_time']} GMT ({p_item['elev']})"
                
                if is_curr:
                    safe_addstr(stdscr, 13 + p_idx, 2, row_str, curses.color_pair(5) | curses.A_BOLD)
                else:
                    safe_addstr(stdscr, 13 + p_idx, 2, row_str, curses.A_DIM)

            safe_addstr(stdscr, max_y - 2, 2, "─" * (max_x - 4), curses.A_DIM)
            safe_addstr(stdscr, max_y - 1, 2, f"Recording raw satellite PCM audio to {OUT_DIR}/. Press 'q' when pass finishes.", curses.A_DIM)

            stdscr.noutrefresh()
            curses.doupdate()

            key = stdscr.getch()

            if key != -1:
                if key in [ord('q'), ord('Q')]:
                    break
                elif key in [ord('m'), ord('M')]:
                    mute_flag = "/tmp/fm_mute.flag"
                    if os.path.exists(mute_flag):
                        os.remove(mute_flag)
                    else:
                        with open(mute_flag, "w") as fm:
                            fm.write("MUTE")
                elif key in [ord('n'), ord('N')]:
                    # Switch to next pass (NOAA 19 at 137.100 MHz)
                    current_pass_idx = (current_pass_idx + 1) % len(passes_schedule)
                    active_pass = passes_schedule[current_pass_idx]
                    freq_mhz = active_pass["freq"]
                    freq_hz = int(freq_mhz * 1e6)

                    hackrf_proc.terminate()
                    aplay_proc.terminate()
                    wf_out.close()

                    time.sleep(0.1)
                    ts_str = time.strftime("%Y%m%d_%H%M%S")
                    wav_path = os.path.join(OUT_DIR, f"NOAA_{active_pass['sat'].replace(' ', '')}_{freq_mhz:.4f}MHz_{ts_str}.wav")

                    hackrf_cmd[4] = str(freq_hz)
                    hackrf_proc = subprocess.Popen(hackrf_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    aplay_proc = subprocess.Popen(aplay_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    wf_out = wave.open(wav_path, "wb")
                    wf_out.setnchannels(1)
                    wf_out.setsampwidth(2)
                    wf_out.setframerate(audio_rate)
                    rec_start_time = time.time()

    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        try:
            wf_out.close()
            hackrf_proc.terminate()
            aplay_proc.terminate()
        except Exception:
          pass

        # Auto-trigger NOAA APT image decoder on capture exit if WAV file was recorded
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 50000:
            decoder_script = "/home/kbnet/noaa_decoder.py"
            if os.path.exists(decoder_script):
                try:
                    subprocess.run(["/home/kbnet/.sdr/venv/bin/python3", decoder_script, wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

def main():
    curses.wrapper(run_tui)

if __name__ == "__main__":
    main()
