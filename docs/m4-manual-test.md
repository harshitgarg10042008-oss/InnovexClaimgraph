# M4 manual test checklist

Playwright could not complete because Docker Desktop's Linux engine was unavailable:
`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`.

1. Open `/` and verify the seeded cases table shows title, supplier, buyer, document count, needs-review count, and status.
2. Open Case A and click **Process documents**; wait until every document is `ready` or `needs_review`.
3. Open the Review workspace and select a needs-review fact.
4. Verify the evidence drawer shows the page image, quoted source, extractor, confidence, and bbox rectangle when available.
5. Edit an amount to `1,23,456.00`; press Enter and verify `Edited`, `was:`, and validation warnings.
6. Confirm one needs-review fact and verify its status becomes `Confirmed`.
7. Mark another required fact as not present and verify the required-fields count changes.
8. Click **Confirm all auto** for one document and verify the confirmation count and summary strip change.
9. Reload and verify edited, confirmed, and not-present statuses persist.
10. Open **Audit log** and verify the review actions are listed newest first.
11. Focus the review panel, press `j`, then Enter, and verify the selected fact becomes confirmed.
12. Repeat the workspace check at 390px width and verify the document list and evidence drawer remain usable.
