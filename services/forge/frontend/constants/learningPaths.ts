// The four paths named in the platform plan. Descriptions only — none of these
// run yet, and the pages that render them say so.

export interface LearningPath {
  slug: string;
  title: string;
  summary: string;
  question: string;
  example: string;
  steps: { title: string; detail: string }[];
}

export const LEARNING_PATHS: LearningPath[] = [
  {
    slug: "classification",
    title: "Classification",
    summary: "Sort rows into categories you already know the names of.",
    question: "Which bucket does this row belong to?",
    example:
      "Given a well's readings, flag it as needing maintenance or not. Given a support ticket, route it to the right team.",
    steps: [
      {
        title: "Pick a dataset",
        detail: "Any CSV you've uploaded, or one of the bundled samples.",
      },
      {
        title: "Choose the column to predict",
        detail: "The label — the column holding the category, e.g. pass/fail.",
      },
      {
        title: "Choose the columns to learn from",
        detail: "The features. Forge will suggest which ones actually carry signal.",
      },
      {
        title: "Train and score",
        detail: "Split the data, fit a model, and report accuracy on the held-back rows.",
      },
      {
        title: "Read the result",
        detail:
          "A confusion matrix plus which columns mattered most, in plain language.",
      },
    ],
  },
  {
    slug: "regression",
    title: "Regression",
    summary: "Predict a number rather than a category.",
    question: "How much, given everything else in the row?",
    example:
      "Estimate monthly production volume from operating conditions, or project a cost from job parameters.",
    steps: [
      { title: "Pick a dataset", detail: "The rows you want to learn the relationship from." },
      {
        title: "Choose the number to predict",
        detail: "The target column. It has to be numeric.",
      },
      {
        title: "Choose the columns to learn from",
        detail: "Text columns get encoded automatically so you don't have to prepare them.",
      },
      {
        title: "Train and score",
        detail: "Fit the model and report error on rows the model never saw.",
      },
      {
        title: "Read the result",
        detail: "Predicted against actual, plus how much each column moved the prediction.",
      },
    ],
  },
  {
    slug: "time-series",
    title: "Time series",
    summary: "Use the shape of the past to say something about the near future.",
    question: "Where is this heading over the next N periods?",
    example:
      "Forecast next quarter's monthly sales, or spot the week a metric broke its usual pattern.",
    steps: [
      {
        title: "Pick a dataset with a date column",
        detail: "One row per period. The Monthly Sales sample is shaped for this.",
      },
      {
        title: "Point at the date and the value",
        detail: "Which column is time, and which column is the thing being measured.",
      },
      {
        title: "Set the horizon",
        detail: "How far ahead to forecast, and how the history should be split for testing.",
      },
      {
        title: "Fit and back-test",
        detail: "Forecast a stretch of history that's held back, then compare against what happened.",
      },
      {
        title: "Read the result",
        detail: "A chart of history and forecast with a confidence band, plus flagged anomalies.",
      },
    ],
  },
  {
    slug: "llm-playground",
    title: "LLM playground",
    summary: "Ask questions of your data in plain English.",
    question: "What does this dataset actually say?",
    example:
      "\"Which three months had the steepest drop?\" answered against the CSV you just uploaded, with the rows it used.",
    steps: [
      { title: "Pick a dataset", detail: "The model only sees the dataset you select." },
      {
        title: "Ask a question",
        detail: "Plain English. No query language, no column names to memorise.",
      },
      {
        title: "See the working",
        detail:
          "The answer comes with the rows and the calculation behind it, so it can be checked.",
      },
      {
        title: "Save what's useful",
        detail: "Keep an answer as a note on the dataset, or push it into a workflow step.",
      },
    ],
  },
];

export function findLearningPath(slug: string): LearningPath | undefined {
  return LEARNING_PATHS.find((path) => path.slug === slug);
}
