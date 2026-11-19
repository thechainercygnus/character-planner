# 0061: Encrypted backups

Status: accepted (2026-11-21).

## Context

An instance's database held everything people made in the planner, with no backup beyond
copying the SQLite file or running `pg_dump` by hand (#240). The roadmap's refinement
(#214) chose instance-wide backups, managed by permission, encrypted to an age public key.

## Decision (Bryce, 2026-11-19)

1. **A logical dump, not `pg_dump` or SQLite's online backup.** Every table goes through
   SQLAlchemy into one gzipped JSON document, with its format, the app version and the
   schema revision. One format serves SQLite and Postgres, a backup restores into either,
   and the image needs no Postgres client tools. It deviates from #240's wording, which
   named `pg_dump`.
2. **What's left out** (`backup.EXCLUDED`):
   - Blizzard's data: its caches, and snapshots fetched from the API. Blizzard's terms
     keep it 30 days at most (ADR 0034), and a backup can live longer. The next sync
     fetches it again.
   - Secrets: Battle.net tokens and sign-in sessions. People sign in again after a restore.
   - Forever Companion caches, the alert outbox and job leases: they refill on their own.
3. **Encrypted with age** (pyrage) to `BACKUP_AGE_RECIPIENT`, a public key. The private key
   stays on the operator's own machine; the settings refuse a secret key. Restoring means
   decrypting there first.
4. **Stored in S3-compatible storage** (boto3; `BACKUP_S3_*`, https only). Retention is by
   count: the newest `BACKUP_KEEP` (14) are kept, older ones deleted after each upload.
5. **The worker checks hourly** and backs up when one is due: never made, the last one
   failed, or older than `BACKUP_EVERY_HOURS` (24). The outcome is kept in
   `instancesetting` (`backup_status`). A failure raises, so the worker's
   "A scheduled job failed" system alert fires (ADR 0045).
6. **Restore is a command**, `character-planner-db restore --file ... --yes`: into an empty
   database, at the same schema revision as the backup. A mismatch names the version to
   restore with; upgrade afterwards. Postgres sequences are moved past the restored ids.
7. **`backups.manage`** lets the admin see the last backup and back up now in the admin
   area (ADR 0055). Only the admin has it.

## Consequences

- Backups never hold Blizzard's data or anyone's tokens, so they can be kept as long as the
  operator likes; a deleted account leaves them as newer backups replace older ones.
- A restore needs the planner version that made the backup, then an upgrade.
- The dump is held in memory: fine at this app's size, to revisit if a database grows large.
