# Reply to Zhuo and Junhao — RUMI Phase 1 submission structure

*Draft response to the third message in `comments.md`. Everything below is
implemented in `docs/RUMI-submission-spec-v3.md` (`RULES_VERSION:
2026-08-rumi-v3`), which is the document the portal and the local validator are
both generated from.*

---

Hi Zhuo, Junhao,

Thank you — I think we are now converged. I have written the agreed structure
up as a single specification so that the portal, the downloadable validator and
the participant instructions cannot drift apart. Point by point below, then
three things that came out of implementing it.

## 1. Archive naming and package size

Agreed on both counts. One archive per event, with the event code in the name:

```
RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01.tar.gz
```

The portal database upload ID stays the authoritative identifier; the archive
name is for human legibility and for letting the portal extract the
configuration identity without asking the participant to retype it.

One small constraint that the parser forces on us: **the fields must not contain
hyphens**, because the hyphen is the separator. So `WRF-ARW` has to be written
`WRFARW`. This is the same rule the NetCDF filename convention already uses, so
it is not a new burden, but it should be stated explicitly in the participant
instructions.

Per-event archives come out at roughly 2–4 GB instead of 15 GB, which is a large
improvement for resubmission cost.

## 2. Directory structure and experiment names

Agreed — canonical identifiers only:

```
RUMI-ERA5-AN   RUMI-FNL-AN   RUMI-JRA55-AN   RUMI-UKMO-AN   RUMI-OTHER-AN
RUMI-GFS-FC    RUMI-UKMO-FC  RUMI-OTHER-FC
```

No `AN-ERA5` / `FC-GFS`, and therefore no mapping table to maintain. The
validator additionally checks that each file's `experiment` global attribute
equals the directory it sits in, which catches misfiled output.

## 3. Initialization-directory naming

You convinced me — we keep the `Init-*` day labels and record the real
initialization timestamp in the NetCDF metadata. Your HRAIN2023 example
(`Init-1` is 38 hours before the peak, not 24) is exactly the case an
hours-based naming would have made wrong, and the labels are already in the
guidelines and in Lewis's document.

For the AN question you raised at the end: **`Init-0` for a single analysis-driven
run, and `Init-<YYYYMMDDHH>` when a participant runs several AN initializations
for the same event.** For example `Init-2025080300`. I prefer this over omitting
the level, for the reason you gave — the hierarchy stays identical for AN and
FC — and it gives multiple AN initializations somewhere unambiguous to live
rather than being silently mixed.

## 4. Required submission periods

I have adopted your table as-is:

| Event | ~1 km | Sub-km | Interval | Final timestamp |
|---|---|---|---|---|
| MANGKHUT2018 | Sep 15 00Z – Sep 17 00Z | Sep 15 12Z – Sep 17 00Z | 1 h | required |
| HRAIN2023 | Sep 06 00Z – Sep 09 00Z | Sep 07 02Z – Sep 08 20Z | 1 h | required |
| HRAIN2025 | Aug 03 00Z – Aug 06 00Z | Aug 04 09Z – Aug 06 00Z | 1 h | required |
| HEAT2022 | Jul 22 00Z – Jul 25 00Z | Jul 22 12Z – Jul 25 00Z | 1 h | required |
| HEAT2024 | Aug 27 00Z – Aug 29 00Z | Aug 27 12Z – Aug 29 00Z | 1 h | required |

Your reading is the one I have implemented: ~1 km simulations provide the full
event period, sub-km simulations may provide the peak impact period extended by
12 hours at each end. Your staggered-FC rule is implemented too — if the actual
initialization is later than the required start, the required period begins at
the actual initialization time and the final timestamp is unchanged.

And I have followed your suggestion on strictness: **only the final timestamp is
a hard requirement.** A missing initial timestamp, a gap in the hourly series, or
an unexpected interval are reported as warnings with the specific missing hours
listed, so we can look at them rather than the portal rejecting the submission.
That seems right given the accumulated fields.

**One thing to confirm**: your prose says the HRAIN2025 sub-km window begins
2025-08-04 21:00, but your table says Aug 04 09Z. The table is self-consistent
across all five events — every sub-km window is peak start minus 12 h to peak
end plus 12 h — so I have used **Aug 04 09Z**. Please confirm that is what you
meant.

