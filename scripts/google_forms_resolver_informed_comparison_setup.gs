/*
 * Creates the RQ1 resolver-informed comparison requested by the supervisor.
 *
 * Run createResolverInformedComparisonStudy() once in a NEW Apps Script
 * project. It creates four blinded Google Forms, a central Google Sheet, and
 * automatic normalised result logging. The normalised sheet deliberately does
 * not include a submission timestamp.
 */

const RQ1_TITLE = 'How people judge explanations of programming errors';
const RQ1_METHODS = ['llm', 'resolver_template'];
const RQ1_SCALE_COLUMNS = [
  '1 — Strongly disagree', '2 — Disagree',
  '3 — Neither agree nor disagree', '4 — Agree', '5 — Strongly agree'
];
const RQ1_SCALE_ROWS = [
  'Q1. From this explanation, I understand why the notebook failed.',
  'Q2. This explanation is satisfying.',
  'Q3. This explanation has enough detail.',
  'Q4. This explanation seems complete.',
  'Q5. This explanation is useful for understanding what went wrong.',
  'Q6. This explanation seems correct, based on the error shown.'
];

// Each participant rates four cases: two LLM explanations and two deterministic,
// resolver-informed explanations. Across the four variants every case occurs in
// both conditions, but a participant never sees both forms of one case.
const RQ1_ASSIGNMENTS = {
  A: [[1, 'llm'], [2, 'resolver_template'], [3, 'llm'], [4, 'resolver_template']],
  B: [[1, 'resolver_template'], [2, 'llm'], [3, 'resolver_template'], [4, 'llm']],
  C: [[3, 'llm'], [4, 'resolver_template'], [1, 'llm'], [2, 'resolver_template']],
  D: [[3, 'resolver_template'], [4, 'llm'], [1, 'resolver_template'], [2, 'llm']]
};

const RQ1_CASES = {
  1: {
    executionId: 62, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'sklearn'",
    llm: "What happened: The notebook failed because Python could not find the module 'sklearn'.\n\nWhy it happened: The notebook imports 'sklearn', which is not available in the execution environment. The classifier also marks this as an import/distribution-name mismatch, meaning the import name may not directly match the package distribution name.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'sklearn'.\n- The root_cause_hint is import_distribution_name_mismatch.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected.",
    resolver_template: "Python could not find the import 'sklearn'. The resolver verified that the PyPI distribution 'scikit-learn' provides this import. This distribution is not available in the current execution environment. The available metadata does not show why it was absent or identify the exact failing notebook cell."
  },
  2: {
    executionId: 79, subtype: 'missing_package', errorType: 'ModuleNotFoundError',
    error: "No module named 'cv2'",
    llm: "What happened: The notebook failed because Python could not find the module 'cv2'.\n\nWhy it happened: The notebook imports 'cv2', which is not available in the execution environment. The classifier also marks this as an import/distribution-name mismatch, meaning the import name may not directly match the package distribution name.\n\nEvidence:\n- The error type is ModuleNotFoundError.\n- The error message says: No module named 'cv2'.\n- The root_cause_hint is import_distribution_name_mismatch.\n\nLimitations: The exact failing cell and dependency files cannot be inspected.",
    resolver_template: "Python could not find the import 'cv2'. The resolver verified that the PyPI distribution 'opencv-python' provides this import. This distribution is not available in the current execution environment. The available metadata does not show why it was absent or identify the exact failing notebook cell."
  },
  3: {
    executionId: 175, subtype: 'wrong_version', errorType: 'ImportError',
    error: "cannot import name 'cumtrapz' from 'scipy.integrate' (/tmp/.local/lib/python3.10/site-packages/scipy/integrate/__init__.py)",
    llm: "What happened: The notebook failed because it tried to import 'cumtrapz' from 'scipy.integrate', but that name was not available.\n\nWhy it happened: This is likely caused by a package API or version incompatibility, where the notebook expects a function that is not present in the installed SciPy package version.\n\nEvidence:\n- The error type is ImportError.\n- The error message says that 'cumtrapz' could not be imported from 'scipy.integrate'.\n- The root_cause_hint is version_or_api_incompatibility.\n\nLimitations: The installed SciPy version and full notebook context are not available, so the exact compatibility mismatch cannot be verified.",
    resolver_template: "Python found SciPy, but the installed version does not provide 'cumtrapz' in 'scipy.integrate'. The resolver's verified compatibility evidence identifies SciPy versions below 1.14.0 as compatible with this import. The error is therefore a version or API incompatibility, not a missing-package error. The available metadata does not show the exact installed version."
  },
  4: {
    executionId: 197, subtype: 'wrong_version', errorType: 'ImportError',
    error: "cannot import name 'VisibleDeprecationWarning' from 'numpy' (/tmp/.local/lib/python3.10/site-packages/numpy/__init__.py)",
    llm: "What happened: The notebook failed because it tried to import 'VisibleDeprecationWarning' from 'numpy', but that name was not available.\n\nWhy it happened: This is likely caused by a package API or version incompatibility, where the notebook expects a warning class that is not present in the installed NumPy package version.\n\nEvidence:\n- The error type is ImportError.\n- The error message says that 'VisibleDeprecationWarning' could not be imported from 'numpy'.\n- The root_cause_hint is version_or_api_incompatibility.\n\nLimitations: Only metadata is available, so the exact failing cell and dependency files cannot be inspected. The installed NumPy version is not available, so the exact compatibility mismatch cannot be verified.",
    resolver_template: "Python found NumPy, but the installed version does not provide 'VisibleDeprecationWarning'. The resolver's verified compatibility evidence identifies NumPy versions below 2.0.0 as compatible with this import. The error is therefore a version or API incompatibility, not a missing-package error. The available metadata does not show the exact installed version."
  }
};

