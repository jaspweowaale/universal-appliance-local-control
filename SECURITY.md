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
