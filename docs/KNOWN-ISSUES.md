# Known issues and acceptance scope

## B35-LIVE-01 — recovered error remains active

When an input changes during counting, the engine correctly rejects the unstable
measurement and publishes a verified retry. However, the old error event may
remain queued and be shown after recovery, asking a user to acknowledge a stale
fault. Observed twice during the designated real-chat trial. It remains unfixed
in this snapshot. Successful text/count checks do not close this issue.

A future fix must preserve real unresolved errors, per-policy budget tier
history, persistent deduplication, recovery/re-fault semantics and safe late
acknowledgements. Do not force complete=true or suppress all source-change errors.

## Evidence scope

Stages 1–3 and limited 3.5A have local acceptance records; those records and real
chat data stay private. Stage 3.5B has development/trial evidence, not final
independent release approval. Human 90/over acknowledgement evidence exists
locally. 50/75 cards have user-reported observation without target screenshots.

Exact budget equality, several live cancellation/exclusion/hidden-window cases,
additional real chats, zstd cold logs, actual DPI changes/login startup and target
context budget calibration were not all revalidated in this trial. No stage-4
preparation/migration development is implied by publishing this repository.
