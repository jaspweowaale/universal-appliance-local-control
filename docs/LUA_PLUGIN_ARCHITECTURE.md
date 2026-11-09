# UALC Lua plugin architecture — decision record

Status: **ACCEPTED (Option C), implemented as a reviewed experimental
extension point. Disabled by default.**
Date: 08 11 2026 · Supersedes: nothing · UALC plugin API version: `1.0`

## 1. The problem

UALC's goal is local control of appliances the maintainers do not own. The
binding constraint is not code — it is **hardware access**. Somebody with the
appliance in their house can observe its protocol; we cannot. So the
architecture has to let that person contribute working support without
needing commit rights to UALC core, and without us having to trust their code
with our house.

Python-only extension does not solve this well. It means every contributor
edits the same package, their code runs in the same process as the router and
the credential store, and a review has to reason about arbitrary Python —
which can do anything.

## 2. Options considered

### Option A — Lua handlers in a managed in-process runtime

Embed Lua in the Python process via a binding (`lupa`, which wraps LuaJIT or
Lua).

* **For:** lowest call overhead; simple data marshalling; one process.
* **Against:**
  * adds a **compiled C-extension dependency** to a project that is
    otherwise stdlib-only outside the Roborock adapter — a real cost for a
    framework we want people to install easily;
  * an in-process sandbox is the weakest kind. A runaway `while true do end`
    blocks the host; a memory blow-up kills the host; a crash in the C
    binding takes the whole process with it;
  * the handler shares an address space with the credential store. Even if
    no API exposes credentials, "shares memory with secrets" is a far worse
    starting posture than "cannot see them";
  * LuaJIT is Lua 5.1-era; standard Lua is 5.4/5.5. Picking one splits the
    contributor ecosystem.

### Option B — Lua plugins as isolated subprocesses over a defined protocol

Run the handler as a separate OS process; speak a documented wire protocol.

* **For:** a hang, crash or memory explosion is contained and recoverable;
  the OS enforces limits; no new Python dependency; the boundary is auditable
  because it is a *protocol*, not an API surface.
* **Against:** per-call IPC overhead; the protocol has to be specified and
  versioned; binary payloads need an encoding (we use lowercase hex).

### Option C — Hybrid: declarative profiles, Lua for behaviour, Python core

Three levels. Most contributions need only the first.

* **For:** matches the actual distribution of work. The majority of "add my
  model" cases are a different tag-to-field table, which is **data** and
  needs no sandbox at all because it cannot express behaviour. Lua is
  reserved for the minority that genuinely need logic. Python core keeps
  transport, credentials and the HA boundary.
* **Against:** three mechanisms to document instead of one.

## 3. Decision

**Option C, with Option B as its Level-2 mechanism.** The two are
complementary, not competing: C decides *what runs where*, B decides *how
Lua runs*.

| Level | Mechanism | Sandbox needed | Typical contribution |
|---|---|---|---|
| **1** | JSON/YAML model profile (`devices/<vendor>/<MODEL>.json`) | none — it is data | a model on an already-supported protocol |
| **2** | Lua handler (`plugins/lua/...`), isolated subprocess | yes | model-specific decoding, quirks, partial-state rules |
| **3** | Python `ProtocolAdapter` (`translator/adapters/`) | code review | a genuinely new protocol family |

Implemented in this repository:

* `translator/profiles.py` — Level 1. Loader, validator, `ProfileAdapter`.
* `translator/lua_host.py` — Level 2 host. Subprocess supervision,
  limits, output validation, `LuaProtocolAdapter`.
* `plugins/lua/ualc_sdk.lua` — Level 2 guest. Sandbox, JSON codec, dispatch.
* `plugins/lua/examples/lg_air_910604_ww/` — reference handler.
* `devices/lg/AIR_910604_WW.json` — reference profile, same device.

## 4. Where Lua executes, and how its output reaches Home Assistant

**Home Assistant does not run Lua, and nothing in this design asks it to.**
Being explicit, because the question is easy to get wrong:

