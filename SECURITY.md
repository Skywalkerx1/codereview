# Security policy

CodeReview reads other people's code and holds provider API keys in
its environment, so a security problem in the tool itself matters.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Send it privately to: **<SECURITY-CONTACT-ADDRESS — TO BE SET BEFORE LAUNCH>**

Please include the version (`codereview --version`), what you did,
what you expected and what happened. A `codereview support-bundle`
is welcome (read it first; see below). We aim to acknowledge a
report within **<N — TO BE SET BEFORE LAUNCH>** working days.

## What counts

We use the project's severity scale: **S0** security problem, secret
exposure, data loss, or a wrong gate outcome; **S1** documented
behaviour broken, silent degradation, a hang or a crash; **S2/S3**
smaller issues and notes. Anything that lets reviewed code reach a
provider key, escape the evidence/probe sandbox beyond what
`THREAT-MODEL.md` already documents, or turn a BLOCKED into a PASS
is S0.

## Known and accepted limits

`THREAT-MODEL.md` lists the residual risks we already know about
(for example: the evidence and probe sandboxes do not isolate the
filesystem). A report that restates one of them is welcome but is
not a new vulnerability.

## Bug reports that are not security problems

See `CONTRIBUTING.md`.
