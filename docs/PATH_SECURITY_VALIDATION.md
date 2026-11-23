# Path Security Validation

Scope: V1 scanning + V2 organization engine. Host: Linux x86_64 dev container
(all automated checks) · Android 15/Termux: structural only, NOT TESTED on device.

## V1 controls verified
| # | Control | Implementation | Test evidence |
|---|---|---|---|
| 1 | Root canonicalized once; immutable per run | `safety.validate_scan_root` (realpath, is-dir, listable) | test_safety.py |
| 2 | String-prefix trap | containment via `safe_relpath` (path components, not `startswith`) | prefix-trap test |
| 3 | Symlinks never followed | lstat-based traversal; symlink recorded, never recursed; broken OK | symlink loop test; broken-symlink fixture |
| 4 | No path escape from traversal | every child re-checked via `safe_relpath`; failures → skip + issue | containment issue tests |
| 5 | Mount boundary | `st_dev` vs root device → skip, never descend | the two real-device mounts (see forensic audit); decision documented |
| 6 | Output-inside-root | exact output subtree excluded; recorded in exclusions_json | DB-inside-root test |
| 7 | Unrepresentable names | raw bytes preserved (surrogateescape); escaped only at render | Unicode/emoji/newline fixtures |
| 8 | Very long paths | no truncation; TEXT columns; tree escaping | deep-path fixture |
| 9 | Case/Unicode normalization | original name kept; `normalized_name` for sorting only | classifier/scanner fixtures |

## V2 additions (organization engine)
| # | Control | Implementation | Test evidence |
|---|---|---|---|
| 10 | Destination must stay in target root | `_dest_contained` realpath check at plan AND apply time | hostile stored path test |
| 11 | `..` segments in stored paths | segment sanitizer; realpath re-check; destination refused otherwise | `../../../etc/evil.txt` fixture |
| 12 | Symlink sources/destinations | refused at plan (`is_symlink`) and re-checked at apply (`islink`) | symlink plan test |
| 13 | Dest appears after planning | `lexists` re-check → op failed, never overwritten | sentinel test |
| 14 | Source path occupied at undo | undo refused (no overwrite of anything) | undo gate test |
| 15 | Cross-device move | copy→verify→remove; `os.renames` fallback verified | undo fallback path |

## TOCTOU & descriptor-relative operations
The dev host and Termux expose no `openat2`/`dirfd`-anchored helpers in the
Python stdlib, so containment is enforced by: (a) lstat (never following),
(b) realpath re-checks immediately before each sensitive operation, (c) fsync
+ post-copy verification before any source removal. Remaining residual risk:
a hostile directory swap between the re-check and the copy — an attacker with
write access to the user's storage could race any path-based API. This is
inherent to path-based I/O without kernel descriptors; mitigated by verifying
destination size/hash after copy (corruption can never masquerade as success)
and by never deleting unverified destinations. **Residual risk accepted and
documented; no user data can be destroyed by this race without the user's own
concurrent modification of their storage.**

## Explicitly not validated
- Mount-namespace attacks (no CAP_SYS_ADMIN needed; not mounted over paths).
- FUSE quirks on OEM ROMs (only behavior observed on the user's Android 15:
  two boundary mounts recorded and handled).
- Unicode normalization collisions across NFC/NFD on dest FS (target is same
  shared storage; behavior consistent with V1 scanner).
