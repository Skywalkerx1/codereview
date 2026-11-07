# CodeReview — sandbox threat model (Epic C5)

This document states what the CodeReview execution sandbox
does and does not protect against. It is the written threat
model ticket C5's acceptance calls for; the mechanism summary
also lives in `src/codereview/evidence.py`'s module docstring
and the README's sandbox paragraph. Where this document and
the code disagree, the code is what runs — file an issue.

## What runs in the sandbox, and why it is untrusted

One executor — `evidence._execute` — runs every command whose
*code* comes from the tree under review:

- **Evidence commands and adapters** (Epic C1/C2): the
  project's configured tests, lint, and security scanners,
  executed against the change being reviewed.
- **Builder-claim re-runs** (Epic C4): commands a builder's
  work report claims were run, re-run to check the claim.
- **Lifecycle hooks** (Epic L3): project-declared commands
  from `.codereview.toml`, run through the evidence runner
  verbatim — there is no second executor.

The *choice* of commands comes from the operator (a config
file or policy the operator points the CLI at — the same
trust level as `--test-command`). The *code those commands
execute* is the reviewed tree's code, and everywhere else in
this product that tree is untrusted data. The sandbox treats
it that way here too.

## Assets

1. The operator's credentials: provider API keys, tokens,
   SSH agent, credential files (`~/.gitconfig`, `~/.netrc`,
   cloud SDK configs).
2. The checkout the operator is about to merge — evidence
   must not be able to rewrite the thing it attests to.
3. The operator's machine: CPU, memory, disk, process table,
   and the gate process itself.
4. The integrity of the run record: what the record says
   happened (isolation mode, limits, output) must be what
   actually happened.

## Controls

| Control | Mechanism | Verified by |
|---|---|---|
| Throwaway working copy | `tempfile.mkdtemp` (mode 0700) copy of the tree, `.git` excluded, symlinks copied as links and never dereferenced during the copy; the copy is the child's cwd, never the reviewed tree | `test_evidence`: copy-not-source, `.git` exclusion |
| Cleanup on every exit path | `try/finally` + `shutil.rmtree` in both `collect()` and `verify_claims()` — normal, failure, and timeout-kill paths alike | `test_sandbox_c5.CleanupPinTests` (normal / timeout-kill / copy-failure / claims) |
| No secrets in the child | Environment built from a positive allow-list (`PATH`, locale, terminal basics). Provider keys, tokens, `SSH_AUTH_SOCK` and every other operator variable never cross. `HOME`/`TMPDIR` point inside the sandbox, so credential files are unreachable through them. There is deliberately no option to run with the operator's environment | `test_evidence` marker test; `test_sandbox_c5.EnvAllowListPinTests` (key-shaped names, agent socket); `test_hooks` marker test |
| No network by default | Proxy variables are stripped (most tooling egresses through them). Where Linux user+network namespaces work (`unshare -rn`, probed once per process), the child runs with no network at all. An item must opt in with `allow_network: true`; the opt-in re-admits proxy variables only, never keys | `test_sandbox_c5.NetworkEnforcementTests` (namespace is a different namespace; a connect attempt fails inside it); honest-mode tests in `test_evidence` |
| Honest isolation reporting | The record states the mode that actually applied per item — `namespace`, `env-only`, or `allowed` — never claiming isolation that did not happen | `test_evidence`: honest-mode + opt-in tests |
| Wall-clock bound | Per-item timeout; expiry kills the whole process group (`start_new_session` + `killpg`), so grandchildren in the group die too | `test_evidence` timeout test; `test_sandbox_c5` cleanup-after-kill |
| CPU bound | `RLIMIT_CPU` = timeout + 5 s, set in the child via `preexec_fn` | `test_sandbox_c5.ResourceLimitPinTests` (child reports its own limits) |
| Per-file size bound | `RLIMIT_FSIZE` = 256 MiB per file | same pin as above |
| Captured-output bound | Each stream (stdout, stderr) is drained by a reader thread under an 8 MiB cap: past the cap the parent keeps draining and discarding, so the child never blocks on a full pipe and the gate process's memory stays bounded. The record's hash and redacted tail cover the capped bytes; a truncation marker in the output says when the cap bit. On the timeout path the drainers are joined after the kill (a bounded settle), so the sinks are final before they are read; if a detached process still holds a pipe open after the settle, the capture is marked incomplete in the output — partial output is never presented as whole | `test_sandbox_c5.OutputCapTests` (cap + marker, drained-not-blocked, byte-identical under the cap, incomplete-capture marker) |
| Output is evidence, not truth | Full output is never stored: its sha256 plus a tail (4 000 chars) passed through the review path's `redact_secrets`, so a scanner that prints the secret it found does not smuggle it into the record | `test_evidence` hash tests |
| Supervised waits only | Every `Popen` in `src/` pairs with `communicate(timeout=…)`, the seat wait, or the sandbox's `_supervise_sandbox_run` — an AST guard keeps it so | `test_v093_fixes.SubprocessTimeoutGuardTests` |