```
  appliance                UALC host (a machine you control; not necessarily
     |                     the HA box, and preferably not it)
     | local protocol
     v
  +-----------------------------------------------------------------+
  |  router/  (Python)      byte-for-byte TCP/TLS relay, no parsing |
  +-----------------------------------------------------------------+
     | raw frame
     v
  +-----------------------------------------------------------------+
  |  translator/  (Python)  ===== UALC CORE, TRUSTED =====           |
  |     chooses an adapter for (manufacturer, protocol_family)       |
  |                                                                  |
  |   ProfileAdapter          LuaProtocolAdapter      RoborockB01... |
  |   (Level 1, data)         (Level 2)               (Level 3)      |
  |                                 |                                |
  |                                 | NDJSON over stdin/stdout       |
  |                   - - - - - - - | - - - - - - - -  process border|
  |                                 v                                |
  |                      +------------------------+                  |
  |                      |  lua (separate PID)    |  UNTRUSTED       |
  |                      |  ualc_sdk.lua sandbox  |                  |
  |                      |  community handler.lua |                  |
  |                      +------------------------+                  |
  |                                 |                                |
  |                                 | validated result               |
  |     StandardMessage  <----------+                                |
  +-----------------------------------------------------------------+
     | StandardMessage (integration_contract.py)
     v
  ha_interface.py  ->  MQTT / a Home Assistant integration  ->  HA
```

The Lua process returns plain decoded values. **UALC core, in Python, is what
constructs the `StandardMessage`.** A plugin can never mint an envelope, set
`auth_status` to `VERIFIED`, or address a device it was not invoked for. HA
sees an ordinary `StandardMessage` and cannot tell which level produced it —
which is exactly the property that lets a Lua contribution work without
touching the HA interface.

## 5. The operation set

A plugin **declares** what it implements; the host never assumes a uniform
surface. All operations are optional.

| Operation | Purpose |
|---|---|
| `describe` | identity, supported models, operation list, honest status |
| `identify` | "is this model mine?" |
| `parse_inbound` | frame → decoded state (+ `partial` flag) |
| `decode_state` | alias for decoders that separate framing from semantics |
| `describe_controls` | readable/writable fields and their enums |
| `supported_commands` | which `StandardCommand`s can be built |
| `validate_command` | check parameters *before* anything is encoded |
| `build_outbound` | command → frame bytes |
| `is_ack_for` | does this inbound frame acknowledge that command? |

The reference handler deliberately implements **eight of the nine** — it has
no `build_outbound`, because the outbound frame's checksum polynomial has not
been independently verified and emitting unverified bytes at real hardware is
the one thing a decoder must not do. The contract test asserts that
`build_outbound` raises `NotImplementedError` for it. **Partial
implementations are a first-class outcome, not a defect**, and the example
exists partly to prove that.

Full wire format: [`PLUGIN_MANIFEST_SPEC.md`](PLUGIN_MANIFEST_SPEC.md).

## 6. Security posture — and its limits

> **Lua is not secure because it is a scripting language.** A Lua
> interpreter with its standard library intact can read your files and spawn
> processes. The isolation below is something we *build*; it is not something
> Lua gives us.

### Enforced, and covered by a test in `testing_infra/plugin_security_test.py`

| Control | Mechanism | Test |
|---|---|---|
| No filesystem access | `io`, `dofile`, `loadfile` removed from `_ENV` | group 1, 2 |
| No process execution | `os.execute`/`os.remove`/`os.rename`/`os.exit` removed; only `os.time`/`clock`/`difftime` remain | group 1 |
| No host environment | `os.getenv` removed; child env is a 4-variable allow-list with empty `LUA_PATH`/`LUA_CPATH` | group 1 |
| No native library loading | `package`, `require`, `package.loadlib` removed | group 1, 2 |
| No bytecode injection | loaded with `load(src, name, "t", env)`; a leading `\27` is rejected before that | group 3 |
| CPU exhaustion | `RLIMIT_CPU` + host wall-clock timeout per request | group 4 |
| Memory exhaustion | `RLIMIT_AS` (best effort) | — |
| Cannot create files | `RLIMIT_FSIZE = 0` (pipes are unaffected, so stdout still works) | — |
| Cannot fork | `RLIMIT_NPROC` where permitted | — |
| Output flooding | response size cap, enforced byte-by-byte while reading | group 5 |
| Lying about types | every returned field type-checked before use | group 6 |
| Invented error codes | host rejects any code outside the closed set | group 7 |
| **Credential exposure** | **the contract has no credential field, and the host refuses to forward any credential-shaped key even if a caller passes one** | group 8 |
| Crash containment | handler error → `ADAPTER_ERROR`; subprocess survives | group 9 |
| Clean disable/rollback | `stop()` closes stdin, then terminate, then kill; idempotent; no orphan | group 10 |
| Forged envelopes | plugin returns values; **Python** builds `StandardMessage` and forces `auth_status = UNVERIFIED` | contract test, all cases |
| Per-device isolation | one subprocess per device/group; no shared handler state | by construction |

