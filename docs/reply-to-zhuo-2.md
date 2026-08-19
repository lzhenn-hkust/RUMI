# Reply to Zhuo — revised periods, variable levels, and a naming simplification

*Response to the fourth message in the thread, plus two decisions taken on our
side afterwards. `docs/RUMI-submission-spec-v3.md` is the authoritative version;
everything below is implemented and covered by tests.*

---

Hi Zhuo,

Thank you — all four points are in. Two of them changed shape after we worked
through the consequences, and there is a naming simplification at the end that
touches something we had previously agreed, so please read that part carefully.

## 1. HRAIN2025 sub-km start — adopted, and it is now one clean rule

You are right, and your correction is better than what I had. I inferred the
rule from the table and got `peak start − 12 h`; your reading of the guideline is
that the lead-in before the peak is a matter for each model configuration, and
only the 12 hours *after* the peak are a submission requirement.

Your five rows follow a single rule exactly, which is what the validator now
enforces:

> **sub-km required period = peak impact start → peak impact end + 12 h**

| Event | Sub-km required period | Hourly steps |
|---|---|---|
| MANGKHUT2018 | Sep 16 00Z – Sep 17 00Z | 25 |
| HRAIN2023 | Sep 07 14Z – Sep 08 20Z | 31 |
| HRAIN2025 | Aug 04 21Z – Aug 06 00Z | 28 |
| HEAT2022 | Jul 23 00Z – Jul 25 00Z | 49 |
| HEAT2024 | Aug 28 00Z – Aug 29 00Z | 25 |

The ~1 km column is unchanged, and only the final timestamp is a hard
requirement.

## 2. Init-0.5 / Init-0.25 — agreed, and deliberately non-blocking

Agreed. Because you want to confirm the practicality with Lewis first, I went
further than "warning within 6 hours": for `Init-0.5` and `Init-0.25` **any**
deviation is a warning and never a rejection, and the message says the label is
provisional. `Init-5` through `Init-1` sit on 00 UTC cycles and are unambiguous,
so those stay strict. Tightening this later is a one-line change.

## 3. Participant Model Documentation — confirmed

Agreed, and already implemented that way: a `.pdf` or `.docx` at the top level
of every event archive, and its absence is an error.

## 4. Required variables — implemented, but as **recommended**, not mandatory

The variable lists are in, with one important change of level from what you
proposed.

| Level | Variables | If missing |
|---|---|---|
| **Required** | T2M, U10M, V10M, PRATE, SLP, RH2M, TOTAL_PRECIP, PSFC, Q2M | **Submission rejected** |
| Recommended | SWDOWN, SWNET, SWDIR, LWDOWN, LWNET | Accepted; uploader is told which were not found |
| Recommended | T, Z, RH, U, V, Q at 850/500/200 hPa, plus OMEGA **or** W | Accepted; uploader is told which were not found |

The reasoning is the consequence I measured before deciding. Making the 3D
fields mandatory would roughly **quadruple** the volume per timestamp:

| Group | Per timestamp |
|---|---|
| Core 2D (9 fields) | 1.44 MB |
| Radiation 2D (5 fields) | 0.80 MB |
| 3D (7 fields × 3 levels) | 3.36 MB |
| **Total** | **5.61 MB**, measured, versus 1.44 MB for core 2D alone |

That is about 2.9 GB of raw data for a full HRAIN2025 archive. The portal handles
it comfortably — uploads are resumable and validating all 512 files took 29
seconds in the background — but it would have meant that **every participant who
has already prepared 2D-only output could not submit at all** until they
regenerated their files. Rejecting a scientifically usable submission over fields
the group is still discussing with Lewis is the wrong trade.

So the radiation and pressure-level fields are now recommended: the submission is
accepted and stored, and the uploader gets an explicit note listing exactly which
recommended variables were not found, both on the upload page and in the stored
validation record. We can see from the portal who has supplied what, and chase
the gaps individually rather than through a wall of rejections. If the group
later decides to make either group mandatory, it is a one-line change in
`rumi_protocol.py`.

`create_ncdf.py` writes the complete set, so anyone using the reference script
produces everything without thinking about it.

## 5. A naming simplification — this changes something we agreed

We have dropped the `RUMI-` prefix everywhere, and switched the version token
from `v` to `r`:

| | Before | Now |
|---|---|---|
| Archive | `RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01.tar.gz` | `HKUST-MPAS-HRAIN2025-LIU-CONFIG01-r01.tar.gz` |
| Experiment directory | `RUMI-ERA5-AN`, `RUMI-GFS-FC` | `ERA5-AN`, `GFS-FC` |
| NetCDF file | `RUMI-ERA5-AN-WRF-MANGKHUT2018-20180916120000.nc` | `ERA5-AN-WRF-MANGKHUT2018-20180916120000.nc` |
| Version suffix | `_v02` | `_r02` |

**I want to flag this explicitly**: in the second round we agreed to keep the
canonical `RUMI-` experiment identifiers precisely so no mapping table would be
needed. Dropping the prefix supersedes that. Everything inside a RUMI submission
is a RUMI file, so the prefix was pure repetition — but it does mean the
`experiment` global attribute now reads `ERA5-AN` rather than `RUMI-ERA5-AN`,
and the full experiment list is:

    ERA5-AN   FNL-AN   JRA55-AN   UKMO-AN   OTHER-AN
    GFS-FC    UKMO-FC  OTHER-FC

The validator rejects the old prefixed form with a message naming the valid
identifiers, so nobody can submit under the old convention by accident. If you or
Junhao would rather keep the prefix, say so now — reverting is cheap today and
expensive once instructions have gone out.

## Status

Settled and enforced: per-event packaging, archive and file naming, experiment
directories, `Init-*` naming including `Init-0` and `Init-<YYYYMMDDHH>`, required
periods for both resolution classes, the documentation requirement, and the nine
required 2D variables.

Recommended and reported but never blocking: the radiation fields and the
pressure-level fields.

Still with Lewis: whether `Init-0.5` / `Init-0.25` are practical against the
available forecast cycles, and whether the radiation fields should eventually
become required for all five events or only the heatwave cases.

`rumi_validate.py` is downloadable from the portal and applies exactly these
rules, so participants get the portal's verdict before they spend time packaging.

Best regards,
Zhenning
