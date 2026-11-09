# Why UALC

> **Software support should not determine the lifespan of perfectly good hardware.**

This document explains the reasoning behind Universal Appliance Local Control. It is a
statement of intent and design philosophy, not a claim about what the project currently does.
For what is actually working today, read [STATUS_MATRIX.md](STATUS_MATRIX.md) — it is the
authoritative record, and it is deliberately unflattering.

## Why local appliance ownership matters

When you buy an appliance, you own the machine. In practice you increasingly do not own its
behaviour. The compressor, the motor, the sensors and the radio are yours; the decision about
whether they respond to you is made somewhere else, by a service you do not control and did not
buy.

That gap matters because the two have very different lifespans. A washing machine or an air
conditioner is engineered to last ten to fifteen years. The mobile app and cloud service that
operate it are commercial products with much shorter commercial lives. Nothing about the
hardware changes when the service is retired — it simply stops being reachable.

Local control closes that gap. If a device can be operated over the network it is already
connected to, its useful life is bounded by its mechanical and electrical condition, which is
how it should be.

## Why cloud-dependent functionality creates longevity risks

A cloud dependency is a single point of failure that sits outside the owner's control and
outlives no commitment. In practice it fails in several ordinary ways:

- **Service retirement.** A vendor exits a product line, is acquired, or simply decides the
  running costs are not worth it.
- **Account and app churn.** A rewritten app drops older models; an account system changes and
  older firmware can no longer authenticate.
- **Connectivity.** A device that needs a round trip to another continent to turn on a light
  does not work when the connection does not.
- **Unilateral change.** Features present at purchase can be altered or removed remotely, and
  the owner has no version to stay on.

None of these are hypothetical, and none of them involve the appliance breaking. That is the
point: the failure mode is entirely administrative, and the machine is still perfectly good.

## Why UALC favours non-invasive communication over firmware replacement

There is an established and valuable tradition of replacing appliance firmware outright. UALC
deliberately takes a different route, for reasons of reach rather than disagreement:

- **Nothing is opened, soldered, or re-flashed.** Replacing firmware usually means physical
  access, disassembly, and the real risk of turning a working appliance into a brick. That is a
  high barrier, and an irreversible one when it goes wrong.
- **It generalises better.** A flashing procedure is specific to one board revision. Speaking a
  device's existing local protocol can apply across many models that share it.
- **It is reversible.** If the approach does not work, nothing has been changed on the device
  and the owner is exactly where they started.
- **It keeps the device's own safety logic intact.** Appliance firmware contains interlocks and
  thermal limits written by people with the full specification. UALC does not replace that
  reasoning; it communicates with it.

### Warranty considerations — stated carefully

Because the approach involves no physical modification and no firmware replacement, it avoids
the most obvious categories of warranty dispute that come with opening or re-flashing hardware.

That is **not** a guarantee that any particular warranty is preserved. Warranty terms vary by
manufacturer, product and jurisdiction, and a manufacturer may take its own view of any
unofficial local access. Nothing in this project constitutes legal advice, and the relationship
between an owner and their manufacturer remains between them. If warranty status is critical to
you, check your own terms before doing anything.

## Data ownership and locally controlled processing

Appliance telemetry is more revealing than it first appears. When the washing machine runs, how
often the fridge door opens, when a room is heated — in aggregate that is a detailed account of
when a household is awake, at home, or away.

UALC's position is that this data should be processable where it is produced. Not because
remote processing is inherently wrong, but because it should be a choice rather than a
precondition for the appliance functioning at all. Local processing also tends to be faster and
to keep working during an outage.

The project's architecture reflects this: credentials are isolated per device and per
manufacturer, and no plugin or profile is ever handed one.

## Manufacturer interoperability and reusable profiles

Most of the real cost in this area is rediscovery. Each appliance tends to be reverse
engineered from scratch, in isolation, and the result is frequently a single-purpose script
that works for one person's model and is never reused.

UALC is structured so that work accumulates instead:

- A **router** that is entirely manufacturer-independent and contains no device-specific code.
- A **translator** with a common message contract, so a consumer such as Home Assistant can use
  a new device without knowing anything about its protocol.
- **Reusable device profiles**, so adding a compatible model can be a matter of describing it
  rather than writing new code.

The intent is that supporting the second device of a family is dramatically cheaper than the
first, and the tenth is nearly free.

## Right to repair, and electronic waste

An appliance discarded because its app stopped working is pure waste: the embodied carbon and
material cost of manufacturing it are spent, and the replacement spends them again. Compared
with most things a developer can do, extending the service life of equipment that already
exists is unusually effective.

This sits naturally alongside right-to-repair principles. The argument there is that owners
should be able to maintain what they own, with access to the parts and information required.
UALC applies that reasoning to the communication layer: if a device can still be talked to, it
can still be used, and it does not become scrap on a vendor's schedule.

## Community contributions and responsible protocol research

The limiting factor on this project is not code — it is hardware access. No individual owns
enough different appliances to validate broad support, which makes contribution essential
rather than decorative. The contribution model is built for that: declarative profiles for
simple cases, sandboxed handlers for moderate ones, full adapters where genuinely needed.

Research here is held to a few standards:

- **Work on devices you own**, and document what was actually observed rather than what was
  assumed.
- **Distinguish verified from inferred.** The support levels and verification sources are
  tracked as separate axes precisely so that an untested claim cannot quietly present itself as
  a tested one.
- **Never publish credentials**, personal network details, or captures containing them.
- **Respect the licences and provenance** of prior work, and cite rather than silently absorb
  other people's findings.

## Current limitations and maturity

To be unambiguous:

- **UALC is pre-alpha.** It is infrastructure and research, not a finished product.
- **No appliance is controllable through the UALC framework on real hardware today.** The test
  suites run offline, against local brokers and simulators.
- Passing tests demonstrate that the plumbing is internally consistent. They demonstrate
  **nothing** about whether a real device will accept a connection, trust a certificate, or
  speak the protocol variant assumed.
- Some components are explicitly blocked on evidence that does not exist yet, and are labelled
  as such rather than quietly implemented on assumption.
- Interfaces will change. Nothing here should be depended on in production.

If that sounds cautious, it is deliberate. The failure mode this project is trying to avoid is
the one where confident documentation outruns tested reality, and someone trusts it with an
appliance they cannot afford to lose.

## In short

The goal is not to take anything away from manufacturers, and not to encourage people to pull
their appliances apart. It is narrower than that: when the software behind a device is retired,
the device itself should not have to be.
