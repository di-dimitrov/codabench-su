# Changes log (audit)

Audit of every change made by Claude Code in this repository (`codabench-su`, a Codabench fork for the SemEval 2027
Task 9 event). Newest entries go at the bottom of each section; add a new numbered entry for every future change.

- **Branch:** `registration-changes-after-refresh` (based on `upstream/develop` at `dede0ba4`, plus the owner's own commits)
- **Last commit when this log was written:** `00598787` ("Fix FirstName,LastName issue")
- **Status of everything below: NOT COMMITTED** (working tree changes and new untracked files only)
- **Verification:** nothing here was run against a real Codabench instance. Where the code was exercised at all it was on a
  throwaway local setup (SQLite, S3 mock) and is stated per entry. The owner does not run tests on this machine.

Entry format: **what** changed, **files**, **why / who decided**, **status**, **notes**.

---

## 1. Summary table

| # | Date | Area | One line | Status |
|---|------|------|----------|--------|
| 1 | 2026-10-24 | Review | Review of the 168 upstream commits imported into `develop` (no code change) | done |
| 2 | 2026-10-24 | Migrations | Merge migration for the two `profiles` leaf nodes | uncommitted |
| 3 | 2026-10-24 | Settings | `TASK9_COMPETITION_IDS` configurable from the environment | uncommitted |
| 4 | 2026-10-24 | Sign-up | Terms-and-conditions link and indentation in `signup.html` | uncommitted |
| 5 | 2026-10-24 | Infra | Caddy proxies MinIO to port 9000 | uncommitted |
| 6 | 2026-10-24 | Infra | `docker-compose.yml` cosmetics, `site_worker` memory limit 5GB | uncommitted |
| 7 | 2026-10-24 | Auto-enroll | Denied anywhere = denied everywhere, denial wins | uncommitted |
| 8 | 2026-10-24 | Email | Organizers' mass email: no denied/deleted recipients | uncommitted |
| 9 | 2026-10-24 | Review | Comparison with AI4Media-Bench (no code change) | done |
| 10 | 2026-10-25 | Email | Mass email rewritten: BCC batches, formatting kept, plain text, sanitizing | uncommitted |
| 11 | 2026-10-25 | Email settings | `EMAIL_USE_TLS` / `EMAIL_PORT` parsing, `EMAIL_BULK_BATCH_SIZE` | uncommitted |
| 12 | 2026-10-25 | Organizer UI | "Pending participants" indicator | uncommitted |
| 13 | 2026-10-25 | Review fixes | Code-review findings fixed (fan-out robustness, duplicate admin check) | uncommitted |
| 14 | 2026-10-25 | Email | Mass email has no visible `To` (university SMTP) | uncommitted |
| 15 | 2026-10-26 | Leaderboard | Team Name + Username columns, exports gain Team Name | uncommitted |
| 16 | 2026-10-26 | Users | Account deletion also clears team name and affiliation | uncommitted |
| 17 | 2026-10-26 | Privacy | Other users' emails no longer sent to the browser; account/notification pages owner-only | uncommitted |
| 18 | 2026-10-24..26 | Tests | Tests written (not run) and `src/conftest.py` | uncommitted, owner ignores tests |
| 19 | 2026-10-26 | Tests | Mass-email test file deleted | done |
| 20 | 2026-10-27 | Submissions UI | Drag & drop zone with zip checks and an explicit Submit button | uncommitted |
| 21 | 2026-10-27 | Static files | `ASSET_VERSION` cache busting + `no-cache` header on `/static/*` | uncommitted |
| 22 | 2026-10-27 | Failed submissions | Docker pull failure is reported reliably and its log is created | uncommitted |
| 23 | 2026-10-27 | Failed submissions | Failure types, ERROR tab, organizer-only details, configurable stuck-submission cleanup | uncommitted |
| 24 | 2026-10-27 | Backups / disk | Backup script: weekly MinIO archive, small retention, free-space check, correct path | uncommitted |
| 25 | 2026-10-27 | Disk | Caddy access log rotates at 100 MiB, 5 files kept | uncommitted |

---

## 2. Detailed entries

### 1. Review of the upstream import (no code change)
- **What:** `develop` was found to be exactly `upstream/develop` + one local commit ("Updates on setup"). The 168 upstream
  commits (125 non-merge) were summarised (multi-task/group submissions, privacy of competition fields, announcements,
  external competitions, compute-worker reliability, home page redesign, Django 5.2.18). Problems were found in the
  local commit because it was made on a stale base and overwrote newer upstream files: missing
  `external_competitions` app and `EXTERNAL_COMPETITIONS_ENABLED` setting, resurrected `User.is_bot`, two `0024`
  migrations in `profiles`, signup not saving the new fields, old terms link.
- **Status:** the branch `registration-changes-after-refresh` already contained the fixes for the settings, `is_bot` and the
  sign-up form fields; the remaining ones are entries 2-5.

### 2. Merge migration `profiles/0026`
- **Files:** `src/apps/profiles/migrations/0026_merge_registration_and_upstream.py` (new)
- **What:** joins `0025_customgroup_is_selectable_by_participant` (upstream) and `0025_merge_20260922_1002` (already applied on
  the owner's deployment). `0025_merge_20260922_1002` was deliberately NOT edited (changing the dependencies of an applied
  migration raises `InconsistentMigrationHistory`).
- **Why:** without it `migrate` stops with "Conflicting migrations detected" and the `django` container cannot start.
- **Checked:** dependency graph read by script (single leaf) and `makemigrations --check` reported no changes (local SQLite).

### 3. `TASK9_COMPETITION_IDS` from the environment
- **Files:** `src/settings/base.py`
- **What:** comma-separated env var `TASK9_COMPETITION_IDS`, default `3,4,5,6,7,8,9,10,11,12,13,14` (same as before).
- **Why:** the ids were hard-coded; the default keeps current behaviour.

### 4. Sign-up page
- **Files:** `src/templates/registration/signup.html`
- **What:** terms link points back to Codabench `PRIVACY.md` (it had been reverted to the old codalab-competitions wiki);
  fixed a mis-indented `<div>`.

### 5. Caddy MinIO proxy
- **Files:** `Caddyfile`
- **What:** `reverse_proxy @min_bucket minio:{$MINIO_PORT}` -> `minio:9000`.
- **Why:** `MINIO_PORT` is the host port; inside the Docker network MinIO always listens on 9000.

### 6. docker-compose
- **Files:** `docker-compose.yml`
- **What:** removed the obsolete `version: "2.4"` line and the commented-out command blocks; `site_worker` memory limit
  `512M` -> `5GB` (requested by the owner).
- **Not changed (decisions left to the owner):** `CODALAB_IGNORE_CLEANUP_STEP` in `compute_worker` is ignored by the code
  (the real variable is `COMPUTE_WORKER_NO_CLEANUP`); RabbitMQ and Redis are bound to 127.0.0.1 so a compute worker on
  another machine could not connect; port 443 is not published (TLS terminates at the university proxy).

### 7. Auto-enrollment: denied anywhere = denied everywhere
- **Files:** `src/apps/autoenroll/signals.py`, `src/apps/autoenroll/management/commands/sync_task9_participants.py`,
  `src/apps/autoenroll/management/__init__.py`, `src/apps/autoenroll/management/commands/__init__.py` (empty, new)
- **Rules (decided by the owner):**
  - APPROVED on any of the 12 competitions -> approved on all of them (as before).
  - DENIED on any -> denied on all of them (new). Denial wins: an approval saved while the user is denied elsewhere is
    stored as a denial.
  - An organizer can reverse a denial on purpose: changing a DENIED row to approved/pending lifts it on the whole group.
  - The old `RESPECT_DENIALS` setting was removed.
- **Sync command:** `sync_task9_participants [--dry-run]` applies the same rules to existing rows (denial wins, since it
  cannot know which decision came last). It must be run once after deploy (see section 4).
- **Hardening (entry 13):** only existing competitions are targeted; one failing sibling cannot fail the user's request.
- **Known, accepted by the owner:** the event is one-off, so no organizer carve-outs, no generalisation. Until the sync
  has run, a user denied before deploy who applies to an auto-approve sibling gets an "accepted" email but is stored as
  denied.

### 8. Mass email recipients
- **Files:** `src/apps/competitions/tasks.py`
- **What:** `batch_send_email` no longer emails participants with status `denied` or deleted accounts (pending/unknown
  still receive it, as before).

### 9. Comparison with AI4Media-Bench (no code change)
- **What:** their public repo is a single snapshot (2024-01-09) of Codabench from about November 2023 (Django 2.2) with
  about 50 changed files, mostly rebranding. Only genuinely new behaviour: a submission limit of 0 blocks submissions.
  Their email code has no functional improvement; they only moved the sender to a domain-authenticated address.

### 10. Organizers' "Email all participants" rewritten
- **Files:** `src/utils/email.py`, `src/apps/competitions/tasks.py`, `src/apps/api/views/competitions.py`,
  `documentation/docs/Organizers/Running_a_benchmark/Competition-Detail-Page.md`, `.env_sample`
- **What:**
  - The browser sends HTML rendered by the editor; the server accepts that or raw markdown (Python-Markdown leaves block
    HTML untouched), so the email is what the organizer saw in the preview.
  - Server-side sanitising with `nh3` (allow-list of formatting tags; scripts, styles, event handlers, `javascript:` links
    removed). Site-relative links/images become absolute URLs. A small `<style>` block gives tables, code and quotes a
    readable look in mail clients.
  - A real plain-text alternative is generated (before it was empty).
  - Recipients only in BCC, in batches of `EMAIL_BULK_BATCH_SIZE` (default 100); duplicates removed case-insensitively; a
    failing batch is logged and the others still go out; `EmailDeliveryError` is raised at the end if any failed.
  - A lone recipient (message to one participant) is addressed normally in `To`.
  - Both email endpoints (`email_all_participants`, participant `send_email`) return 400 for an empty message.
  - `batch_send_email` selects recipients with a single query (no prefetch).
  - Removed the unused `sanitize()` helper.
- **Verified:** an early probe showed Python-Markdown preserves editor-style HTML; the code was read back and reviewed
  by hand; the new tests were NOT run.
- **Open:** exact whitespace inside code blocks relies on Python-Markdown's raw-HTML handling (the test that covered it was
  deleted, entry 19).

