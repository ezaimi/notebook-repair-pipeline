/*
 * Creates four blinded Google Forms for the LLM-versus-template explanation
 * comparison and records every submission in one normalised Google Sheet.
 *
 * Run createComparisonStudy() once from script.google.com while signed in to
 * the Google account that should own the forms. Authorise the requested Forms,
 * Sheets, and trigger permissions. The created spreadsheet contains the four
 * participant URLs in the "Study setup" tab.
 */

const STUDY_TITLE = 'How people judge explanations of programming errors';
const SCALE_COLUMNS = [
  '1 — Strongly disagree',
  '2 — Disagree',
  '3 — Neither agree nor disagree',
  '4 — Agree',
  '5 — Strongly agree'
];
const SCALE_ROWS = [
  'Q1. From this explanation, I understand why the notebook failed.',
  'Q2. This explanation is satisfying.',
  'Q3. This explanation has enough detail.',
  'Q4. This explanation seems complete.',
  'Q5. This explanation is useful for understanding what went wrong.',
  'Q6. This explanation seems correct, based on the error shown.'
];

// The method field is never added to a form. It is only stored in the
// researcher-facing sheet after the response is received.
const ASSIGNMENTS = {
  A: [[1, 'llm'], [2, 'template'], [3, 'llm'], [4, 'template'], [5, 'llm'], [10, 'template']],
  B: [[1, 'template'], [2, 'llm'], [3, 'template'], [6, 'llm'], [7, 'template'], [11, 'llm']],
  C: [[4, 'llm'], [6, 'template'], [8, 'llm'], [9, 'template'], [12, 'template'], [10, 'llm']],
  D: [[5, 'template'], [7, 'llm'], [8, 'template'], [9, 'llm'], [11, 'template'], [12, 'llm']]
};

