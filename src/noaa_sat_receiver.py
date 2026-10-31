#!/usr/bin/env python3
"""Backward-compatible entry point; runs the current Meteor-M LRPT receiver."""
from meteor_sat_receiver import main

if __name__ == "__main__":
    print("NOTICE: NOAA-15/18/19 APT is decommissioned. Starting the Meteor-M LRPT receiver instead.")
    main()