### 11. Email settings parsing
- **Files:** `src/settings/base.py`, `.env_sample`
- **What:** `EMAIL_USE_TLS` is parsed as a boolean (the string `"False"` used to be truthy), `EMAIL_PORT` is an integer,
  new `EMAIL_BULK_BATCH_SIZE` (blank values fall back to defaults).
- **Reminder:** `settings.develop` defaults to the console email backend; real sending needs
  `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` in `.env`.

### 12. Pending-participants indicator
- **Files:** `src/apps/api/serializers/competitions.py`, `src/apps/api/views/competitions.py`,
  `src/static/riot/competitions/competition_list.tag`, `src/static/riot/competitions/detail/_header.tag`,
  `src/static/riot/competitions/detail/participant_manager.tag`
- **What:**
  - The organizer's list ("Organizing" tab) shows an orange "N pending" badge per competition; clicking it opens the
    competition with the participants window filtered to Pending.
  - The "Participants" button on the competition page shows the count; it updates after an approve/deny.
  - Counts only pending requests of non-deleted accounts. The API only returns the count to organizers: it is annotated
    in the `mine=true` list (subquery, no extra query per row) and is an admin-only field on the competition detail.
- **Needs:** front-end rebuild (the `builder` container compiles the `.tag` files).

### 13. Fixes from the code review (`/code-review`, high effort, 10 findings)
- **Fixed:**
  - Fan-out and sync only target competitions that exist (a missing id crashed the user's request); one failing sibling
    is logged and skipped. (`signals.py`, `sync_task9_participants.py`)
  - The "is the user an admin of this competition" check was evaluated three times per detail request; now once.
    (`api/serializers/competitions.py`)
- **Not applied (owner's decision or out of scope):** accepted-email-before-denial gap (handled by running the sync);
  denial overwriting organizers' own rows (ignored: one-off event); non-string `message` crashing the email task; fan-out
  cost of about 11 competition saves; sync command doing one query per row; duplicate Task 9 test override in
  `settings/test.py` and `src/conftest.py`; tests not collected by pytest (`autoenroll/tests.py`).

### 14. No visible `To` on mass emails
- **Files:** `src/utils/email.py`
- **What:** `to=[from_email]` removed. Django delivers to `To` as well as BCC, so every batch was also delivered to the
  sender address (bounces or a flooded mailbox). Bulk messages now have only BCC recipients, as the original code did.
- **Why:** the university SMTP has restrictions; the original code (BCC only) was known to work.

### 15. Leaderboard: Team Name and Username
- **Files:** `src/apps/api/serializers/submission_leaderboard.py`, `src/apps/api/views/competitions.py`,
  `src/static/riot/competitions/detail/leaderboards.tag`
- **What (decisions by the owner):**
  - Column 1 "Team Name" (`N/A` when the user has none), column 2 "Username" (the existing display-name-or-username value,
    linked to the profile). Header column span adjusted.
  - Submissions made as an organization are shown like any other row (the organization name is no longer displayed; it is
    still present in the API data).
  - CSV, ZIP and JSON exports keep the username and gain a "Team Name" column.
  - Rows are not merged per team; sign-up fields are unchanged.
  - No first/last name on the leaderboard (leaderboards are public, profiles need a login).
- **Needs:** front-end rebuild.

### 16. Account deletion clears team name and affiliation
- **Files:** `src/apps/profiles/models.py`
- **What:** the anonymisation on account deletion now also empties `team_name` and `affiliation` (they would otherwise
  stay on the public leaderboard).

### 17. Other users' emails no longer sent to the browser
- **Files:** `src/apps/profiles/views.py`
- **What:**
  - Public profile page (`/profiles/user/<username>/`): the page embeds the user's whole record as JSON; the email and
    the three notification settings are now removed unless the viewer is that user or staff/superuser. The page looks the
    same (it already hid the email for other users).
  - Settings page (`/accounts/user/<username>/account/`) and notifications page: any logged-in user could open them for
    any username and receive that user's data; they now return 404 unless the viewer is that user or a superuser (same
    rule the edit page already used).
- **Not changed:** `SimpleUserSerializer` also contains `email`; it is not used by any view found in this review.

### 18. Tests and `src/conftest.py`
- **Files (new, untracked):** `src/apps/autoenroll/tests.py`, `src/apps/api/tests/test_pending_participants.py`,
  `src/conftest.py`, plus a Task 9 override in `src/settings/test.py`. (`test_mass_email.py` was written too and later
  deleted, see entry 19.)
- **Status:** written but **not run** (the owner does not run tests here and prefers to delete them rather than maintain
  them). `src/conftest.py` switches the Task 9 group off for the whole test suite so factory data cannot trigger it;
  `autoenroll/tests.py` would not be collected by pytest. Delete or fix when the owner decides.
- **Earlier local runs (not part of the repo):** 12 existing participant/email tests and the first 16 autoenroll tests
  passed on a local SQLite + S3-mock setup; a wider run showed 48 failures that come from the setup (no Redis/RabbitMQ,
  SQLite lacks `DISTINCT ON`) and could not be attributed further.

### 19. Mass-email test file deleted
- **Files:** `src/apps/competitions/tests/test_mass_email.py` (deleted; it was new and untracked, so it is not in git history)
- **Why:** requested by the owner ("remove the test for emails"); the file also still expected the pre-entry-14 `To`
  behaviour. The tracked upstream `src/apps/competitions/tests/test_emails.py` was NOT touched.
- **Effect:** the mass-email code of entries 10 and 14 now has no tests; entry 10's "covered by a test" notes no longer apply.

### 20. Submission upload: drag & drop zone, zip checks, explicit Submit button
- **Files:** `src/static/riot/forms/input-file.tag`, `src/static/riot/competitions/detail/submission_upload.tag`,
  `src/apps/api/serializers/datasets.py`
- **What (decisions by the owner):**
  - `input-file` has a new optional mode (`droppable="true"`): a drop zone you can also click to browse. The default mode
    used by every other form (competition bundle upload, datasets, resources, tasks) is unchanged.
  - The chosen file is checked immediately, for both drop and browse: exactly one file, not a folder, not empty, name ends
    in `.zip` (any letter case) and the first bytes are a zip signature (catches a renamed non-zip). Any problem shows a red
    message under the zone and a toast, and the file is not kept. File name rules are NOT checked (only the extension).
  - Choosing or dropping a file no longer starts the submission. The file is shown (name, size, Remove button) and a
    **Submit** button in the form starts the upload; it is disabled without a valid file and while an upload runs. Phase
    and limit checks (`can_make_submissions`) run when Submit is clicked, as before.
  - Server: the `.zip` extension check in `DataSerializer.validate` is now case-insensitive (`RESULTS.ZIP` was rejected).
    The duplicate-name check and everything else are unchanged. The compute worker reads the zip with `ZipFile` and does
    not depend on the file name.
- **Not changed:** the competition bundle upload (`competitions/upload.tag`) still uploads as soon as a file is picked.
- **Needs:** front-end rebuild; participants only get it immediately once the cache-busting `ASSET_VERSION` change is
  made (proposed, not yet applied).
- **Verified:** read back and reviewed by hand only. Not run in a browser. Manual test list: valid zip, `.ZIP`, `.txt`,
  a `.txt` renamed to `.zip`, two files, a folder, remove then re-pick the same file, Submit while the phase is closed.

### 21. Static file cache busting (`ASSET_VERSION`)
- **Files:** `src/utils/static_storage.py` (new), `src/settings/base.py`, `Caddyfile`, `.env_sample`
- **Why:** after the update the browser kept an old `init.js` (calling `particlesJS`) with the new pages, which broke
  menus and dropdowns until the cache was emptied. Participants who visited the old version would hit the same thing.
- **What:**
  - `VersionedStaticFilesStorage` appends `?v=<ASSET_VERSION>` to every `{% static %}` URL. Files keep their names, so
    `collectstatic` and Caddy are unaffected. `ASSET_VERSION` comes from `.env` (default `1`).
  - `base.py` uses it as the `staticfiles` storage. `settings/production.py` (whitenoise, hashed names) and
    `settings/test.py` keep their own storage and are not affected.
  - Caddy sends `Cache-Control: no-cache` for `/static/*`, so browsers recheck before reusing a file (a 304 when
    unchanged). This also covers files referenced from CSS or built in JavaScript, which get no `?v=`.
- **Operation:** change `ASSET_VERSION` in `.env` at every deploy and recreate the django container
  (`docker compose up -d`; a plain restart does not re-read `.env`). The first deploy changes every URL already
  (default `1`, no `?v=` before), so everyone refetches once.
- **Not versioned:** images and fonts referenced from inside CSS files, and URLs built in JavaScript from `STATIC_URL`.
- **Verified:** read back by hand only. After deploy, view the page source: scripts should end in `?v=<value>`.

### 22. Failed submission 2: root cause and two fixes
- **Investigation (no change):** submission 2 failed with a tooltip full of `HTTPSConnectionPool ... too many 500 error
  responses` and no logs. The stored traceback showed the worker failing in `prepare()` -> `_get_container_image` (Docker
  image pull) and then failing again while reporting that failure to `PATCH /api/submissions/2/`. A manual
  `docker pull codalab/codalab-legacy:py37` on the server failed with `no space left on device`: **the server disk is
  full**. The pull filled it, Postgres could no longer write, so the worker's status updates returned 500.
- **Files:** `compute_worker/compute_worker.py`, `src/apps/api/views/submissions.py`
- **Worker:** new `_report_error()` sends the error to the website but never lets a failure of that call replace the real
  error (it only logs it); used for both Docker pull failure branches and the "image not present locally" branch, whose
  report sat after a `raise` and was never sent. A pull failure caused by a full disk now says so in the message
  ("Pull for <image> failed (the compute worker has no free disk space left)!"). The error text is sent as a string.
- **Server:** for `Docker_Image_Pull_Fail` / `Execution_Time_Limit_Exceeded` reports, the log
  (`prediction_ingestion_stderr` or `scoring_stderr`) is now created when it does not exist yet (before, the message was
  dropped with "SubmissionDetails object not found", which is why such failures showed no logs). Problems while writing
  the log are logged and can no longer turn the status update into a 500.
- **Not done (proposed):** the error panel, failure categories and a `failure_type` field (see the discussion of
  platform / submission / program / scoring failures).
- **Needs:** `./compute_worker` is mounted into the worker container, so `docker compose restart compute_worker` is enough
  (no image rebuild); the django container reloads by itself. **Free disk space first**, otherwise the same failure
  repeats.
- **Verified:** compiled and read back only.

### 23. Failed submissions: failure types, clear error display, faster stuck-submission cleanup
- **Files:** `src/apps/competitions/models.py`, `src/apps/competitions/migrations/0066_submission_failure_type.py` (new),
  `src/apps/api/serializers/submissions.py`, `src/apps/competitions/tasks.py`, `src/settings/base.py`, `.env_sample`,
  `compute_worker/compute_worker.py`, `src/static/riot/competitions/detail/submission_manager.tag`,
  `src/static/riot/competitions/detail/submission_modal.tag`
- **Failure types** (new nullable field `Submission.failure_type`, migration 0066): `platform` (server / compute worker
  problem, not the submission's fault), `submission` (unusable zip, missing metadata/files), `program` (a program
  failed), `scoring` (scoring program could not evaluate), `time_limit`. Each has a title and a plain explanation
  (`Submission.FAILURE_SUMMARIES`); old failures without a type show a generic "Failed".
- **Worker:** `SubmissionException` can carry a type; it is set where the worker fails (API/storage/Docker/container
  problems = platform, unreadable zip or metadata = submission before scoring and scoring after it, missing or
  undecodable scores file and non-zero scoring exit = scoring, time limit = time_limit). The generic "anything else"
  path is a platform failure. `_update_status()` sends the type with the Failed status. The type is cleared by the
  server whenever a non-failed status is reported (a submission started again).
- **Server:** `SubmissionSerializer` returns `failure_type`, `failure_title`, `failure_message`. For a FAILED submission
  `status_details` (tracebacks, host names, paths) is now only returned to organizers; everyone else gets the plain
  explanation (Human-in-the-Loop messages stay visible to all). The organizer check is cached per competition so a long
  list does not cost a query per row.
- **Page:** a failed row shows a coloured label with the type (explanation on hover) instead of the "?" tooltip;
  clicking the row opens the submission window on a new **ERROR** tab (for failed submissions only) with the title, the
  explanation, why there may be no logs, and for organizers the technical details with a Copy button. The logs tab says
  why it is empty instead of a bare "No logs available".
- **Stuck submissions (configurable):** a submission still `Running` more than `SUBMISSION_STALE_GRACE_MINUTES` (default
  **30**, was 24 hours) after the execution time limit of its phase is failed as a platform error with an explanation;
  the check runs every `SUBMISSION_CLEANUP_INTERVAL_SECONDS` (default **300**, was 3600). Only `Running` submissions are
  covered, as before; ones stuck in other states (for example Preparing or Scoring) are not.
- **Needs:** migration 0066 (runs when the django container starts), `docker compose restart compute_worker`, front-end
  rebuild, `ASSET_VERSION` bump. Optional `.env`: the two settings above.
- **Not done (proposed):** platform failures not counting against the submission limits, automatic re-queue, notifying
  organizers. Free disk space on the server is the real fix for submission 2.
- **Verified:** Python compiled, tag markup checked for balance, code read back. Not run or tested in a browser.

### 24. Backup script and the full-disk problem
- **Investigation (no change):** the server disk is **16 GB** (13 GB used, 2.5 GB free). Docker uses about 5 GB, the project
  1.2 GB (`var/minio` 604 MB, `var/log` 268 MB, `var/postgres` 71 MB), `/var/backups/codabench` 1.2 GB; the rest was not
  measured yet. `docker builder prune` freed only 43 MB. `codalab/codalab-legacy:py37` (used by all 13 competitions) is
  not present yet and needs several GB, so its pull fails again unless space is freed. `/home/didimitrov/codabench` no
  longer exists, the project is `codabench-su`.
- **Files:** `codabench-backup.sh`
- **What (decided by the owner: "smaller backup retention"):**
  - The default project folder is now `/home/didimitrov/codabench-su`; every setting can be overridden from the environment.
  - The database dump is still taken on every run (it is about 120 KB) and kept 30 days (`RETENTION_DAYS_DB`).
  - The MinIO archive (as large as `var/minio`, about 600 MB) is taken once a week (Sunday, `MINIO_BACKUP_DAY`) or when no
    archive exists, and only the newest 2 are kept (`MINIO_KEEP`). `FORCE_MINIO_BACKUP=1` takes it on demand.
  - Before archiving it checks the free space (the archive size plus `MIN_FREE_MB`, default 2048); if there is not enough
    it skips the archive with a WARNING and ends with exit code 3, instead of filling the disk.
  - Temporary files are removed when a run fails, and leftover `*.tmp` files older than a day are removed (the 33
    empty files from the broken nightly runs).
- **Not done:** a disk-usage alert (the owner does not want it), a bigger disk (the owner is not sure it is possible),
  smaller Docker image for the competitions, Caddy access-log size limit (proposed: `roll_size` is 5000 MiB).
- **Needs:** copy the script to the server (`/usr/local/bin/codabench-backup`) and use the crontab line from its header.
- **Verified:** read back by hand only, not run.

### 25. Caddy access log size
- **Files:** `Caddyfile`
- **What:** the access log (`var/log/caddy/caddyaccess.log` on the host) was rotated at 5000 MiB per file with Caddy's default of 10
  files kept, which could fill a 16 GB disk. It now rotates at **100 MiB** (the owner chose 100 rather than 20) and keeps
  the **5** newest rotated files (about 600 MiB at most).
- **Needs:** `docker compose restart caddy` (the Caddyfile is mounted into the container). The existing 268 MiB file is
  above the new limit, so it is rotated on the next write.
- **Verified:** read back only.

---

## 3. Things that were looked at and deliberately NOT changed
- Compose: dead `CODALAB_IGNORE_CLEANUP_STEP`, RabbitMQ/Redis bound to localhost, no port 443.
- `base_email.html` still hotlinks the Codabench logo and says "Codabench Team".
- Unused template `emails/participation/participant/participation_organizer_direct_email.*`.
- Denied participants keep their existing submissions on the leaderboard.
- Denial fan-out also applies to users who organize one of the 12 competitions (accepted: one-off event).
- Public participant counters include denied rows created by the fan-out.

## 4. Deploy checklist (as agreed; also stored in Claude's memory)
1. Commit the changes on `registration-changes-after-refresh`.
2. Rebuild the front-end bundle (`builder` container compiles the Riot `.tag` files).
3. `.env`: real SMTP (`EMAIL_BACKEND=...smtp.EmailBackend`, host, port, user, password, `EMAIL_USE_TLS`), `DEFAULT_FROM_EMAIL`
   and `SERVER_EMAIL` on an address the university SMTP accepts; optionally lower `EMAIL_BULK_BATCH_SIZE`.
4. Migrations (`profiles/0026`) run on container start.
4a. Optional `.env`: `SUBMISSION_STALE_GRACE_MINUTES` (default 30) and `SUBMISSION_CLEANUP_INTERVAL_SECONDS` (default 300).
   After the update also run `docker compose restart compute_worker` (the worker code changed).
4b. Set `ASSET_VERSION` in `.env` (any new value at every deploy, e.g. the date) and recreate with `docker compose up -d`,
   so participants' browsers do not keep old JavaScript/CSS.
5. **Run `sync_task9_participants --dry-run`, then for real, once right after deploy.**
6. Check `TASK9_COMPETITION_IDS` matches the real competition ids on the server.
7. Users without a team name show `N/A` on the leaderboard; tell them to fill it in on their profile.

## 5. Outside the repository (no effect on the code)
- Claude's memory files (`~/.claude/projects/D--Codabench-codabench-su/memory/`): deploy checklist reminder, Task 9
  one-time-event context, and this audit-log habit.
- Scratch files only (temporary Python environment, S3 mock, a read-only clone of AI4Media-Bench, extracts of upstream
  used as test baselines) were kept in the session's scratch folder, not in the repository.
