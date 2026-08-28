# Task report: E87 Ghidra ARM64 documentation

**Date:** 2026-08-28
**Worktree:** `/home/jethac/.local/share/e87-dev/worktrees/e87-ghidra-docs`
**Branch/base:** `codex/e87-ghidra-docs` from `f7eb885117df2f86aaf895b8317f0301e29d15d4`

## Plan

1. Add a self-contained, hash-gated ARM64 ELF runbook.
2. Copy the canonical annotation script byte-for-byte and retain its refusal
   behavior for non-matching targets.
3. Add only a cross-link to the existing OTA research, without reconciling its
   stale findings.
4. Verify content, hashes, Markdown paths, whitespace, and repository state
   before committing.

## Implemented

- Added `docs/GHIDRA-ARM64-RUNBOOK.md`.
  - Covers the exact Windows input, target SHA-256, ELF import settings,
    Auto Analyze boundary, annotation invocation, address anchors, helper
    scripts, exports, and the GhidraMCP safety boundary.
  - Explicitly distinguishes the Android ELF from JieLi `pi32v2` `app.bin`
    analysis.
- Added `analysis/ghidra-scripts/AnnotateJlOtaAuth.java` as a direct copy of
  `C:\Users\jetha\Downloads\e87-reversing\tools\ghidra-scripts\AnnotateJlOtaAuth.java`.
- Added the requested narrow link from `docs/OTA-RESEARCH.md`; no OTA claims
  were rewritten.

## Integrity evidence

- Target SHA-256:
  `D65DD43FB8EB284B93FCBD85C7CE4E59168F3673E28C7637ED467667E4CC5C4B`
- Annotation-script SHA-256:
  `DFA250D0F4CF0A62E1C44C8F21856C2E82214EB39C7DC4976654D8DB4C2B77CA`
- The copied Java source checks `currentProgram.getExecutableSHA256()` and
  throws `Refusing to annotate an unexpected program` before annotation on a
  mismatch.

## Scope boundary

No Ghidra project was opened or changed. No Ghidra process, device, firmware,
Android project, or firmware S0 path was touched. The repository copy retains
only the canonical annotation script; the broader read-only helper set remains
at `B:\esp32\analysis\ghidra-scripts`.

## Verification record

- Source and repository annotation-script SHA-256 values matched exactly.
- Required runbook content, the target hash, safety whitelist, Java refusal
  guard, and OTA cross-link were checked as literals.
- `git diff --cached --check` completed without whitespace errors.
- The staged change set contains only the four files listed in this report.
