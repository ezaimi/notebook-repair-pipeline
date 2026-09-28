# Create the automatic Google Forms comparison study

The script [google_forms_comparison_setup.gs](/home/zaimi/era/ma-erisa-zaimi/scripts/google_forms_comparison_setup.gs) creates four complete, blinded Google Forms and one central Google Sheet. Every submission is automatically converted into six normalised rows in the `Normalised responses` sheet: one row for each explanation a participant rated.

## One-time setup

1. Go to [script.google.com](https://script.google.com) while signed into the Google account that should own the survey.
2. Create a **New project**, remove its default code, and paste in the complete contents of `google_forms_comparison_setup.gs`.
3. Select `createComparisonStudy` in the function drop-down, then click **Run**. Google will ask you to authorise access to Google Forms, Google Sheets, and triggers. This is required so submissions can be recorded automatically.
4. Open the execution log. It contains the URL of the newly created spreadsheet. Its `Study setup` tab contains the participant and edit URLs for Variants A–D.

Send participant codes round-robin with the matching participant link: C01 → A, C02 → B, C03 → C, C04 → D, then repeat. Do not tell participants which explanation type they are rating.

## Results

Google Forms keeps its normal raw response tabs. The script also automatically appends clean, numeric results to `Normalised responses` whenever someone submits a form. It includes the hidden research fields `survey_variant`, `example_id`, and `explanation_method`, so no manual matching is needed later.

For analysis, download `Normalised responses` as CSV. Do not combine it with the previous LLM-only human-study responses: this is a new blinded comparison.

The owner of the Google account remains responsible for confirming that the consent text and data handling are permitted by the thesis's ethics/data-protection arrangements before distributing the links.
