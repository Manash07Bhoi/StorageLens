# Security Policy

## Scope

Android Storage Audit is a **read-only** local tool. Its security posture is
its main feature: it never modifies, moves, renames or deletes source
files, and it never uses the network. Any behavior that violates either
property is a security bug.

## Reporting a vulnerability

Please report vulnerabilities by describing the **class of problem** (for
example: "a filename containing X breaks out of the HTML report") via a
private channel with the repository owner, or with a minimal, synthetic
reproduction — never with an actual scan report or database, since those
contain personal filenames.

Do not open a public issue containing:

- your real scan database, reports, exports or logs;
- personal filenames or paths;
- proof that requires publishing anyone's private data.

## Known limitations (documented honestly)

- The tool was verified on the development host (Linux x86_64);
  on-device Termux behavior is pending user validation.
- Static audit + test evidence only; no formal fuzzing of the report
  renderer in a hostile browser.
- The report is privacy-sensitive by design: filenames are personal data.
  Keep it local.

## Guarantees enforced by tests

- No network access (report assets are local; no remote URLs in output).
- No writes to the scanned tree (snapshot tests).
- Symlinks never followed.
- HTML/JSON/CSV/Markdown escaping verified for hostile filenames.
- SQL is fully parameterized; column interpolation is whitelist-bound.