### NOT enforced — stated plainly

1. **No OS-level network isolation.** Lua's stdlib has no sockets and
   `loadlib` is gone, so a *pure-Lua* handler cannot open a connection. That
   is a Lua-level argument, not a kernel-level one. There is no namespace,
   seccomp or firewall confinement. **For genuinely untrusted code, run the
   UALC host in a container or VM.**
2. **rlimits are POSIX-only.** On Windows the host still applies timeouts and
   output caps but **no rlimits**. The security test reports this as a skip
   rather than passing silently.
3. **`RLIMIT_AS` is honoured inconsistently** across platforms and
   allocators. Treat it as best-effort.
4. **`RLIMIT_CPU` is coarse** (whole seconds) and is a backstop behind the
   host's wall-clock timeout, not the primary control.
5. **`preexec_fn` is used to apply rlimits**, which is not safe to call from
   an arbitrarily threaded parent. Documented rather than hidden; the host is
   intended to be driven from the asyncio core, not from many threads.
6. **A reviewed plugin is still a trust decision.** Nothing here makes
   reading the diff unnecessary. See
   [`PLUGIN_REVIEW_POLICY.md`](PLUGIN_REVIEW_POLICY.md).
7. **Resource limits do not bound *correctness*.** A plugin can be perfectly
   contained and still decode a value wrongly. That is what the contract
   tests and hardware-verification levels are for, not the sandbox.

### Operational rules

* Community plugins are **`enabled_by_default: false`** in their manifest and
  must be enabled deliberately.
* **Do not run unreviewed plugins on the machine hosting production Home
  Assistant.** UALC's design already separates the two; keep them separated.
* Level 1 profiles are **not** sandboxed, because they are data and the
  validator proves it: unknown keys, unknown codecs, credential-shaped keys
  and anything resembling an expression are all rejected
  (`profile_validation_test.py`, groups 2 and 3).

## 7. Why not WASM, or a plain config DSL?

* **WASM** gives stronger isolation and we may revisit it. Today it would add
  a runtime dependency heavier than Lua's ~300 KB, and the contributor pool
  for "write a small Lua decode function" is much larger than for toolchain
  WASM. Revisit if UALC ever accepts plugins from people we have no
  relationship with at all.
* **A pure config DSL** is Level 1, and it is the *preferred* path. The reason
  Level 2 exists is that real appliances have quirks a table cannot express —
  write-while-off being acknowledged and ignored, a fan write that must carry
  the current mode, a value whose meaning depends on another field. Those need
  code. Pretending otherwise produces a DSL that slowly grows conditionals and
  becomes a bad programming language.

## 8. Costs accepted

* IPC overhead per call. Irrelevant at appliance message rates (seconds, not
  microseconds).
* A wire protocol to version. Mitigated by `min_ualc_api_version` in the
  manifest and an explicit `api_version` in `describe`.
* A second language in the tree. Deliberate: it is the price of letting
  someone who owns the appliance contribute.
* A hand-written JSON codec in Lua (~180 lines, ours, MIT). Chosen over
  vendoring a third-party Lua JSON library so no external licence attaches to
  the plugin path.

## 9. Verification status of this design

| Claim | Status |
|---|---|
| Lua handler decodes real frames identically to the Python profile | **TESTED** — `adapter_contract_test.py`, 86 checks, 13 shared cases, Python/Lua equivalence group |
| Sandbox removes the documented escapes | **TESTED** — `plugin_security_test.py`, 26 checks |
| Profile validator enforces the safety and honesty rules | **TESTED** — `profile_validation_test.py`, 32 checks |
| No regression in the pre-existing framework | **TESTED** — 79 pre-existing checks still pass |
| A Lua plugin can control a real appliance | **NOT TESTED.** No plugin in this repository has ever run against physical hardware. The reference handler cannot even send a frame. |
| The sandbox resists a determined attacker | **NOT CLAIMED.** See section 6. |
