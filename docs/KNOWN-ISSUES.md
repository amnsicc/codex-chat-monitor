# Status and verification scope

## B35-LIVE-01

The recovered-error lifecycle repair was independently accepted locally on
2026-11-10. A fully verified recovery retires stale errors for that chat; partial
recovery preserves errors. Budget histories, other chats and stale acknowledgements
retain their existing behavior. Private evidence and receipts are not public.

## C1 offline material

The additive conservative entry point is a development candidate awaiting
independent acceptance. It can retain ambiguous text and projected JSON with
provenance while leaving strict-complete semantics intact. Some preserved JSON
contains timestamps, completion status, or empty lists. Their removal has only
been volume-modelled locally; no such filter is implemented here. Model reading
or distillation quality has not been measured against an original-chat baseline.

## Remaining scope

The target native tokenizer and effective budget are uncalibrated. GUI/worker
integration of conservative mode, full real-schema coverage, actual DPI/login
startup and model-based migration remain outside this publication. Offline zstd
support via an explicitly supplied existing Python 3.14 helper is not realtime
zstd monitoring support. Existing private real trials prove only their stated
limited scope, not general completeness or losslessness.
