# Community device profiles

Level-1 model profiles contributed by people who own the appliance. Drop a
profile here if there is no `devices/<manufacturer>/` directory yet; a
maintainer will promote it to a manufacturer directory once there are a few.

A profile here is **not** lower quality than one in a manufacturer directory.
The directory says nothing about status — that lives in each profile's own
`support_status`, and the validator enforces that it is honest.

## Adding one

1. Read [`../../docs/contributing/DEVICE_CONTRIBUTION.md`](../../docs/contributing/DEVICE_CONTRIBUTION.md).
2. Copy [`../lg/AIR_910604_WW.json`](../lg/AIR_910604_WW.json) as a starting
   point.
3. Name it `<MODEL_ID>.json`, using the identifier the appliance itself
   reports.
4. Fill in `support_status` truthfully. With fixtures and no hardware test
   that is `DECODED` / `none` / `false`, and that is a good contribution.
5. Populate `known_limitations`. Say what you did **not** do.
6. Run the validator — it loads every file in this tree, so a broken profile
   fails CI rather than failing later on somebody's appliance:

```bash
PYTHONPATH=translator:testing_infra:. python testing_infra/profile_validation_test.py
```

## Reminders

* A profile is **data**. No executable expressions, no credentials, no shell
  commands — all rejected at load time.
* `codec` must name a codec UALC already implements. A genuinely new protocol
  is a [Level 3](../../CONTRIBUTING.md) contribution.
* Empty `firmware_ranges` means **unknown**, not **all**.
* Claim the models you actually observed. A shared model identifier is not
  evidence of a shared protocol — this project has already been caught out by
  exactly that assumption.