function createResolverInformedComparisonStudy() {
  const properties = PropertiesService.getScriptProperties();
  if (properties.getProperty('rq1_resolver_comparison_spreadsheet_id')) {
    throw new Error('This project has already created the resolver-informed comparison study.');
  }

  const spreadsheet = SpreadsheetApp.create('RQ1 resolver-informed explanation comparison — responses');
  const results = spreadsheet.getActiveSheet();
  results.setName('Normalised responses');
  results.appendRow([
    'participant_id', 'survey_variant', 'comparison', 'case_id',
    'notebook_execution_id', 'subtype', 'explanation_method',
    'programming_experience', 'python_familiarity', 'jupyter_familiarity',
    'dependency_error_familiarity', 'q1_understanding', 'q2_satisfaction',
    'q3_detail', 'q4_completeness', 'q5_usefulness', 'q6_perceived_correctness',
    'feedback_unclear_or_missing', 'feedback_more_helpful'
  ]);
  results.setFrozenRows(1);

  const setup = spreadsheet.insertSheet('Study setup');
  setup.appendRow(['Variant', 'Participant URL', 'Edit URL', 'Assignment rule']);
  setup.setFrozenRows(1);
  const formVariants = {};
  Object.keys(RQ1_ASSIGNMENTS).forEach(function(variant) {
    const form = buildRq1Form_(variant);
    formVariants[form.getId()] = variant;
    setup.appendRow([
      variant, form.getPublishedUrl(), form.getEditUrl(),
      'Assign participant codes round-robin: R01 → A, R02 → B, R03 → C, R04 → D, then repeat.'
    ]);
    ScriptApp.newTrigger('onRq1ResolverComparisonSubmit')
      .forForm(form).onFormSubmit().create();
  });
  setup.autoResizeColumns(1, 4);
  properties.setProperty('rq1_resolver_comparison_spreadsheet_id', spreadsheet.getId());
  properties.setProperty('rq1_resolver_comparison_form_variants', JSON.stringify(formVariants));
  Logger.log('Created study spreadsheet: ' + spreadsheet.getUrl());
}

