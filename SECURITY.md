# Security Notes

## This repository does not include any bootstrap/session-establishment code

Earlier development of the Roborock B01 adapter explored
`Python-roborock/local_roborock_server` PR #96, a draft pull request that
implements an HMAC+AES bootstrap handshake reverse-engineered from a
specific device's firmware. As of this writing, that PR is **paused by its
own author pending a responsible-disclosure window** on the mechanism it
implements.

This repository deliberately does **not** vendor, wrap, or otherwise
reproduce that code, and does not document its internal mechanics beyond
what's already public in the PR itself. The Roborock adapter in this repo
only contains the runtime status/command encode-decode path, which reuses
`python-roborock`'s own already-shipped, independently-published library —
not anything tied to the paused disclosure.

**If you need that functionality:** go read the upstream PR yourself and
form your own judgment about its disclosure status. Do not ask this
project's maintainer to provide a workaround, a mirror, or an explanation of
mechanics beyond what upstream has already made public.

## No real device credentials, captures, or network details

This repository was developed against a real device during research, but:
- no real device IP addresses, MAC addresses, or hostnames appear anywhere in this code — all example/test values are RFC 5737 reserved documentation ranges (`192.0.2.0/24`, `203.0.113.0/24`) or clearly-synthetic placeholders,
- no real packet captures are included,
- no real account credentials, tokens, or device secrets are included,
- no local infrastructure paths (file paths, internal hostnames) from the original development machine are included.

If you find anything that looks like it violates the above, please treat it
as a bug and report it privately to the maintainer before any public
disclosure.

## Reporting a vulnerability

This is a pre-alpha private repository with no public release yet. There is
no formal vulnerability-reporting process until a public v0.1.0 release
exists.

---

## Community plugins are untrusted code (added 08 11 2026)

UALC accepts **executable device handlers from contributors** (Level 2, Lua).
That is a deliberate feature — the project's premise is supporting appliances
the maintainers do not own — and it is treated as the security problem it is.

### Standing rules

1. **Community plugins are untrusted until a human has read them.** The
   sandbox raises the cost of a malicious plugin; it does not remove the need
   to review the diff.
2. **There is no plugin marketplace, no registry, and no automatic download
   or execution of community code.** Plugins arrive as pull requests. This is
   a permanent design choice.
3. **Community plugins ship `enabled_by_default: false`.**
4. **Do not run unreviewed plugins on the machine hosting production Home
   Assistant.** UALC's architecture already separates the two.
5. **No plugin ever receives a credential.** The wire contract has no field
   for one, and the host refuses to forward credential-shaped keys. Plugins
   cannot reach `credential_store.py`.
6. **Level-1 profiles are data, not code**, and are not sandboxed — the
   validator rejects executable expressions, credential-shaped keys, unknown
   codecs and unknown top-level keys.

### What is enforced, and where it is tested

Separate process · sandboxed `_ENV` with no `io`/`os.execute`/`os.getenv`/
`require`/`package`/`load`/`debug`/`dofile` · text-only chunk loading so
precompiled bytecode cannot be injected · POSIX rlimits for CPU, address
space, open files, `RLIMIT_FSIZE=0` and no fork · per-request wall-clock
timeout · response-size cap applied while reading · strict type validation of
every returned field · closed set of error codes · crash containment ·
idempotent shutdown with a no-orphan assertion.

Evidence: `testing_infra/plugin_security_test.py` — **26 checks**, plus **2
explicit skips** for restrictions we do **not** enforce. Full matrix:
[`docs/LUA_PLUGIN_ARCHITECTURE.md`](docs/LUA_PLUGIN_ARCHITECTURE.md) §6.

### What is NOT enforced

Stated plainly, because a security section that lists only its strengths is
worse than none:

* **No OS-level network isolation.** Lua's stdlib has no sockets and
  `package.loadlib` is removed, so a *pure-Lua* handler cannot open a
  connection — but that is a Lua-level argument, not a kernel-level one. There
  is no namespace, seccomp or firewall confinement. **For genuinely untrusted
  code, run the UALC host in a container or VM.**
* **rlimits are POSIX-only.** On Windows, timeouts and output caps still
  apply; rlimits do not.
* **`RLIMIT_AS` is best-effort** across platforms and allocators.
* **`RLIMIT_CPU` is coarse** (whole seconds) and is a backstop behind the
  host's wall-clock timeout.
* **Sandboxing does not bound correctness.** A plugin can be perfectly
  contained and still decode a value wrongly. That is what the contract tests
  and the hardware-verification levels are for.

**Lua is not secure because it is a scripting language.** A Lua interpreter
with its standard library intact can read your files and spawn processes. The
isolation above is something UALC builds.

### Reporting a plugin problem

Security issues in a plugin or in the host: use the reporting process above —
**do not open a public issue first**. Non-security problems: open an issue
naming the plugin `id` and version.

Review checklist and what a merge does and does not mean:
[`docs/PLUGIN_REVIEW_POLICY.md`](docs/PLUGIN_REVIEW_POLICY.md).
