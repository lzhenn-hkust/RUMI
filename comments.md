Hi Zhenning,
After discussing these issues with Junhao, we would like to confirm the following points with you before preparing the final instructions for participants.
Submission package and directory structure
We propose naming each submission archive as:
RUMI-<INSTITUTE>-<MODEL>-<POC>.tar.gz
Here, <POC> is the surname of the point of contact. For example:
RUMI-HKUST-MPAS-LIU.tar.gz
└── RUMI-HKUST-MPAS-LIU/
    ├── Participant_Model_Documentation.pdf
    ├── MANGKHUT2018/
    ├── HRAIN2023/
    ├── HRAIN2025/
    │   ├── AN-ERA5/
    │   │   ├── Init-5/
    │   │   ├── Init-4/
    │   │   ├── Init-3/
    │   │   ├── Init-2/
    │   │   ├── Init-1/
    │   │   ├── Init-0.5/
    │   │   └── Init-0.25/
    │   └── FC-GFS/
    │       ├── Init-5/
    │       ├── Init-4/
    │       ├── Init-3/
    │       ├── Init-2/
    │       ├── Init-1/
    │       ├── Init-0.5/
    │       └── Init-0.25/
    ├── HEAT2022/
    └── HEAT2024/
The experiment directory would combine the mode and forcing source. Other possible examples include:
AN-ERA5
AN-FNL
AN-JRA55
AN-UKMO
AN-OTHER

FC-GFS
FC-UKMO
FC-OTHER
This would prevent results from different forcing datasets from being mixed within a general AN or FC directory.
We include <POC> because the institution and model may not uniquely identify a submission. Multiple participants from the same institution may use the same model with different configurations. The POC identifies the person responsible for validation questions, corrections, and resubmissions.
Participants would include only the events, experiment types, and initialization experiments they have completed. They would not be required to create every directory shown above, but any submitted directory should follow the agreed naming convention.
Initialization-directory naming
The lead_* naming used in the earlier proposal, such as lead_120 or lead_096, should be replaced by the Init-* terminology in Lewis’s updated document:
Init-5
Init-4
Init-3
Init-2
Init-1
Init-0.5
Init-0.25
This avoids ambiguity for HRAIN2023 and HRAIN2025, whose peak-impact periods do not begin at 00 UTC.
Although multiple initialization times are not required for AN submissions, the same Init-* structure could be used when they are provided.
Required submission period
The guideline states:
“Covering the full simulation period is highly recommended for simulations at ~1 km resolution; the Peak Impact Periods table below is provided as reference for sub-kilometer resolution simulations where computational constraints may apply.”
It also states:
“Simulations should be run and submitted for 12 hours beyond the end of the peak impact period.”
It is unclear whether approximately 1 km simulations should submit the full event period while sub-kilometre simulations may submit only the peak-impact period plus 12 hours, or whether the full period is still expected for all simulations.
For HRAIN2025, for example:
Full recommended period:
2025-08-03 00:00 to 2025-08-06 00:00 UTC

Peak-impact period plus 12 hours:
2025-08-04 21:00 to 2025-08-06 00:00 UTC
We therefore need to agree on and provide one clearly defined submission period for each event before preparing the participant instructions and portal validation rules.
Upload form and local validation
Since the Participant Model Documentation, directory structure, and NetCDF global attributes already contain most of the required metadata, we suggest simplifying the upload form to:
Institution
Model
Point of Contact
Participant name(s)
This would avoid asking participants to manually repeat information already contained in their files.
We also suggest providing a downloadable validation script for local checks before compression and upload. This would prevent participants from spending considerable time creating a large archive only to discover afterwards that their files do not meet the requirements. It could also reduce failed submissions and the validation burden on the portal.
Large-file uploads
A complete archive may reach approximately 15 GB. Such a large upload may fail because of an interrupted connection or limited network speed.
Does the portal support resumable uploads, allowing participants to continue an interrupted upload rather than restarting it?
Once these points are agreed, we will prepare a short .txt document containing the final instructions for participants.
We would appreciate your thoughts and suggestions.
Best regards,
Zhuo
LI Zhenning

​liu zhuo <liuz09815@gmail.com>​
​
HU Junhao;​
Jimmy C H FUNG;​
MA Tianyuan;​
Xiaoming SHI;​
Fei CHEN​
Hi Zhuo,

Thank you for the detailed proposal. I agree with much of it, but several points should be clarified before we update the guidelines and validator.
Please check the following point-to-point and magic-to-magic response before decision:

