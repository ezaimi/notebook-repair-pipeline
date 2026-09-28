# RQ1 resolver-informed explanation comparison

This is the stronger comparison requested by the supervisor. It compares the
frozen LLM explanation with a deterministic explanation that contains verified
resolver evidence:

- `sklearn` → `scikit-learn`;
- `cv2` → `opencv-python`;
- `scipy.integrate.cumtrapz` → compatible SciPy version below 1.14.0;
- `numpy.VisibleDeprecationWarning` → compatible NumPy version below 2.0.0.

## Create the forms

1. Open [script.google.com](https://script.google.com) and create a **new**
   Apps Script project. Do not reuse the project that created the earlier
   minimal-template forms.
2. Paste the complete contents of
   `scripts/google_forms_resolver_informed_comparison_setup.gs` into `Code.gs`.
3. Save, select `createResolverInformedComparisonStudy`, and click **Run**.
4. Authorise the Forms, Sheets, and trigger permissions. The execution log
   shows the central spreadsheet URL; its `Study setup` tab contains the four
   participant links.

Assign codes and links round-robin: R01 → Variant A, R02 → B, R03 → C,
R04 → D, then repeat. Recruit a new group of at least 16 participants,
preferably 20 so that each variant has five participants. Do not present the
previous minimal-template forms or use their 16 responses in this comparison.

Every completed participant contributes four evaluations: two LLM and two
resolver-template. The normalised sheet automatically records four rows per
participant and contains no submission date, timestamp, or participant
completion-time field. The forms retain their own response records; the script
does not link all four forms to the same response spreadsheet, because the
normalised sheet is the study's central output.
