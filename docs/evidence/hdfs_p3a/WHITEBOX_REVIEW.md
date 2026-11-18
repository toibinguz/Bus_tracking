# P3A white-box review

Reviewed against the original bounded P3A acceptance plan (since retired during documentation cleanup) and the relevant domain/API contracts in spec 25. The checked scope remains documented in the P3A runbook and this evidence directory. This review covers code correctness; real-cluster acceptance also requires the retained integration results.

## Reviewed scope

- `history_query.py`, `hdfs_history_server.py`, HDFS Compose service and startup-script normalization.
- `hdfs_p3_stage_observed_snapshot.py`, `hdfs_p3_validate.py`.
- Focused request-validation, bracketing and split tests.

## Findings corrected during review

1. Evaluation originally calculated errors from in-memory medians. The implementation now writes Gold Parquet and reloads it before held-out predictions.
2. Missing station references originally dropped groups from evaluation. They now fail explicitly.
3. Empty training history originally left a report pointing at nonexistent Gold output. An explicit schema now permits an empty Gold Parquet result.
4. The snapshot manifest now records source selection, database origin, deterministic snapshot identifier, content hashes and canonical shape lengths. Input count, route and hashes are validated.
5. The server now limits analytical execution to one worker, bounds the wait to 20 seconds, cancels the Spark job group on timeout and configures finite HDFS connection retries/timeouts.

## Checks and conclusions

- Training observations enter the statistic only on the declared training date; held-out observations are strictly later. A focused test changes held-out durations and verifies training samples remain unchanged.
- Trip segmentation calls the existing segmenter. Bracketing/corridor functions are loaded from their existing AST bodies, avoiding a second algorithm and heavy optional imports. Adaptive long-segment and 150-second bracketing guards are exercised.
- The validator verifies HDFS input hashes/counts, materializes HDFS Silver Parquet, writes explicit-schema Gold and reads persisted Gold for predictions. Missing history yields null MAE and an inconclusive result, rather than zero error.
- Trip coverage includes valid held-out trips with no usable segment history. The reported trip error is explicitly a sum over valid bracketed adjacent spans, not a full terminal-to-terminal journey error.
- API values are validated and supplied as Spark column literals; only Silver paths reached through published checkpoint manifests are selected. Ambiguous published source-window versions fail closed.
- Focused command: `.venv/Scripts/python.exe -m pytest tests/test_hdfs_history_query.py tests/test_hdfs_p3_observations.py -q -p no:cacheprovider` — 10 passed.

## Explicit limits

- The richer accuracy dataset imports existing projected observations; this is not a fresh Bronze-to-projection parity proof. The P2 fixture remains the separate crawler/replay lineage check and is too small for accuracy.
- The bounded two-date median is not the full local day/hour baseline. The report explicitly records that reconciliation is absent; no parity or ML-quality claim is made.
- AST loading deliberately depends on the two named existing functions remaining self-contained. Renaming/changing their dependencies requires updating the adapter and rerunning tests.
- The 20-second analytical wait does not defend against a client that never finishes sending its HTTP headers; the service is a loopback student demo. Actual HDFS outage timing and recovery must be established by integration evidence.

No remaining blocking implementation finding in the reviewed code. Acceptance remains conditional on real-cluster API, publication, outage/recovery and observed-validation evidence.

## Final implementation recheck

The final API advertises `spark.driver.host=history-api` and binds the driver to `0.0.0.0`, allowing executors on the private network to reach the driver despite its second client network. Executor memory is explicitly 512 MiB; the 20-second analytical deadline remains in place. These changes do not broaden the loopback HTTP port exposure.

Reviewed `observed_validation.json`: 10,268 imported observed pings, 134 training trips and 4,103 training segment samples; 68 held-out trips and 1,724 held-out segments, all with historical estimates. Persisted Gold is reloaded before computing segment MAE 17.76428138386899 seconds and valid-span trip MAE 224.88370244117345 seconds. The report includes exact source hashes, split and HDFS paths, and a separate published four-ping diagnostic with zero valid trips and no accuracy claim. These figures describe this bounded sample only.

No new blocking code issue found in this final recheck. Actual dependency-outage/recovery evidence remains an integration acceptance item.
