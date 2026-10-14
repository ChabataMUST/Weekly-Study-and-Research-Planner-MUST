# Collaboration

Use the repository at https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST as the shared source of record. The two distribution packages contain the same program; the development handover adds explanations for local work.

## Suggested feature ownership for the next milestone

| Member | Proposed focus | Review activity |
| --- | --- | --- |
| ZhaoYue | Course/assignment organisation, import scenarios and requirement-history workflow | Run the reporting walkthrough and check the written requirements against the interface |
| WangYule | Persistence and ownership support for weekly records and report data | Review the import changes, transaction behaviour and validation cases |

These are proposed work assignments. Record completed contributions in the issues and pull requests that deliver them. Both members should review the data model and test each other's feature paths.

## Making a change

1. Start with an issue describing the user action, expected behaviour and a short acceptance case.
2. Create a branch for that change. Keep commits small enough for the other member to review.
3. Run the existing tests and add a meaningful test when behaviour changes. Recheck the affected browser workflow.
4. Open a pull request explaining the change and its validation. Ask the other member to review it before merging.
5. Update the relevant guide when the workflow or setup changes.

Use each member's own GitHub account. Do not commit local databases, session keys, `.venv` directories, installer caches or private questionnaire responses. Preserve the font license and third-party notices.

An example pull request can say: "Keep linked requirements visible after a class room changes. Checked reimport with the same occurrence key and ran the importer regression tests." Replace that example with the actual behaviour and results of the change being submitted.