## Trust boundaries — what is NOT in this sandbox

- **Agent seats** run the operator's own installed reviewer
  CLIs. Those are operator-trusted programs, not tree code;
  they run under the providers module's own environment
  discipline, not this sandbox.
- **`--test-command` and workflow builder/test commands**
  are operator-supplied shell strings executed in the
  operator's checkout with the operator's environment — the
  documented trust level of a CI config the operator wrote.
  For an untrusted tree, the evidence runner is the confined
  path; the plain test-command path is a convenience for your
  own code.
- **Tech Lead probes** (`probe.py`) execute reviewer-requested
  checks in a parallel, smaller sandbox of their own: temp
  copy, a tighter env allow-list, a timeout whose expiry
  kills the whole process group (`start_new_session` +
  `killpg`), rlimits set in the child (`RLIMIT_CPU` =
  timeout + 5 s, `RLIMIT_AS` 2 GiB, `RLIMIT_FSIZE` 256 MiB,
  `RLIMIT_NOFILE` 1024, core dumps off — the C5 hardening of
  2026-11-06), drained output caps, and an `unshare -n`
  probe with honest fallback. Its confinement is per-probe
  and its reporting is its own; do not assume the evidence
  guarantees apply there verbatim.
- The MCP server's `run_gate` calls the CLI's own `main()`,
  so MCP-served runs get exactly this sandbox — and exactly
  its limits below.
- **The project policy may come from the reviewed tree.**
  The review command discovers `.codereview.toml` at the
  reviewed repository's root — a file the tree's author
  controls, like the code under review itself (P3-01; owner
  ruling 2026-11-06, option 1). A discovered policy is
  therefore honoured only where it can *strengthen* a review:
  panel minimums, evidence requirements, path `require_*`
  rules, the strict waiver values, `[diversity]
  enforce = "block"`, a `"strict"` gate profile. What it may
  not do is execute code or weaken the gate: its `[hooks]`
  commands and timeout, a weaker-than-strict `[gate]`
  profile, `[[paths]] enforce = "advisory"`, the waiver
  leniency values, `[diversity] enforce = "degrade"` and
  `exclude_builder_family`, and `[risk]` tiering with its
  seat selection are dropped back to defaults at load, before
  anything applies the policy — the dropped keys are named in
  the record (`policy.ignored_keys`), counted in the CLI's
  stderr warning, and returned to MCP clients
  (`policy_ignored_keys`). (Why hooks matter here: they run
  through this sandbox, so a planted hook's confinement is
  exactly the residual-1 limit below — absolute-path writes
  at the operator's uid. The restriction removes the tree's
  ability to fire one at all.) An operator who trusts the
  repository's policy opts in explicitly: `--policy PATH`
  (operator-named policies are always honoured in full) or
  `--trust-repo-policy` for the discovered file. The keys a
  discovered policy may not set are enumerated in one place:
  `policy.DISCOVERED_POLICY_RESTRICTED_KEYS`.

## Residual risks — stated plainly

The sandbox is confinement against accidents and casual
hostility, plus strict secret hygiene. It is **not a jail**.
For a genuinely hostile tree, run the whole CLI inside a VM
or a container.

1. **No filesystem isolation.** The copy confines *relative*
   side effects; nothing stops the child from using absolute
   paths. Untrusted code can read any file the operator can
   read (including, by absolute path, the credential files
   the environment hygiene keeps out of `HOME`-relative
   reach) and can write to any operator-writable path. Tree
   symlinks are copied as links and may be followed at run
   time. Redaction bounds what reaches the *record*; it does
   not stop code writing what it read to an absolute path.
   This is the honest limit of "never run untrusted PR code
   with secrets": secrets are never *provided* to the child —
   its environment, arguments, and home contain none — but
   the child shares the operator's filesystem view.