Archive naming and package size
Including institute, model, and POC is useful. However, a surname may not uniquely identify multiple configurations from the same participant. We may need an additional configuration identifier and version, for example:
RUMI-HKUST-MPAS-LIU-CONFIG01-v01.tar.gz
The portal already records the authenticated uploader, so the database upload ID should remain in the authoritative identifier.

I am also concerned about placing all events and experiments in one archive. A 15 GB all-or-nothing package would be expensive to validate and resubmit if one file fails. I would prefer one archive per event and experiment, or at least a defined maximum package size.

Directory structure and experiment names
Grouping by event, forcing dataset, and initialization experiment is sensible and prevents data mixing. However, I suggest retaining the canonical experiment identifiers already used in NetCDF filenames and global attributes, such as RUMI-ERA5-AN and RUMI-GFS-FC, rather than introducing the reversed AN-ERA5 convention. Otherwise, we must define and maintain an explicit mapping.

Initialization directories
I agree that the previous lead_* naming should be replaced, but I suggest expressing initialization offsets in hours rather than days. This is more precise and consistent with the NetCDF metadata and forecast lead-time conventions. For example:
Init-120h/
Init-96h/
Init-72h/
Init-48h/
Init-24h/
Init-12h/
Init-6h/
The guidelines should define exactly what these offsets are measured relative to, using an event-specific UTC reference time. For example, Init-24h should clearly mean an initialization time 24 hours before the defined reference time. This also avoids ambiguity for events whose peak-impact periods do not begin at 00 UTC. For AN submissions with only one initialization, the Init-* directory may be omitted or standardized as Init-0h; we should agree on one convention.

Required submission periods
This must be resolved before implementing strict validation. My interpretation is that approximately 1 km simulations should provide the full event period, while sub-kilometre simulations may provide the peak-impact period plus 12 hours. However, this should be confirmed by the group. We need one table specifying the required start and end timestamps, resolution category, output interval, and endpoint inclusivity for every event.

Upload form and metadata
I support simplifying the form. Institution and POC can come from the authenticated account, while model and experiment information can be extracted from the archive and NetCDF metadata. Instead of repeating fields manually, the portal could display the extracted information for confirmation.
A small machine-readable manifest at the archive root may also help identify the configuration, participants, POC, events, and experiment types without relying on PDF parsing.

Local validation
I strongly support providing a downloadable validator. It should use the same rules and version as the portal and validate the uncompressed directory before packaging. It should check directory names, time coverage, NetCDF variables, coordinates, attributes, and filename consistency.

7. Resumable uploads
The current portal uploads in 8 MB chunks and accepts files up to 20 GB, but it is not yet fully resumable after a connection failure, page refresh, or browser restart. The server records the received offset, so proper resume support is feasible. We should add automatic chunk retries, persistent upload IDs, and a Resume function.

Best regards,
Zhenning
liu zhuo<liuz09815@gmail.com>

​
LI Zhenning​
​
HU Junhao;​
Jimmy C H FUNG;​
MA Tianyuan;​
Xiaoming SHI;​
Fei CHEN​
Hi Zhenning,
Thank you for the detailed comments. Junhao and I discussed these points further, and I think we are largely in agreement. Please see our responses below.
1. Archive naming and package size
I agree that adding a configuration identifier and version number would make the archive name more robust.
I also agree that placing all five events in one large archive may make validation and resubmission unnecessarily difficult. Since we currently have 17 participating institutions and five events, organizing submissions by event would give 17 × 5 institution-event combinations at the basic level, which I think is manageable.
We therefore suggest using one archive per event, with the event code included in the archive name. For example:
RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01.tar.gz
Different experiment types and initialization runs for the same event could then be organized within that event archive. The portal/database upload ID can still serve as the authoritative unique identifier.
2. Directory structure and experiment names
I agree with your suggestion. It would be better to retain the canonical experiment identifiers already used in the NetCDF filenames and global attributes, such as:
RUMI-ERA5-AN
RUMI-GFS-FC
rather than introducing AN-ERA5 or FC-GFS. This avoids creating an additional mapping between the directory names and the existing experiment identifiers.
3. Initialization-directory naming
I agree that using hours would normally be more precise. However, the current guideline already defines the experiments as:
Init-5
Init-4
Init-3
Init-2
Init-1
Init-0.5
Init-0.25
and these labels do not always correspond exactly to 120, 96, 72, 48, or 24 hours before the peak.
For example, for HRAIN2023, the guideline specifies:
Peak impact start: 2023-09-07 14:00 UTC

