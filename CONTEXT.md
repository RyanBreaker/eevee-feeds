# Feedings

A simple web app for tracking a baby's oral (PO) and NG-tube feedings, with daily totals and a weekly target that increases on a configured day.

## Language

**Feeding**:
A single recorded milk-intake event, with a timestamp, PO amount, NG amount, and optional notes.

**Regular Feeding**:
A Feeding that is not a Snack.
_Avoid_: full feeding, scheduled feeding

**Snack**:
A Feeding that is recorded for completeness. Its volume is included in the Period total and target progress, but it has no suggested target volume and is not treated as the previous Feeding when computing the suggested target or gap for a later Feeding.
_Avoid_: extra feed, top-off

**Period**:
A 24-hour aggregation window for feedings, starting at a configurable time of day (default 6:00 AM local time). A Period belongs to the date on which it starts, and Period boundaries are always computed from the current configured start time — changing the start time re-buckets all historical feedings into new Periods.
_Avoid_: day, date

**Backup**:
An immutable, point-in-time copy of all Feeding records, exported as CSV and stored in a remote location.
_Avoid_: archive, dump, snapshot

**BackupLog**:
A record that a Backup was attempted for a specific Period, capturing the run timestamp and success/failure status.
_Avoid_: backup run, backup attempt

**TargetConfig**:
The app's feeding configuration: the starting feeding-volume target, the weekly increment schedule, the Period start time, and the Tracking mode.

**Tracking mode**:
A global setting on TargetConfig with values `ng_plus_po` or `oral_only`, controlling which intake routes the app captures and emphasizes. In `ng_plus_po` mode both PO and NG amounts are recorded and PO percentage is displayed. In `oral_only` mode only PO amounts are captured, and NG amounts are displayed only when nonzero. Historical data is unaffected by the current mode. Existing installs default to `ng_plus_po`.
_Avoid_: feeding mode, app mode

**Sleep**:
A recorded interval of baby sleep, with a start and end timestamp. Every recorded Sleep subtracts from the elapsed interval used by TargetFeedAmount — only the portion overlapping the interval counts, and an in-progress Sleep counts through the current moment. A Feeding recorded during a Sleep ends that Sleep.

**TargetFeedAmount**:
The recommended milk volume for a single Feeding, calculated by prorating the Period's target volume by the elapsed interval since the most recent Feeding. The interval is computed to the minute, clamped to [2, 4] hours, then reduced by any overlapping Sleep. The recommended amount is rounded down to the nearest 5 mL and is never displayed below 5 mL when an interval exists.
_Avoid_: required feed amount

**FeedingStart**:
The recorded beginning of a feed that has not yet completed, consisting of a single timestamp. A FeedingStart is completed by providing PO and NG amounts, at which point it becomes a Feeding and the FeedingStart is removed.
_Avoid_: in-progress feeding, pending feed, draft feeding

**FeedingStart reminder**:
A notification sent while a FeedingStart exists, fired every 15 minutes after the FeedingStart timestamp. FeedingStart reminders are independent of the normal post-feeding reminders and are cancelled when the feed completes or is discarded.
_Avoid_: in-progress notification, start alert

**PO percentage**:
The percentage of a Feeding's or Period's total volume that was delivered orally, calculated as `po_amount / (po_amount + ng_amount) * 100` and rounded to one decimal place. When the total volume is zero, the value is undefined and displayed as `—`. Displayed only in `ng_plus_po` Tracking mode; in `oral_only` mode it is omitted everywhere (cards, Feeding lists, charts).
_Avoid_: PO ratio, oral fraction

**Same-time variance**:
The difference between the current Period's total intake so far and the total intake at the same elapsed time within a comparison Period. Computed against the previous Period ("vs yesterday") and against the average of the prior 7 Periods ("vs 7-day avg"). The vs-yesterday value is shown whenever the previous Period has at least one Feeding; the 7-day value requires at least 3 prior Periods with Feedings.
_Avoid_: day-over-day diff, pace delta

**Intake trend**:
The linear-regression slope of daily total intake over the last 14 Periods, expressed in mL per day. Shown only when at least 3 of those Periods have Feedings; otherwise displayed as `—`. The slope figure is shown in both Tracking modes; the trend line on the chart is shown only in `oral_only` Tracking mode (where it replaces the PO percentage lines). Replaces PO percentage as the headline trend metric in `oral_only` mode.
_Avoid_: volume trend, intake slope
