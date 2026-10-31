#!/usr/bin/env python3
"""Backward-compatible entry point for the SatDump Meteor-M LRPT decoder."""
from meteor_decoder import main

if __name__ == "__main__":
    print("NOTICE: This project now decodes Meteor-M LRPT with SatDump.")
    main()