Init-5:    Sep 02 00Z
Init-4:    Sep 03 00Z
Init-3:    Sep 04 00Z
Init-2:    Sep 05 00Z
Init-1:    Sep 06 00Z
Init-0.5:   Sep 07 02Z
Init-0.25:   Sep 07 08Z
Therefore, Init-1 is actually 38 hours before the peak-impact start rather than exactly 24 hours. A similar issue occurs for HRAIN2025 because the longer-lead experiments use the 00 UTC forecast cycles.
For this reason, I think it may be better to retain the existing Init-* terminology from the guideline as the experiment labels, while recording the actual initialization timestamp in the NetCDF metadata.
For AN-mode experiments, I think using a standardized Init-0h directory is preferable to omitting the Init-* level, as it keeps the structure consistent with FC-mode experiments and avoids introducing a special case in the directory hierarchy. However, I am also thinking about how we should distinguish AN simulations if participants use multiple initialization times. In that case, we would still need a clear and consistent naming convention so that results from different AN initialization settings are not mixed together.
4. Required submission periods
Based on our interpretation of the current guideline, we suggest the following submission windows:


Event Code
~1 km Required Period
Sub-km Required Period
Output Interval
Final Timestamp
MANGKHUT2018
Sep 15 00Z – Sep 17 00Z
Sep 15 12Z – Sep 17 00Z
1 h
Required
HRAIN2023
Sep 06 00Z – Sep 09 00Z
Sep 07 02Z – Sep 08 20Z
1 h
Required
HRAIN2025
Aug 03 00Z – Aug 06 00Z
Aug 04 09Z – Aug 06 00Z
1 h
Required
HEAT2022
Jul 22 00Z – Jul 25 00Z
Jul 22 12Z – Jul 25 00Z
1 h
Required
HEAT2024
Aug 27 00Z – Aug 29 00Z
Aug 27 12Z – Aug 29 00Z
1 h
Required
For staggered FC-mode experiments, if the actual initialization time is later than the required start time listed above, the required submission period would begin at the actual initialization time, while the required final timestamp would remain unchanged.
The current ~1 km submission periods already begin at the Init-1 time for several events. For the time coverage, we suggest not strictly requiring the initial timestamp, particularly for accumulated variables such as hourly rainfall. We would only require the specified final timestamp to be present in the submission.
5. Upload form and metadata
I agree with your suggestion that extracting institution, POC, model, experiment information, and other metadata directly from the authenticated account, archive structure, and NetCDF metadata would reduce unnecessary manual input.
Regarding the proposed machine-readable manifest, could you clarify how this would be generated and used by the portal? Would participants need to prepare and provide the manifest.yaml themselves, or could it be generated automatically from the information already available in the archive structure and NetCDF metadata?
If participants need to prepare it manually, I wonder whether this would add an additional burden or create another source of inconsistency between the manifest and the NetCDF metadata. If it can be generated automatically, I think it could be useful for organizing and validating the submissions.
6. Local validation
I fully agree. Providing participants with the same validator used by the portal would allow them to check the uncompressed directory before packaging and uploading. This should substantially reduce failed submissions and make the overall process more efficient.
7. Resumable uploads
I also fully agree with adding automatic chunk retries, persistent upload IDs, and a Resume function. These improvements would be particularly useful for large submissions and would greatly improve the reliability of the upload system.
Based on our discussion, I think the revised submission structure could be:
RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01.tar.gz
└── RUMI-HKUST-MPAS-HRAIN2025-LIU-CONFIG01-v01/
    ├── Participant_Model_Documentation.pdf
    │
    ├── RUMI-ERA5-AN/
    │   └── Init-0/
    │
    └── RUMI-GFS-FC/
        ├── Init-5/
        ├── Init-4/
        ├── Init-3/
        ├── Init-2/
        ├── Init-1/
        ├── Init-0.5/
        └── Init-0.25/
For now, I have not included manifest.yaml as a required file in this proposed structure, since I think we should first clarify whether it needs to be prepared manually by participants or can be generated automatically by the portal.
In this structure:
each archive corresponds to one event, one model configuration, and one version;
the event code is included directly in the archive name;
experiment directories retain the canonical RUMI identifiers;
FC initialization directories retain the Init-* terminology already defined in the guideline;
Init-0h is shown here as the proposed default for a single AN initialization, while the naming convention for multiple AN initialization times still needs to be agreed;
participants include only the experiment and initialization directories they have actually completed.
Once we agree on the AN initialization naming, the required time-coverage rules, and how the manifest would be handled, I think we can finalize the participant instructions and corresponding validation rules.
Best regards,
Zhuo
