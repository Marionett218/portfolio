[← Back to the portfolio](../../README.md) | [Русская версия](README_Ru.md)

# STEPPE Navigator — Career Guidance Analytics for Mangystau

Interactive BI project based on a regional career-guidance pilot conducted in Mangystau Region, Kazakhstan, from March to May 2026.

The analytical cohort contains completed questionnaire sessions for **40,168 students from 148 public schools**.

<picture>
  <img src="assets/steppe_navigator_dashboard_preview.jpg" alt="STEPPE Navigator Plans after school dashboard preview">
</picture>

[View the interactive dashboards on Tableau Public](https://public.tableau.com/app/profile/evgeny.vinogradov/viz/SteppeNavigator_Mangistauresults2026/sheet0_1)

The dashboards are presented in Russian because they were designed around the language and terminology used by the regional education stakeholders and the source questionnaire.

## Business context

STEPPE Navigator is a career-guidance platform intended to support school career counsellors. During the pilot, trained staff in participating public schools used the platform to conduct student diagnostics across Mangystau Region.

The original analysis was developed as part of pilot reporting. Its results were presented to public education stakeholders. The Tableau workbook published here was created afterwards as a portfolio demonstration and was not itself used in those presentations.

The pilot produced a large operational dataset to explore four management questions:

- how career-guidance diagnostics progressed across districts and grades;
- how students' plans after school differed by territory and grade;
- how certain students were about their educational choices;
- what students' intended study locations could indicate about future educational migration.

If the pilot develops into recurring work, the same analytical views could be refreshed from the beginning of a semester or academic year and used as a monitoring instrument.

## Analytical questions

The published solution is designed to help education managers investigate:

- How many students and schools participated in each district?
- How did participation and diagnostic completion accumulate during the pilot?
- Where did students stop between registration, starting diagnostics, and receiving a report?
- How did plans for university, college, work, military service, a gap year, or an undecided path vary across districts and grades?
- Which districts differed most from the regional average?
- How many students had one preferred option, several options, or no defined choice?
- Which criteria did students report considering when choosing a university or college?
- Where did students intend to study: within Mangystau, elsewhere in Kazakhstan, or abroad?

## Dashboard structure

### Coverage and diagnostic progress

Shows participating students by grade and district, geographic coverage, cumulative completion of diagnostic stages, and the distribution of completion statuses across districts.

### Plans after school

Compares post-school plans by grade and district. A separate view shows each district's deviation from the regional average in percentage points, making territorial differences easier to identify.

### Educational choice

Explores the certainty of educational choice, criteria students reported considering when choosing an institution, and intended study geography. Results can be filtered by district and grade.

## Selected observations from the pilot

Unless stated otherwise, the following results describe the full published cohort with all districts and grades selected:

- Among students planning to attend university, **56.0%** intended to study in another region of Kazakhstan and **14.4%** abroad; **15.2%** intended to remain in Mangystau, while **14.4%** had not selected a study location. Among students planning to attend college, the corresponding shares were **33.0%**, **6.8%**, **42.1%**, and **18.0%**. The difference makes educational migration a material management question, especially for university-oriented students.
- Patterns varied across territories. University orientation was **11.46 percentage points above** the regional average in Mangystau District and **10.74 pp above** in Tupkaragan District, while Karakiya District was **7.01 pp below**. College orientation was above the regional average in Karakiya District (**+5.02 pp**) and Zhanaozen (**+4.99 pp**), and below it in Mangystau District (**−8.55 pp**) and Tupkaragan District (**−6.01 pp**). These contrasts identify locations for follow-up analysis. Understanding their causes could help the education authority identify local practices that may be transferable to neighbouring districts.
- A single preferred option had been selected by **45.8%** of university-oriented students and **41.8%** of college-oriented students. The remaining respondents reported several alternatives or no defined choice: approximately **54%** of the university group and **58%** of the college group. This supports treating choice certainty as a useful monitoring indicator.
- Within the university-oriented group, the share reporting one preferred option was higher in each successive grade: **36.0%** in grade 8, **41.2%** in grade 9, **52.9%** in grade 10, and **68.9%** in grade 11. This pattern is consistent with choice certainty increasing progressively in later grades. This is a cross-sectional comparison between grades; repeated collection of comparable data year after year would be needed to track change within the same cohort. College-oriented results for grades 10–11 are excluded from this comparison because the respondent counts in those subgroups are naturally low.
- Abilities and interests were the most frequently reported consideration when choosing an institution: **69.6%** for the university group and **60.9%** for the college group. University-oriented students also selected the number of grants (**35.3%**) and institutional ranking (**34.5%**) more often than college-oriented students (**21.3%** and **21.4%**, respectively). The share who found it difficult to answer was more than twice as high among students planning to attend college: **16.5%** versus **7.6%**. Explaining this difference would require additional research.

The criteria question allowed multiple responses, so its percentages are not intended to sum to 100%. These observations identify management topics for further research and do not establish the causes of students' choices.

## How the analysis can support management

### Monitoring career-guidance delivery

The current dashboards provide a retrospective view of the pilot. With regular data refreshes, the same logic could show the current position from the beginning of a semester or academic year. Regional managers could use completion and participation patterns to identify districts requiring follow-up, coordinate with district education administrations, and direct support through school leadership and career-guidance staff.

### Investigating differences in educational trajectories

District-level deviations provide signals for deeper investigation. For example, if regional policy seeks to increase enrolment in vocational education, districts with a comparatively high college orientation could be studied to understand local practices, information channels, access to education, local business involvement, existing cooperation between schools and colleges, and other factors. Findings from that investigation could then inform measures in other districts.

### Tracking potential educational migration

Intended study geography provides an early indicator of students' orientation toward staying in the region, moving elsewhere in Kazakhstan, or studying abroad. Repeated measurements could help monitor how students perceive Mangystau's educational image and how the attractiveness of local education changes alongside measures aimed at reforming or promoting it.

### Assessing the maturity of educational choice

The share of students with a defined choice, several alternatives, or no clear option can serve as one monitoring indicator for long-term career-guidance work. With comparable cohorts and consistent measurement, it could support before-and-after assessment of a pilot intervention or comparison of different approaches across districts.

## Data and analytical scope

- Source: a working MySQL database dump from the STEPPE Navigator platform.
- Working analytical environment: PostgreSQL, following migration through SQLines and reconciliation of the transferred structure.
- Period: the operational pilot window from March to May 2026.
- Cohort: completed questionnaire sessions associated with public schools participating in the pilot.
- Training and test activity was excluded using the pilot period and school identifiers.
- Questionnaire reference data was used to interpret stored question and option identifiers.
- Public school metadata used for district-level aggregation was compiled from open sources.
- The public dashboards present results at district and grade level; individual-school results are not shown.
- Free-text questionnaire responses are excluded from the published extract, and the table linking technical identifiers to personal records is absent from the public workbook.

## Interpretation boundaries

- The data describe an operational pilot cohort. No probability-sampling design or statistical weights were applied.
- The scale and territorial reach support robust analysis of STEPPE Navigator pilot participants: approximately 40,200 students in grades 8–11 from 148 public schools completed the diagnostic process, representing about 86% of the estimated target-group population. This high coverage provides a broad picture of the pilot participants; strict statistical representativeness was not assessed separately.
- District differences identify areas for investigation. Explanatory research is required before attributing those differences to school practices, local conditions, or policy effects.
- Intended study geography is a measure of stated plans at the time of the questionnaire. Actual enrolment and migration outcomes require follow-up data.
- The current workbook contains one pilot period. Statements about change over time require repeated measurements using comparable definitions and cohorts.
- Evaluation of a career-guidance intervention requires an agreed design, such as comparable baseline and follow-up measurements or a controlled pilot.
- Assessing structural alignment with the labour market requires additional data on regional vacancies, shortage occupations, education capacity, enrolment, and graduate employment.

## My role and AI-assisted workflow

My contribution included:

- interpreting the source database using knowledge of the product, diagnostic process, pilot timeline, and operational context;
- defining the pilot cohort and excluding training and test activity;
- formulating the analytical questions and interpretation boundaries;
- selecting the management views and comparison levels;
- designing and assembling the Tableau dashboards through the Tableau interface;
- reviewing results, investigating anomalies, and accepting the final analytical presentation.

The work was performed in close collaboration with LLM tools. The LLM generated the more complex SQL transformations, supported schema exploration, proposed validation checks, and provided recommendations during visualization design. I defined the questions and requirements, supplied business context, reviewed outputs for plausibility and consistency, and made the analytical and presentation decisions. The project is presented as an AI-assisted analytical workflow; the SQL is not represented as manually authored code.

## What this project demonstrates

- Translating a public-sector management context into analytical questions
- Cohort definition and interpretation of an unfamiliar operational database
- Analytical comparison across districts and grades
- Tableau dashboard and information design
- Clear separation of observed results, possible management use, and future analytical extensions
- Responsible disclosure of sampling, causal, migration, and AI-assistance boundaries

## Current status

The three-dashboard Tableau Public workbook is published as a retrospective demonstration of the 2026 pilot. The next analytical layer could connect repeated career-guidance measurements with regional education capacity and labour-market demand.
