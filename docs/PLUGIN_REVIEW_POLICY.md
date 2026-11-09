# Plugin validation and review policy

Community Lua handlers are **executable code from people we may not know**.
This policy says what happens before one is merged and what is still true
after it is.

## Standing position

1. **Every community plugin is untrusted until reviewed by reading it.**
   The sandbox raises the cost of a malicious plugin; it does not remove the
   need to read the diff.
2. **There is no plugin marketplace, no plugin registry, and no automatic
   download or execution of community code.** Plugins arrive as pull
   requests, are read by a human, and land in the tree. This is a permanent
   design choice, not a missing feature.
3. **Community plugins ship `enabled_by_default: false`.** An operator turns
   one on deliberately.
4. **Do not run unreviewed plugins on the machine hosting production Home
   Assistant.** UALC already separates the two; keep them separated.
5. **Level 1 profiles are reviewed as data, not sandboxed** — the validator
   proves they cannot express behaviour.

## Review checklist

### A. Licensing and provenance

- [ ] contribution is MIT-compatible
- [ ] `source_provenance` is filled in
- [ ] no code, comments or fixtures copied from a GPL (or other
      incompatible) project — if the knowledge came from one, the
      implementation is independent and says so
- [ ] no third-party Lua library vendored
- [ ] contributor has the right to contribute what they sent

### B. Privacy and sanitization

- [ ] no credentials anywhere: code, manifest, fixtures, README, PR text
- [ ] no full MAC addresses, real IPs, serial numbers, device IDs, account
      identifiers or SSIDs
- [ ] captures are sanitized and the contributor says what they removed
- [ ] no manufacturer account credentials were requested or supplied

### C. Manifest integrity

- [ ] `manifest.operations` matches what `describe` returns
- [ ] `permissions` are all `"none"`
- [ ] `authentication.plugin_receives_credentials` is `false`
- [ ] `min_ualc_api_version` present and satisfiable
- [ ] `limits` are at or below defaults, or an increase is justified
- [ ] `enabled_by_default` is `false`
- [ ] `firmware_ranges` are the ones actually tested — empty means unknown,
      not all

### D. Code review — what to actually look for

- [ ] handler returns a table and nothing else; no side effects at load time
- [ ] no attempt to reach `io`, `os.execute`, `require`, `load`, `debug`,
      `package`, or to reconstruct them from a metatable or upvalue
- [ ] no unbounded loop over attacker-controlled length; bounds are checked
      against the buffer before indexing
- [ ] no enormous allocation (`string.rep`, huge table pre-sizing)
- [ ] `partial` is set correctly — ask explicitly how full-state and delta
      frames are distinguished
- [ ] unmapped enum values are **reported** (`*_raw`), not coerced
- [ ] `ualc.fail` used with the right code; `MALFORMED_FRAME` and
      `UNSUPPORTED_PROTOCOL_VERSION` kept distinct
- [ ] `build_outbound` present **only** if the frame format, including any
      checksum, is verified — and the PR says how
- [ ] no claim over sibling models that were not tested
- [ ] obfuscated, minified or generated code: **decline**. A device decoder
      has no reason to be unreadable.

### E. Tests

- [ ] fixtures added and each case has a `rationale`
- [ ] fixtures labelled **synthetic** or **captured**
- [ ] `adapter_contract_test.py` passes
- [ ] `plugin_security_test.py` passes
- [ ] `profile_validation_test.py` passes
- [ ] pre-existing framework suites still pass
- [ ] awkward cases covered: delta frame, out-of-domain enum, truncated
      frame, unknown tag

### F. Honest status

- [ ] claimed `support_status.level` matches the evidence actually supplied
- [ ] `verification_source` is `community` for a community contribution
- [ ] offline tests are not described as hardware validation
- [ ] `CLOUD_INDEPENDENT` is not claimed on cloud-issued credentials
- [ ] `known_limitations` is populated and specific
- [ ] hardware test report attached if a hardware level is claimed

## What a merge means — and does not

A merge means: **the code was read and is safe to ship, the offline tests
pass, and the claimed support level is consistent with the evidence
provided.**

It does **not** mean a maintainer reproduced the result on hardware. We
usually cannot — that is the premise of the project. This is exactly why
`verification_source` exists, and why a community contribution stays
`community` until somebody else with the same appliance independently
confirms it, at which point it becomes `both`.

## Raising a plugin's limits

A reviewer may raise `limits` in the manifest if the appliance genuinely
needs it (a large frame, an expensive decode). A plugin can never raise its
own limits at runtime. Record the reason in the PR.

## Disabling and rollback

* An operator disables a plugin by setting it inactive; the host's `stop()`
  closes stdin, then terminates, then kills, and is idempotent — tested, with
  a no-orphan assertion (`plugin_security_test.py` group 10).
* A plugin that misbehaves in the field gets its `support_status` downgraded
  and `enabled_by_default` left false. We do not silently delete a
  contributor's work; we record what went wrong.
* If a merged plugin turns out to be malicious, it is removed outright, a
  `SECURITY.md` advisory is published, and the contributor is not accepted
  again.

## Reporting a problem with a plugin

Security issues: follow [`../SECURITY.md`](../SECURITY.md) — **do not** open
a public issue first. Everything else: open an issue naming the plugin `id`
and version.
