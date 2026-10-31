# Roselawn Radio — NOAA Weather Satellite APT Suite 🛰️

Automated Software Defined Radio (SDR) receiver, live orbital tracker, and image decoder for **NOAA Weather Satellites (NOAA 15, NOAA 18, NOAA 19)** on VHF **137 MHz APT (Automatic Picture Transmission)**.

Built for **HackRF One** on Linux Mint / Ubuntu with PipeWire audio streaming and automated `noaa-apt` weather map generation.

---

## 📐 Architecture & Pipeline

```text
  ┌─────────────────────────┐
  │  V-Dipole Antenna       │ (137 MHz VHF, 120° V-angle, ~53.5 cm per arm)
  └────────────┬────────────┘
               │
  ┌────────────▼────────────┐
  │  HackRF One SDR         │ (137.100 - 137.9125 MHz, 2.0 MSPS IQ Capture)
  └────────────┬────────────┘
               │
  ┌────────────▼────────────┐
  │  noaa_sat_receiver.py   │ ──► Live PipeWire Stream (`pw-cat` 2400 Hz Sync Beep)
  │  (FM Demodulator & TUI) │ ──► Raw 48 kHz PCM WAV Recording
  └────────────┬────────────┘
               │
  ┌────────────▼────────────┐
  │  noaa_decoder.py        │
  │  (noaa-apt 1.4.1 Engine)│ ──► High-Res False-Color Satellite Weather PNG Map
  └─────────────────────────┘
```

---

## 📡 Hardware & Antenna Setup Guide

1. **Antenna Type:** Telescopic V-Dipole Antenna Kit.
2. **Element Length:** Extend each whip arm to **~53 – 54 cm (~21 inches)** per arm.
   * *Physics:* Resonant quarter-wave length ($\lambda/4$) at 137.5 MHz.
3. **Orientation:** Position the elements in a **horizontal plane** angled at **120° V**, pointing towards open sky (North/South orientation).

---

## 🚀 Quick Start

### 1. Requirements & Dependencies

```bash
# System Dependencies
sudo apt-get update
sudo apt-get install -y hackrf pipewire-audio-client-libraries noaa-apt

# Python Virtual Environment Setup
python3 -m venv ~/.sdr/venv
source ~/.sdr/venv/bin/activate
pip install -r requirements.txt
```

### 2. Live Orbital Satellite Tracker

Predicts upcoming satellite passes, peak elevation angles, and countdowns over your location:

```bash
python3 src/noaa_sat_tracker.py
```

### 3. Live Satellite Receiver & Recorder

Captures 137 MHz APT satellite signals, streams live audio, and logs pass progress:

```bash
python3 src/noaa_sat_receiver.py
```

### 4. Manual / Standalone Image Decoder

Convert any recorded 48 kHz NOAA WAV recording into a high-res PNG cloud map:

```bash
python3 src/noaa_decoder.py path/to/recording.wav
```

---

## 🛰️ Supported NOAA Satellites

* **NOAA 15:** `137.6200 MHz`
* **NOAA 18:** `137.9125 MHz`
* **NOAA 19:** `137.1000 MHz`

Output images are saved automatically to `~/Pictures/Weather_Satellites/`.

---

## 📄 License

MIT License — Created for the Roselawn Radio SDR Project.
