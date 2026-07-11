# Feedings

A simple web app for tracking a baby's oral (PO) and NG-tube feedings, with daily totals and a weekly target that increases on a configured day.

## Language

**Feeding**:
A single recorded milk-intake event, with a timestamp, PO amount, NG amount, and optional notes.

**Period**:
A 24-hour aggregation window for feedings, starting at 6:00 AM local time.
_Avoid_: day, date

**Backup**:
An immutable, point-in-time copy of all Feeding records, exported as CSV and stored in a remote location.
_Avoid_: archive, dump, snapshot

**BackupLog**:
A record that a Backup was attempted for a specific Period, capturing the run timestamp and success/failure status.
_Avoid_: backup run, backup attempt

**TargetConfig**:
The configuration that defines the starting feeding-volume target and the weekly increment schedule.
