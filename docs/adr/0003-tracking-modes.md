# Tracking modes instead of removing NG support

The baby is graduating off the NG tube to fully oral feeding, but we chose not to delete the NG code paths. Instead, TargetConfig gains a global Tracking mode (`ng_plus_po` / `oral_only`, default `ng_plus_po` for existing installs), switchable from Settings. In `oral_only` mode the app captures PO amounts only, omits PO percentage everywhere, and follows one universal display rule: NG amounts appear only when nonzero — so historical NG-era data stays truthful without cluttering the new workflow. We rejected a per-Feeding route field (granularity we no longer need) and outright removal of NG support (irreversible, and setbacks happen). The CSV/backup schema is unchanged: new rows simply record `NG = 0`.

## Consequences

- NG-related code (input field, PO percentage metrics, chart lines) remains but is dormant in `oral_only` mode; mode branches key off the single TargetConfig setting.
- Mode values are stored in the database, so renaming them later requires a migration.
- PO percentage is defined in `CONTEXT.md` as displayed only in `ng_plus_po` mode; `oral_only` mode replaces its headline role with the Intake trend slope.