const EXAMPLES = {
  1: {
    executionId: 62, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'sklearn'",
    llm: "What happened: The notebook failed because Python could not find the module 'sklearn'.\n\nWhy it happened: The notebook imports 'sklearn', which is not available in the execution environment. The classifier also marks this as an import/distribution-name mismatch, meaning the import name may not directly match the package distribution name.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'sklearn'.\n- The root_cause_hint is import_distribution_name_mismatch.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'sklearn' when the notebook was executed. This means that the requested import was not available in the current environment. The message identifies the missing import, but it does not by itself show whether the required package is absent or whether the import name differs from the package distribution name. The exact failing cell and dependency files are not available, so the reason for the missing import cannot be determined further."
  },
  2: {
    executionId: 79, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'cv2'",
    llm: "What happened: The notebook failed because Python could not find the module 'cv2'.\n\nWhy it happened: The notebook imports 'cv2', which is not available in the execution environment. The classifier also marks this as an import/distribution-name mismatch, meaning the import name may not directly match the package distribution name.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'cv2'.\n- The root_cause_hint is import_distribution_name_mismatch.\n\nLimitations: The exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'cv2' when the notebook was executed. This means that the requested import was not available in the current environment. The message identifies the missing import, but it does not by itself show whether the required package is absent or whether the import name differs from the package distribution name. The exact failing cell and dependency files are not available, so the reason for the missing import cannot be determined further."
  },
  3: {
    executionId: 94, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'google'",
    llm: "What happened: The notebook failed because Python could not find the module 'google'.\n\nWhy it happened: The notebook imports 'google', which is not available in the execution environment.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'google'.\n- The root_cause_hint is direct_missing_package.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'google' when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair."
  },
  4: {
    executionId: 118, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'cana'",
    llm: "What happened: The notebook failed because Python could not find the module 'cana'.\n\nWhy it happened: The notebook imports 'cana', which is not available in the execution environment.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'cana'.\n- The root_cause_hint is direct_missing_package.\n\nLimitations: The exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'cana' when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair."
  },
  5: {
    executionId: 172, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'idpgan'",
    llm: "What happened: The notebook execution failed because Python could not find the module 'idpgan'.\n\nWhy it happened: The notebook imports 'idpgan', which is not available in the execution environment.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'idpgan'.\n- The root_cause_hint is direct_missing_package.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'idpgan' when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair."
  },
  6: {
    executionId: 211, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'gnomad'",
    llm: "What happened: The notebook execution failed because Python could not find the 'gnomad' module.\n\nWhy it happened: The notebook imports 'gnomad', which is not installed in the environment.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'gnomad'.\n- The root_cause_hint is direct_missing_package.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'gnomad' when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair."
  },
  7: {
    executionId: 252, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'StringIO'",
    llm: "What happened: The notebook failed because Python could not find the module 'StringIO'.\n\nWhy it happened: The notebook imports 'StringIO', which is not available in the execution environment.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'StringIO'.\n- The root_cause_hint is direct_missing_package.\n\nLimitations: The exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'StringIO' when the notebook was executed. This means that the requested import was not available in the current environment. The message identifies the missing import, but it does not show whether the cause is a missing dependency, an import-name difference, or code written for a different Python environment. The exact failing cell and dependency files are not available, so the cause cannot be determined further."
  },
  8: {
    executionId: 282, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'pygenn'",
    llm: "What happened: The notebook failed because Python could not find the module 'pygenn'.\n\nWhy it happened: The notebook imports 'pygenn', which is not available in the execution environment.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'pygenn'.\n- The root_cause_hint is direct_missing_package.\n\nLimitations: The exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'pygenn' when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair."
  },
  9: {
    executionId: 398, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'celloracle'",
    llm: "What happened: The notebook execution failed because Python could not find the module 'celloracle'.\n\nWhy it happened: The notebook imports 'celloracle', which is not available in the execution environment.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'celloracle'.\n- The root_cause_hint is direct_missing_package.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected.",
    template: "Python could not find the module 'celloracle' when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair."
  },
  10: {
    executionId: 163, subtype: 'wrong_version', errorType: 'ImportError',
    error: "cannot import name 'isshape' from 'scipy.sparse.sputils' (/tmp/.local/lib/python3.10/site-packages/scipy/sparse/sputils.py)",
    llm: "What happened: The notebook failed because it tried to import 'isshape' from 'scipy.sparse.sputils', but that name was not available.\n\nWhy it happened: This is likely caused by a package API or version incompatibility, where the notebook expects a function that is not present in the installed SciPy package version.\n\nEvidence:\n- The error type is ImportError.\n- The error message says that 'isshape' could not be imported from 'scipy.sparse.sputils'.\n- The root_cause_hint is version_or_api_incompatibility.\n\nLimitations: The installed SciPy version and full notebook context are not available, so the exact compatibility mismatch cannot be verified.",
    template: "Python found the SciPy package, but it could not find the name 'isshape' in 'scipy.sparse.sputils'. This is an import error rather than a missing-package error: the notebook expects a name that the installed SciPy version does not provide. The error is therefore consistent with an API or version incompatibility. The installed SciPy version and full notebook context are not available, so this explanation cannot identify the exact compatible version."
  },
  11: {
    executionId: 175, subtype: 'wrong_version', errorType: 'ImportError',
    error: "cannot import name 'cumtrapz' from 'scipy.integrate' (/tmp/.local/lib/python3.10/site-packages/scipy/integrate/__init__.py)",
    llm: "What happened: The notebook failed because it tried to import 'cumtrapz' from 'scipy.integrate', but that name was not available.\n\nWhy it happened: This is likely caused by a package API or version incompatibility, where the notebook expects a function that is not present in the installed SciPy package version.\n\nEvidence:\n- The error type is ImportError.\n- The error message says that 'cumtrapz' could not be imported from 'scipy.integrate'.\n- The root_cause_hint is version_or_api_incompatibility.\n\nLimitations: The installed SciPy version and full notebook context are not available, so the exact compatibility mismatch cannot be verified.",
    template: "Python found the SciPy package, but it could not find the name 'cumtrapz' in 'scipy.integrate'. This is an import error rather than a missing-package error: the notebook expects a name that the installed SciPy version does not provide. The error is therefore consistent with an API or version incompatibility. The installed SciPy version and full notebook context are not available, so this explanation cannot identify the exact compatible version."
  },
  12: {
    executionId: 197, subtype: 'wrong_version', errorType: 'ImportError',
    error: "cannot import name 'VisibleDeprecationWarning' from 'numpy' (/tmp/.local/lib/python3.10/site-packages/numpy/__init__.py)",
    llm: "What happened: The notebook failed because it tried to import 'VisibleDeprecationWarning' from 'numpy', but that name was not available.\n\nWhy it happened: This is likely caused by a package API or version incompatibility, where the notebook expects a warning class that is not present in the installed NumPy package version.\n\nEvidence:\n- The error type is ImportError.\n- The error message says that 'VisibleDeprecationWarning' could not be imported from 'numpy'.\n- The root_cause_hint is version_or_api_incompatibility.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected. The installed NumPy version is not available, so the exact compatibility mismatch cannot be verified.",
    template: "Python found the NumPy package, but it could not find the name 'VisibleDeprecationWarning' in 'numpy'. This is an import error rather than a missing-package error: the notebook expects a name that the installed NumPy version does not provide. The error is therefore consistent with an API or version incompatibility. The installed NumPy version and full notebook context are not available, so this explanation cannot identify the exact compatible version."
  }
};