2. **Memory is not capped.** A memory bomb can grow until
   the wall-clock/CPU bounds end the run, and can pressure
   the host meanwhile. An `RLIMIT_AS` cap is deliberately
   *not* set: virtual-address reservations of legitimate
   toolchains exceed any safe blanket value (Node/V8 reserves
   gigabytes-to-terabytes of address space; the JVM likewise)
   — `npm` is a built-in evidence adapter — and
   `RLIMIT_DATA` does not bound mmap'd heaps. A cap that
   breaks configured workloads would be theatre, not safety.
3. **No aggregate disk quota.** The per-file cap is 256 MiB,
   but file *count* is unbounded: a child can fill the
   sandbox volume with many files before the timeout ends
   the run. The copy is deleted afterwards; a full disk
   during the run is the operator's problem to notice.
4. **No process-count cap.** `RLIMIT_NPROC` counts per real
   user id on Linux, so a child-side value would either do
   nothing or break legitimate parallel test suites by
   counting the operator's unrelated processes. A fork bomb
   is bounded in *duration* (timeout + group kill), not in
   instantaneous process count.
5. **Detached processes escape the kill.** A child that
   double-forks or calls `setsid` leaves the process group
   and survives the timeout kill. It keeps the scrubbed
   environment and (in namespace mode) the absent network,
   and runs as the operator's uid until it exits or the
   operator kills it. If it holds an output pipe open past
   the post-kill settle, the run's captured output is
   partial — and is marked incomplete in the record, never
   presented as whole.
6. **`env-only` mode is not network isolation.** Where
   `unshare` is unavailable, "no network by default" means
   only that proxy variables are stripped; direct connections
   still work. The record says `env-only` so this is never
   mistaken for the namespace mode.
7. **`env-only` mode exposes sibling processes'
   environments.** Env-only mode has no pid namespace and
   no `/proc` masking: a sandboxed child running as the
   operator's uid can read `/proc/<pid>/environ` of any
   other dumpable same-uid process — the operator's shell,
   IDE, or another agent holding provider keys in its
   environment. The gate hardens its *own* process
   (`PR_SET_DUMPABLE, 0`, Phase 3 P3-04), but sibling
   processes are not ours to harden. So the "provider keys
   never reach an evidence process" property depends on
   namespace mode: in env-only mode it holds only for keys
   no same-uid process carries. **Env-only mode is not
   suitable for untrusted trees** on a machine where other
   processes hold credentials in their environment. When a
   run executes env-only while the gate process's own
   environment carries key-shaped variable names, the run
   warns on stderr and records the exposure in the
   evidence record.
8. **Namespace mode trades kernel surface for isolation.**
   `unshare -rn` runs the child as root inside its own user
   namespace (not host root). User namespaces are themselves
   kernel attack surface; on a host where that trade is
   unwanted, the honest fallback is `env-only` — which is
   risk 6, not a quiet upgrade.
9. **Cleanup is best-effort.** If the gate process itself is
   killed (`SIGKILL`, power loss), the `finally` never runs
   and a `codereview-evidence-*` / `codereview-claims-*`
   directory remains in the temp dir (the prefix makes it
   findable). A child that chmods the copy can defeat
   `rmtree`. Leftovers contain a copy of the reviewed tree
   and no secrets — the environment never had any.
10. **The copy is a snapshot.** Evidence attests to the tree
   as copied at run start. Another process mutating the
   source mid-run is out of scope.
11. **`PATH` is the operator's.** Tools are found through
    the operator's own `PATH` (allow-listed in). A poisoned
    operator `PATH` is the operator's configuration — the
    same trust as the commands themselves.
12. **Redaction is pattern-based.** `redact_secrets` covers
    the known key/token shapes; a novel secret format could
    evade a pattern. Exposure is bounded by design: only a
    4 000-char tail is ever stored.
13. **The record content hash is edit detection, not a
    signature.** `record-verify`'s `content_integrity` check
    recomputes a record's `content_sha256`: the content hash
    detects edits to any record that carries one, and
    verification fails closed when a hash-less record's
    surviving declarations (`version`,
    `provenance.generator_version`, `created_at`) show the
    stamping era or are garbled — inside the pre-machinery
    shape too, which reads legacy only when at least one
    declaration parses as pre-stamp and none is stamping-era
    or garbled. What the hash cannot do: there is no
    signature and no allowlist of genuine records, so a
    record whose declarations are rewritten to look
    pre-stamp — machinery sections removed, a consistent old
    `version` and `created_at` left standing — is
    indistinguishable from a genuine pre-stamp record, is
    accepted as a legacy record, and edits to it are not
    detected. That is the accepted limit of hash-based edit
    detection without signatures (tester items P6-12 /
    P6-12b, limit accepted at rerun 4, 2026-11-07).
