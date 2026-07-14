# Feedings

A simple web app for tracking a baby's oral (PO) and NG-tube feedings, with daily totals and a weekly target that increases on a configured day.

## Language

**Feeding**:
A single recorded milk-intake event, with a timestamp, PO amount, NG amount, and optional notes.

**Snack**:
A Feeding that is recorded for completeness. Its volume is included in the Period total and target progress, but it has no suggested target volume and is not treated as the previous Feeding when computing the suggested target or gap for a later Feeding.
_Avoid_: extra feed, top-off

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

**TargetFeedAmount**:
The recommended milk volume for a single Feeding, calculated by prorating the Period's target volume by the elapsed interval since the most recent Feeding.
_Avoid_: required feed amount

**FeedingStart**:
The recorded beginning of a feed that has not yet completed, consisting of a single timestamp. A FeedingStart is completed by providing PO and NG amounts, at which point it becomes a Feeding and the FeedingStart is removed.
_Avoid_: in-progress feeding, pending feed, draft feeding

**FeedingStart reminder**:
A notification sent while a FeedingStart exists, fired every 15 minutes after the FeedingStart timestamp. FeedingStart reminders are independent of the normal post-feeding reminders and are cancelled when the feed completes or is discarded.
_Avoid_: in-progress notification, start alert

**PO percentage**:
The percentage of a Feeding's or Period's total volume that was delivered orally, calculated as `po_amount / (po_amount + ng_amount) * 100` and rounded to one decimal place. When the total volume is zero, the value is undefined and displayed as `—`.
_Avoid_: PO ratio, oral fraction