function createComparisonStudy() {
  const properties = PropertiesService.getScriptProperties();
  if (properties.getProperty('comparison_spreadsheet_id')) {
    throw new Error('This script has already created a study. Run resetComparisonStudy() only if you intentionally want to delete the stored setup reference and create a new one.');
  }

  const spreadsheet = SpreadsheetApp.create('LLM versus template explanation comparison — responses');
  const normalised = spreadsheet.getActiveSheet();
  normalised.setName('Normalised responses');
  normalised.appendRow([
    'participant_id', 'survey_variant', 'example_id',
    'notebook_execution_id', 'subtype', 'explanation_method',
    'programming_experience', 'python_familiarity', 'jupyter_familiarity',
    'dependency_error_familiarity', 'q1_understanding', 'q2_satisfaction',
    'q3_detail', 'q4_completeness', 'q5_usefulness', 'q6_perceived_correctness',
    'feedback_unclear_or_missing', 'feedback_more_helpful'
  ]);
  normalised.setFrozenRows(1);

  const setup = spreadsheet.insertSheet('Study setup');
  setup.appendRow(['Variant', 'Participant URL', 'Edit URL', 'Assignment rule']);
  setup.setFrozenRows(1);

  const formVariants = {};
  Object.keys(ASSIGNMENTS).forEach(function(variant) {
    const form = buildVariantForm_(variant, spreadsheet.getId());
    formVariants[form.getId()] = variant;
    setup.appendRow([
      variant,
      form.getPublishedUrl(),
      form.getEditUrl(),
      'Assign new participant codes round-robin: A, B, C, D, then repeat.'
    ]);
    ScriptApp.newTrigger('onComparisonFormSubmit')
      .forForm(form)
      .onFormSubmit()
      .create();
  });
  setup.autoResizeColumns(1, 4);
  properties.setProperty('comparison_spreadsheet_id', spreadsheet.getId());
  properties.setProperty('comparison_form_variants', JSON.stringify(formVariants));
  Logger.log('Created study spreadsheet: ' + spreadsheet.getUrl());
}

