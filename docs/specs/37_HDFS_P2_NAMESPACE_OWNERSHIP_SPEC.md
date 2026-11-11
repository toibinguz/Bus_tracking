# SPEC-37: HDFS P2 namespace ownership and provisioning

**Status:** implementation directive after SPEC-36.  
**Owner:** `@architect`  
**Scope:** HDFS permission boundary for P2 Spark Bronze-to-Silver/Gold.

## 1. Observed blocker

P2 reads real `hdfs://` Bronze and reaches the accepted projection, then fails:

```text
AccessControlException: user=spark ... WRITE /bus-eta/v1/silver
```

The namespace is root-created. The private ingest runner writes as WebHDFS
user `root`; Spark containers run as HDFS user `spark`. Running Spark as root,
turning off `dfs.permissions`, or using a world-writable namespace is forbidden.

## 2. Decision

Provision these exact roots before P2 input staging or submit:

| Root | Writer | Owner and mode |
| --- | --- | --- |
| `/bus-eta/v1/bronze` | `root` ingest | `root:supergroup`, `755` |
| `/bus-eta/v1/reference` | `root` provisioner | `root:supergroup`, `755` |
| `/bus-eta/v1/silver` | `spark` P2 | `spark:supergroup`, `755` |
| `/bus-eta/v1/gold` | `spark` P2 | `spark:supergroup`, `755` |
| `/bus-eta/v1/_checkpoints/bronze_to_silver` | `spark` P2 | `spark:supergroup`, `755` |
| `/bus-eta/v1/_published/bronze_to_silver` | `spark` P2 | `spark:supergroup`, `755` |

`/bus-eta/v1`, `_checkpoints`, and `_published` are root-owned `755` parents
for traversal. The named P2 children belong to `spark`. `755` permits Spark to
read root-created Bronze/reference data but does not grant write to others.
Do not use `777`, a recursive ownership change of `/bus-eta/v1`, root
`spark-submit`, or a local-output fallback.

## 3. Provisioning

Add one small versioned command/script, run via `docker compose exec namenode`
after NameNode health and before P2 staging. It must make only these parents
and roots with `hdfs dfs -mkdir -p`, explicitly apply `-chown` and `-chmod`,
then print `hdfs dfs -stat '%u:%g %a %n'` for every table row.

It may reapply this policy after a deliberate demo reset. It must not delete
outputs, repair malformed checkpoints, or recursively chown arbitrary Bronze
data. Ingest remains `HDFS_WEBHDFS_USER=root` and writes Bronze only; master,
workers, and submitter remain `USER spark` from SPEC-36 and use
`hdfs://namenode:8020`.

## 4. Acceptance evidence

Store command, exit status, stdout/stderr, and `-stat` output in timestamped
P2 evidence.

| ID | Pass condition |
| --- | --- |
| PERM-01 | Provisioning proves each owner/mode in Section 2. |
| PERM-02 | `id -un` in master, worker, submitter is `spark`; submitter reads staged Bronze and reference. |
| PERM-03 | `spark` writes, reads, then deletes only its own unique temporary child below every Spark-owned root. |
| PERM-04 | `spark` cannot create a temporary child below Bronze or reference; non-zero output is saved. |
| PERM-05 | P2 writes Silver, Gold, checkpoint, and publish manifest without root elevation, all on `hdfs://` paths. |

PERM-03 is a permission probe only; SPEC-35 P2-01 through P2-07 remain
mandatory. This adds no Kerberos, ACLs, Ranger, impersonation, or general
access-control layer. A conflicting owner/mode must fail visibly, never cause
root escalation or a local success path.

## 5. Resume

1. Implement provisioning and capture PERM-01--04.
2. Retain SPEC-36 image/projection-import evidence.
3. Re-run P2 for PERM-05 and SPEC-35 P2-01--P2-07.
4. Request white-box and independent black-box P2 audits.