function buildRq1Form_(variant) {
  const form = FormApp.create(RQ1_TITLE + ' — resolver comparison variant ' + variant);
  form.setDescription(
    'Thank you for taking part in this short study, run as part of a Master\'s thesis in software engineering.\n\n' +
    'You will see four real notebook errors and one automatically generated explanation for each. Rate only the explanation shown. There are no right or wrong answers.'
  );
  form.setConfirmationMessage('Thank you. Your response has been recorded.');
  form.addCheckboxItem().setTitle('Consent')
    .setChoiceValues(['I agree to take part voluntarily. I understand that no identifying information is requested and that results will be reported only in aggregate.'])
    .setRequired(true);
  form.addTextItem().setTitle('Participant code').setHelpText('Enter the code given to you by the researcher, for example R01.').setRequired(true);
  form.addMultipleChoiceItem().setTitle('Programming experience').setChoiceValues(['None', 'Beginner', 'Intermediate', 'Advanced/Professional']);
  form.addMultipleChoiceItem().setTitle('Python familiarity').setChoiceValues(['Never used it', 'Used it a little', 'Use it regularly']);
  form.addMultipleChoiceItem().setTitle('Jupyter Notebook familiarity').setChoiceValues(['Never used them', 'Used them a few times', 'Use them regularly']);
  form.addMultipleChoiceItem().setTitle('Dependency-error familiarity').setChoiceValues(['Never', 'Occasionally', 'Frequently']);
  form.addSectionHeaderItem().setTitle('Instructions').setHelpText('Do not rate whether you personally know how to fix an error. Rate only how clear, detailed, complete, useful, and correct the explanation appears.');

  RQ1_ASSIGNMENTS[variant].forEach(function(pair, index) {
    const caseId = pair[0];
    const method = pair[1];
    const record = RQ1_CASES[caseId];
    const number = index + 1;
    form.addSectionHeaderItem().setTitle('Example ' + number + ' of 4 — the error')
      .setHelpText(record.errorType + ': ' + record.error);
    form.addSectionHeaderItem().setTitle('The explanation').setHelpText(record[method]);
    form.addGridItem().setTitle('Example ' + number + ': rate the explanation')
      .setRows(RQ1_SCALE_ROWS).setColumns(RQ1_SCALE_COLUMNS).setRequired(true);
  });
  form.addParagraphTextItem().setTitle('Optional feedback: Was anything about the explanations unclear or missing?');
  form.addParagraphTextItem().setTitle('Optional feedback: What would make explanations like these more helpful?');
  return form;
}

function onRq1ResolverComparisonSubmit(event) {
  const properties = PropertiesService.getScriptProperties();
  const spreadsheetId = properties.getProperty('rq1_resolver_comparison_spreadsheet_id');
  const variants = JSON.parse(properties.getProperty('rq1_resolver_comparison_form_variants') || '{}');
  const variant = variants[event.source.getId()];
  if (!spreadsheetId || !variant) throw new Error('Missing resolver-comparison setup data.');

  const answers = {};
  event.response.getItemResponses().forEach(function(itemResponse) {
    answers[itemResponse.getItem().getTitle()] = itemResponse.getResponse();
  });
  const resultSheet = SpreadsheetApp.openById(spreadsheetId).getSheetByName('Normalised responses');
  RQ1_ASSIGNMENTS[variant].forEach(function(pair, index) {
    const caseId = pair[0];
    const method = pair[1];
    const record = RQ1_CASES[caseId];
    const ratings = answers['Example ' + (index + 1) + ': rate the explanation'] || [];
    resultSheet.appendRow([
      answers['Participant code'] || '', variant, 'resolver_informed_rq1', caseId,
      record.executionId, record.subtype, method,
      answers['Programming experience'] || '', answers['Python familiarity'] || '',
      answers['Jupyter Notebook familiarity'] || '', answers['Dependency-error familiarity'] || '',
      ratingNumber_(ratings[0]), ratingNumber_(ratings[1]), ratingNumber_(ratings[2]),
      ratingNumber_(ratings[3]), ratingNumber_(ratings[4]), ratingNumber_(ratings[5]),
      answers['Optional feedback: Was anything about the explanations unclear or missing?'] || '',
      answers['Optional feedback: What would make explanations like these more helpful?'] || ''
    ]);
  });
}

function ratingNumber_(answer) {
  return answer ? Number(String(answer).charAt(0)) : '';
}