## 5. Upload form and metadata

Agreed, and the form is being cut down to almost nothing. Institution and point
of contact come from the authenticated account; model, event, configuration and
version are parsed from the archive name; experiment and initialization
information come from the directory structure and the NetCDF attributes. The
portal displays what it extracted for the participant to confirm rather than
asking them to type it again. The only fields left are participant names and
free-text technical notes.

On your manifest question — **the participant never writes it by hand.** The
downloadable validator generates `rumi_manifest.json` at the archive root as a
by-product of a successful local check:

```bash
python3 rumi_validate.py --write-manifest RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01/
```

It records the rules version, the configuration identity, participants, the
experiment/initialization inventory, and a per-file checksum list — all derived
from what is already in the directory, so it cannot disagree with the NetCDF
metadata. The manifest is **optional**: if it is missing the portal derives the
same facts itself, and in no case does the manifest replace the portal's own
validation. It just saves work and makes the archive self-describing. I think
this answers the concern you raised, and it means we do not have to ship a
template for people to fill in.

## 6. Local validation

Agreed, and this is the piece I think will save the most time overall.
`rumi_validate.py` is a single downloadable file that runs on the uncompressed
directory before packing, applies exactly the same rules from the same
`RULES_VERSION` as the portal, and checks directory names, experiment
identifiers, initialization directories, time coverage, filename/metadata
consistency, variables, coordinates and attributes. Exit code 0 means the upload
will pass. It needs only Python 3 plus either the `netCDF4` package or `ncdump`.

## 7. Resumable uploads

Agreed, and all three of the things you listed are going in: automatic chunk
retries with backoff, a persistent upload ID so the identity survives a page
refresh or browser restart, and an explicit Resume action. The server already
tracks the received offset, so the transfer genuinely continues rather than
restarting.

## Proposed structure

Your tree is what I have specified, with `Init-0` fixed as the AN convention:

```
RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01.tar.gz
└── RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01/
    ├── Participant_Model_Documentation.pdf
    ├── rumi_manifest.json            (written by the validator, optional)
    ├── RUMI-ERA5-AN/
    │   └── Init-0/
    └── RUMI-GFS-FC/
        ├── Init-5/ … └── Init-0.25/
```

---

## Three things that came out of implementing it

**a. Init-0.5 and Init-0.25 are not on standard forecast cycles.** The tabled
times are 02Z and 08Z for HRAIN2023 and 09Z and 15Z for HRAIN2025, which are not
00/06/12/18Z GFS cycles. For forecast-driven runs participants will have to use
the nearest available cycle. I have made the validator accept an initialization
within 6 hours of the tabled value and record a warning rather than an error —
the true initialization time is in the metadata regardless. Please confirm that
matches the intent, or tell me if these labels should instead be redefined onto
the cycle times.

**b. Validation has to run asynchronously now.** A per-event archive is only
2–4 GB, but it still contains roughly 500 NetCDF files — for HRAIN2025 that is
73 hourly files for the AN run plus about 439 across the seven FC
initializations. I measured the per-file check on the portal server at 0.2 s,
so a full archive takes 4–7 minutes, and the web server's request timeout is 60
seconds. So the portal now accepts the transfer, returns immediately, and
validates in the background with a progress indicator; participants can close
the browser. Structural problems — a wrong directory name, a bad archive name —
are still reported within seconds, before any per-file work starts. Nothing
changes for the participant except that they see "validating 213/512" instead of
a frozen page.

**c. Storage is comfortable.** 17 institutions × 5 events × ~3 GB is about 255 GB
for one configuration each. The portal filesystem has 4.9 TB free, so multiple
configurations and resubmissions are not a problem. I have raised the per-user
quota accordingly.

## What I need from you to finalise

1. HRAIN2025 sub-km start — Aug 04 09Z, per your table? (section 4)
2. Init-0.5 / Init-0.25 snapping to the nearest forecast cycle — acceptable? (a)
3. Should `Participant_Model_Documentation.pdf` be required in every event
   archive, or only once per configuration? It is small, so I have currently
   required it in each.

Once those three are settled the participant instructions are ready to go out —
I have drafted them as a plain-text document so you can circulate it directly.

Best regards,
Zhenning