function buildVariantForm_(variant, spreadsheetId) {
  const form = FormApp.create(STUDY_TITLE + ' — variant ' + variant);
  form.setDescription(
    'Thank you for taking part in this short study, run as part of a Master\'s thesis in software engineering.\n\n' +
    'You will see six real notebook errors and one automatically generated explanation for each. Rate only the explanation shown. There are no right or wrong answers.'
  );
  form.setConfirmationMessage('Thank you. Your response has been recorded.');
  form.addCheckboxItem()
    .setTitle('Consent')
    .setChoiceValues(['I agree to take part voluntarily. I understand that no identifying information is requested and that results will be reported only in aggregate.'])
    .setRequired(true);
  form.addTextItem().setTitle('Participant code').setHelpText('Enter the code given to you by the researcher, for example C01.').setRequired(true);
  form.addMultipleChoiceItem().setTitle('Programming experience').setChoiceValues(['None', 'Beginner', 'Intermediate', 'Advanced/Professional']);
  form.addMultipleChoiceItem().setTitle('Python familiarity').setChoiceValues(['Never used it', 'Used it a little', 'Use it regularly']);
  form.addMultipleChoiceItem().setTitle('Jupyter Notebook familiarity').setChoiceValues(['Never used them', 'Used them a few times', 'Use them regularly']);
  form.addMultipleChoiceItem().setTitle('Dependency-error familiarity').setChoiceValues(['Never', 'Occasionally', 'Frequently']);
  form.addSectionHeaderItem().setTitle('Instructions').setHelpText('For each example, do not rate whether you know how to fix the error or whether the notebook was repaired. Rate only how the explanation reads to you.');

  ASSIGNMENTS[variant].forEach(function(pair, index) {
    const exampleId = pair[0];
    const method = pair[1];
    const example = EXAMPLES[exampleId];
    const number = index + 1;
    form.addSectionHeaderItem()
      .setTitle('Example ' + number + ' of 6 — the error')
      .setHelpText(example.errorType + ': ' + example.error);
    form.addSectionHeaderItem()
      .setTitle('The explanation')
      .setHelpText(example[method]);
    form.addGridItem()
      .setTitle('Example ' + number + ': rate the explanation')
      .setRows(SCALE_ROWS)
      .setColumns(SCALE_COLUMNS)
      .setRequired(true);
  });

  form.addParagraphTextItem().setTitle('Optional feedback: Was anything about the explanations unclear or missing?');
  form.addParagraphTextItem().setTitle('Optional feedback: What would make explanations like these more helpful?');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, spreadsheetId);
  return form;
}

function onComparisonFormSubmit(event) {
  const properties = PropertiesService.getScriptProperties();
  const spreadsheetId = properties.getProperty('comparison_spreadsheet_id');
  const formVariants = JSON.parse(properties.getProperty('comparison_form_variants') || '{}');
  const variant = formVariants[event.source.getId()];
  if (!spreadsheetId || !variant) throw new Error('Missing comparison-study setup data.');

  const answers = {};
  event.response.getItemResponses().forEach(function(itemResponse) {
    answers[itemResponse.getItem().getTitle()] = itemResponse.getResponse();
  });
  const common = {
    participantId: answers['Participant code'] || '',
    programmingExperience: answers['Programming experience'] || '',
    pythonFamiliarity: answers['Python familiarity'] || '',
    jupyterFamiliarity: answers['Jupyter Notebook familiarity'] || '',
    dependencyErrorFamiliarity: answers['Dependency-error familiarity'] || '',
    feedbackUnclear: answers['Optional feedback: Was anything about the explanations unclear or missing?'] || '',
    feedbackHelpful: answers['Optional feedback: What would make explanations like these more helpful?'] || ''
  };
  const output = SpreadsheetApp.openById(spreadsheetId).getSheetByName('Normalised responses');
  ASSIGNMENTS[variant].forEach(function(pair, index) {
    const exampleId = pair[0];
    const method = pair[1];
    const example = EXAMPLES[exampleId];
    const ratings = answers['Example ' + (index + 1) + ': rate the explanation'] || [];
    output.appendRow([
      common.participantId, variant, exampleId,
      example.executionId, example.subtype, method,
      common.programmingExperience, common.pythonFamiliarity, common.jupyterFamiliarity,
      common.dependencyErrorFamiliarity,
      ratingNumber_(ratings[0]), ratingNumber_(ratings[1]), ratingNumber_(ratings[2]),
      ratingNumber_(ratings[3]), ratingNumber_(ratings[4]), ratingNumber_(ratings[5]),
      common.feedbackUnclear, common.feedbackHelpful
    ]);
  });
}

function ratingNumber_(answer) {
  return answer ? Number(String(answer).charAt(0)) : '';
}

function resetComparisonStudy() {
  // This does not delete forms or spreadsheets. It only removes this script's
  // stored references, allowing a deliberate fresh setup after confirmation.
  PropertiesService.getScriptProperties().deleteAllProperties();
}
