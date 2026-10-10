# AI-assisted development — AlphaLab Intelligence

>Find Russian text below

This document describes the principles of the AI-assisted process used for data analysis and visualization development in the AlphaLab Intelligence project. The examples below relate to Search Demand as the first analytical layer, but the principles apply to the project as a whole.  
The document may be expanded as the project develops.

## 1. The role of AI in the project

In AlphaLab Intelligence, ChatGPT and Codex are used for technical implementation, exploring alternatives, and diagnosing problems. SQL queries, Python scripts, and tests are created with the help of LLMs. Tableau, by contrast, is configured manually following workflows suggested by ChatGPT: the author creates worksheets and dashboards, sets up filters and actions, runs updates, and checks the result in the working interface.

Substantive responsibility remains with the project author. The author formulates the business problem, defines the meaning of metrics and acceptable constraints, chooses architectural and analytical solutions, sets acceptance criteria, runs the implementation locally, and decides whether to accept the result, return it for revision, or change the approach.

## 2. Actual working cycle

Work starts with a business task or analytical problem. The author decides what result is needed and what it should mean: for example, how to aggregate search interest by diagnostic area, how to compare regions, which metrics Tableau needs, and so on.

The alternatives are then discussed with ChatGPT. At this stage, AI acts as a technical counterpart: it helps identify ambiguities, compare data-model, calculation, and architecture options, and assess the consequences of a decision. The first suggestion is not treated as correct by default. It may be rejected or changed if it does not fit the meaning of the task or has other substantive drawbacks.

Once an approach is chosen, a technical specification is prepared: the goal, scope of changes, expected grain, inputs and outputs, checks, and acceptance criteria. SQL, Python, and tests are created by Codex/LLMs. In Tableau, ChatGPT recommendations are implemented manually by the author.

The resulting implementation is run locally. Actual results are brought back into the dialogue: PostgreSQL errors, row counts, tables and query results, test results, query plans and execution times, `git diff`, screenshots, and Tableau behavior. AI cannot declare a task complete on its own: the result is accepted only after the author checks it in the working system.

During verification, the grain, meaning of aggregations, control totals, date ranges, and specific values are checked. For critical calculations, independent recalculations from a lower data layer were used. In Tableau, aggregation levels, metric aggregation, filters, tooltips, actions, and performance were checked separately.

If an implementation works formally but violates the intended semantics, produces suspicious values, creates unacceptable load, or is inconvenient in the real interface, it is returned for revision. After correction, the cycle is repeated.

Only after acceptance are changes prepared for Git. The set of changed files and the diff are reviewed; for changes to stable project rules, the need to update documentation is assessed separately.

```text
business task / analytical problem
→ discussion of options with ChatGPT
→ author decision
→ technical specification
→ SQL / Python / tests via Codex/LLM or manual Tableau configuration
→ local execution
→ verification of data, calculations, tests, and interface
→ revision or acceptance
→ Git and documentation
```

## 3. Responsibility split

| Area | Author | ChatGPT / Codex |
|---|---|---|
| Business problem definition | Formulates the question, goal, constraints, and acceptance criteria | Helps decompose the task and identify ambiguities |
| Analytical methodology | Defines the meaning of metrics and makes methodological decisions | Suggests calculation options and helps assess their consequences |
| Architecture | Chooses the approach and acceptable trade-offs | Suggests data models and technical options |
| Technical specification | Approves the grain, inputs, outputs, checks, and scope of changes | Helps turn the decision into an implementation plan |
| SQL / Python / tests | Usually does not write the main implementation manually | Creates the main implementation |
| Tableau | Manually implements and checks the interface | Suggests visual and technical solutions and helps diagnose problems |
| Local execution | Runs code, migrations, tests, and queries | Helps interpret actual output and errors |
| Result verification | Checks data, metric meaning, independent reconciliations, performance, and Tableau | Helps design checks and investigate discrepancies |
| Acceptance | Accepts, rejects, or returns the result for revision | Does not make the acceptance decision for the author |
| Git and documentation | Reviews the set of changes and decides what to commit | Prepares changes and identifies possible documentation impact |

I did not perform a full traditional line-by-line review of SQL/Python. Control was based primarily on analytical meaning, data structure, actual outputs, independent reconciliations, tests, performance, and system behavior.

## 4. Full-cycle example: synthetic Search Demand dataset

### Problem

Designing Search Demand and Tableau required regional data with a long time history, while collecting such data manually would have taken substantial time. Because the task was being carried out to build the portfolio rather than to solve a live business problem, the decision was made to work with synthetic data. If a real commissioned project and funding become available, real data can be obtained quickly through the Yandex Cloud API and integrated into the existing tables and visualizations.

### Author decision

A temporary synthetic DEV dataset with clear boundaries was chosen. National monthly Yandex values had to be based on factual Wordstat values collected manually for all selected keywords and had to remain exact after distribution across regions. Regional profiles were synthetic, but they were not allowed to be simple proportional copies of a single distribution. Google was allowed only as a fully synthetic source and was used solely to configure the `source` filter. The timeline was shifted 100 years into the past so that demonstration data could not be mistaken for live data. This also addressed safe re-execution: the generator would not be able to duplicate or overwrite an existing dataset.

### AI work

ChatGPT helped formalize the requirements, while Codex/LLMs implemented the Python generator, loading, and tests. Bulk generation was performed by ordinary Python code; the LLM did not participate in generating regional rows at runtime, in order to avoid spending tokens.

### Verification

The final dataset contained 83 regions, 85 keywords, 80 months, and two sources — 1,128,800 rows. Checks covered grain uniqueness, expected volume, exact reconciliation of regional Yandex totals with the original national Wordstat values, and diversity of regional profiles. A repeated run had to recognize the already existing valid dataset and avoid adding duplicates.

### Outcome

The dataset was accepted as a tool for developing and testing Tableau, not as a model of the real regional market. This limitation was preserved both in the documentation and in the public presentation of the case.

## 5. Full-cycle example: redesign due to performance

### Problem

After Search Demand was connected to Tableau, some scenarios became practically unusable because of performance. The problem was identified through the behavior of the working system: visualizations refreshed too slowly, and free disk space was decreasing substantially, which was visible at the operating-system level. This became the reason to stop further interface development and separately investigate the query execution path.

### Author decision

The author proposed changing the responsibility boundary between Tableau and PostgreSQL: move heavy and repeated calculations out of the interactive path into specialized marts, while leaving filtering, user selection, and visual presentation in Tableau. Instead of one universal object, the decision was made to create small `VIEW` / `MATERIALIZED VIEW` objects for specific scenarios.

### AI work

ChatGPT helped examine the options and design the mart architecture, while Codex/LLMs implemented the SQL changes and checks. In particular, some marts were built so PostgreSQL could restrict data by source, diagnostic area, or period before expensive joins and aggregations. As a result, instead of one table, 4 `VIEW` and 2 `MATERIALIZED VIEW` objects were created.

### Verification

After the changes, control queries were run again. For one recorded scenario, query execution time decreased from approximately 819 ms to 86.8 ms. After the SQL checks, the solution was tested again in Tableau as the final interface, where filter behavior was also visibly faster. The resulting behavior was accepted as sufficient for the current prototype.

### Outcome

The performance problem led not to a cosmetic Tableau adjustment, but to a redesign of the `mart` layer architecture. What matters in this case is the cycle itself: a human noticed an operational problem, initiated an investigation, proposed an architectural change, AI helped implement it, and the effect was verified through measurement and actual Tableau behavior.

## 6. How AI-assisted implementation quality is controlled

Control is built around several independent checkpoints.

- **The working system is checked, not the AI report.** Code, migrations, queries, and tests are run locally; Tableau changes are implemented and checked manually.
- **Grain and analytical meaning are checked.** The number of rows or marks, aggregation level, and metric meaning must match the original specification. Suspicious values are investigated through concrete examples rather than accepted simply because the formula works formally.
- **Source and result are reconciled.** For synthetic Yandex data, the sum across regions must exactly reproduce the original national value. Independent calculations were used for critical marts; for example, all 498 rows of `mart.search_demand_keyword_growth` were recalculated separately from staging with no discrepancies in the key metrics.
- **Tests are supplemented by behavioral checks.** Passing tests does not replace checking business meaning, performance, and Tableau behavior.
- **Unsuitable solutions are returned for revision.** This applies both to code and to Tableau recommendations: an AI recommendation is not considered correct until it has been checked in the real interface and against actual data.
- **The scope of changes is checked before committing.** On one occasion, AI prepared documentation changes based on outdated copies and removed current fragments. The error was caught before commit. Since then, only the current version is used for canonical documentation, and unexpected changes in the diff are treated as a blocking issue.

## 7. Limitations of the approach

This project is not an example of independently writing all SQL and Python by hand. Most SQL, Python, and tests were created with ChatGPT/Codex, and I did not perform a full traditional line-by-line code review.

Therefore, passing tests or successfully executing SQL is not treated as automatic proof that a solution is correct. AI can technically implement an incorrectly specified metric, miss a side effect, or propose a plausible but unsuitable architectural solution. In Tableau, AI also cannot see the workbook’s internal state or the result of its recommendation until a human executes it and returns the actual outcome.

My area of responsibility is problem definition, analytical meaning, data structure, choice of solutions, verification criteria, and acceptance of the actual result. In this sense, AlphaLab Search Demand should be viewed as an example of development with AI assistance, not as a demonstration of independent manual programming.

>Russian text

Данный документ описывает принципы AI-ассистируемого процесса анализа данных и создания визуализации в проекте AlphaLab Intelligence. Приведенные примеры относятся к части Search Demand как первому слою анализа, но принципы остаются верными для всего проекта. 
В случае необходимости, файл будет дополнен при дальнейшей работе. 

## 1. Роль AI в проекте

В AlphaLab Intelligence ChatGPT и Codex используются для технической реализации, разбора вариантов и диагностики проблем. SQL-запросы, Python-скрипты и тесты создаются с помощью LLM. Tableau, напротив, настраивается вручную по алгоритмам, предлагаемым ChatGPT: автор создаёт листы и дашборды, задаёт фильтры и действия, запускает обновления и проверяет результат в работающем интерфейсе.

Содержательная ответственность остаётся у автора проекта. Он формулирует бизнес-задачу, определяет смысл показателей и допустимые ограничения, выбирает архитектурные и аналитические решения, задаёт критерии приёмки, запускает реализацию локально и решает, принимать результат, возвращать его на исправление или менять подход.

## 2. Фактический рабочий цикл

Работа начинается с бизнес-задачи или аналитической проблемы. Автор решает, какой результат нужен и что он должен означать: например, как агрегировать поисковый интерес по диагностическим направлениям, как сравнивать регионы, какие показатели нужны Tableau и т.д.

Далее варианты обсуждаются с ChatGPT. На этом этапе AI выступает как технический собеседник: помогает выявить неоднозначности, сравнить варианты модели данных, расчётов и архитектуры, проверить последствия решения. Первое предложение не считается правильным по умолчанию. Оно может быть отклонено или изменено, если не соответствует смыслу задачи или имеет иные недостатки по сути.

После выбора подхода формируется техническая постановка: цель, границы изменений, ожидаемый grain, входы и выходы, проверки и критерии приёмки. SQL, Python и тесты создаются Codex/LLM. В Tableau рекомендации ChatGPT реализуются автором вручную.

Полученная реализация запускается локально. В диалог возвращаются фактические результаты: ошибки PostgreSQL, число строк, таблицы и выборки, результаты тестов, планы и время запросов, `git diff`, скриншоты и поведение Tableau. AI не может самостоятельно объявить задачу выполненной: результат принимается только после проверки автором в рабочей системе.

В ходе проеврки сверяется grain, смысл агрегаций, контрольные суммы, диапазоны дат и конкретные значения. Для критичных расчётов использовались независимые пересчёты из более низкого слоя данных. В Tableau отдельно проверялись уровень агрегирование показателей, фильтры, подсказки, действия и производительность.

Если реализация формально работает, но нарушает семантику, даёт подозрительные значения, создаёт неприемлемую нагрузку или неудобна в реальном интерфейсе, она возвращается на переработку. После исправления цикл повторяется.

Только после приёмки изменения готовятся к фиксации в Git. Проверяются состав изменённых файлов и diff; для изменений устойчивых правил отдельно оценивается необходимость обновления документации.

```text
бизнес-задача / аналитическая проблема
→ обсуждение вариантов с ChatGPT
→ решение автора
→ техническая постановка
→ SQL / Python / тесты через Codex/LLM или ручная настройка Tableau
→ локальный запуск
→ проверка данных, расчётов, тестов и интерфейса
→ исправление или приёмка
→ Git и документация
```

## 3. Распределение ответственности

| Область | Автор | ChatGPT / Codex |
|---|---|---|
| Постановка бизнес-задачи | Формулирует вопрос, цель, ограничения и критерии результата | Помогает декомпозировать задачу и выявить неоднозначности |
| Аналитическая методология | Определяет смысл показателей и принимает методологические решения | Предлагает варианты расчётов и помогает проверить последствия |
| Архитектура | Выбирает подход и допустимые компромиссы | Предлагает модели данных и технические варианты |
| Техническая постановка | Утверждает grain, входы, выходы, проверки и границы изменений | Помогает превратить решение в план реализации |
| SQL / Python / тесты | Обычно не пишет основную часть вручную | Создаёт основную часть реализации |
| Tableau | Вручную реализует и проверяет интерфейс | Предлагает визуальные и технические решения, помогает диагностировать проблемы |
| Локальное выполнение | Запускает код, миграции, тесты и запросы | Помогает разбирать фактический вывод и ошибки |
| Проверка результата | Проверяет данные, смысл показателей, независимые сверки, производительность и Tableau | Помогает строить проверки и искать причины расхождений |
| Приёмка | Принимает, отклоняет или возвращает результат на доработку | Не принимает решение за автора |
| Git и документация | Проверяет состав изменений и решает, что фиксировать | Готовит изменения и указывает возможное влияние на документацию |

Полноценной традиционной построчной проверки SQL/Python с моей стороны не выполнялось. Контроль строился прежде всего на аналитическом смысле, структуре данных, фактических результатах, независимых сверках, тестах, производительности и поведении системы.

## 4. Пример полного цикла: синтетический набор Search Demand

### Проблема

Для проектирования Search Demand и Tableau были нужны региональные данные с длинной временной историей, получать такие данные вручную заняло бы много времени. Поскольку задача решалась для формирования портфолио, а не в рамках реальной бизнес-пробдемы, было принято решение работать на синтетических данных. В случае получения реального заказа и финансирования реальные данные могут быть быстро получены при помощи API Yandex Cloud и встроаны в уже имеющиеся таблицы и визуализации. 

### Решение автора

Был выбран временный синтетический DEV-набор с чёткими границами. Национальные месячные значения Yandex должны были опираться на фактические вручную собранные значения Wordstat по всем выбранным ключевым словам и точно сохраняться после распределения по регионам. Региональные профили были синтетическими, но не должны были быть простыми пропорциональными копиями одного распределения. Google допускался только как полностью синтетический источник и использовался только для настройки фильтра `source`. Временная шкала была сдвинута на 100 лет назад, чтобы демонстрационные данные нельзя было принять за живые. Также это решало проблему безопасного повторного запуска: генератор не мог бы дублировать или перезаписывать существующий набор.

### Работа AI

ChatGPT помог формализовать требования, а Codex/LLM реализовал Python-генератор, загрузку и тесты. Массовая генерация выполнялась обычным Python-кодом; LLM не участвовала в генерации региональных во время выполнения, чтобы не тратить токены.

### Проверка

Итоговый набор содержал 83 региона, 85 keywords, 80 месяцев и два источника — 1 128 800 строк. Проверялись уникальность grain, ожидаемый объём, точное согласование сумм региональных значений Yandex с исходными национальными значениями Wordstat и разнообразие региональных профилей. Повторный запуск должен был распознавать уже существующий корректный набор и не добавлять дубликаты.

### Итог

Набор был принят как инструмент разработки и проверки Tableau, а не как модель реального регионального рынка. Это ограничение было сохранено и в документации, и в публичном представлении кейса.

## 5. Пример полного цикла: переработка из-за производительности

### Проблема

После подключения Search Demand к Tableau отдельные сценарии стали практически непригодными по скорости. Проблема была замечена по поведению работающей системы: визуализации обновлялись слишком долго, существенно уменьшалось свободное место на диске, что отображалось на уровне операционной системы. Это стало основанием остановить дальнейшее усложнение интерфейса и отдельно исследовать путь выполнения запросов.

### Решение автора

Автор предложил изменить границу ответственности между Tableau и PostgreSQL: тяжёлые и повторяемые расчёты вынести из интерактивного контура в специализированные витрины, а в Tableau оставить фильтрацию, выбор пользователя и визуальное представление. Вместо одного универсального объекта было решено создавать небольшие `VIEW` / `MATERIALIZED VIEW` под конкретные сценарии.

### Работа AI

ChatGPT помог разобрать варианты и сформировать архитектуру витрин, а Codex/LLM реализовал SQL-изменения и проверки. В частности, часть витрин была построена так, чтобы PostgreSQL мог ограничивать данные по источнику, направлению или периоду до тяжёлых соединений и агрегаций. В результате вместо одной таблицы было построено 4 VIEW и 2 MATERIALIZED VIEW.

### Проверка

После изменений контрольные запросы были выполнены повторно. Для одного зафиксированного сценария время запроса снизилось примерно с 819 ms до 86.8 ms. После SQL-проверок решение снова проверялось в Tableau как конечном интерфейсе, где также работа фильтров была очевидно быстрее. Итоговое поведение было принято как достаточное для текущего прототипа.

### Итог

Проблема производительности привела не к косметической настройке Tableau, а к изменению архитектуры слоя `mart`. Для этого кейса важен сам цикл: человек заметил эксплуатационную проблему, инициировал исследование, предложил изменение архитектуры, AI помог реализовать его, а эффект был проверен измерением и фактической работой Tableau.

## 6. Как контролируется качество реализации с помощью AI

Контроль строится в нескольких независимых точках.

- **Проверяется рабочая система, а не отчёт AI.** Код, миграции, запросы и тесты запускаются локально; в Tableau изменения реализуются и проверяются вручную.
- **Проверяется grain и аналитический смысл.** Число строк или меток, уровень агрегации и смысл показателя должны соответствовать исходной постановке. Подозрительные значения разбираются на конкретных примерах, а не принимаются только потому, что формула формально работает.
- **Сверяется источник и результат.** Для синтетического Yandex сумма регионов должна точно воспроизводить исходное национальное значение. Для критичных витрин применялись независимые расчёты; например, все 498 строк `mart.search_demand_keyword_growth` были отдельно пересчитаны из staging без расхождений по ключевым метрикам.
- **Тесты дополняются проверкой поведения.** Успешные тесты не заменяют проверку бизнес-смысла, производительности и поведения Tableau.
- **Неподходящее решение возвращается на исправление.** Это относится и к коду, и к советам по Tableau: рекомендация AI не считается правильной до проверки на реальном интерфейсе и данных.
- **Проверяется область изменений перед фиксацией.** Однажды AI подготовил документационные изменения поверх устаревших копий и удалил актуальные фрагменты. Ошибка была обнаружена до commit. После этого для канонической документации используется только актуальная версия, а неожиданные изменения в diff считаются блокирующей проблемой.

## 7. Ограничения подхода

Этот проект не является примером самостоятельного ручного написания всего SQL и Python. Основная часть SQL, Python и тестов создавалась с помощью ChatGPT/Codex, и полноценной традиционной построчной проверки кода с моей стороны обычно не было.

Поэтому прохождение тестов или успешное выполнение SQL не считается автоматическим доказательством правильности решения. AI может технически корректно реализовать неверно заданную метрику, пропустить побочный эффект или предложить правдоподобное, но неподходящее архитектурное решение. В Tableau AI также не видит внутреннее состояние книги и результат своей рекомендации до тех пор, пока человек не выполнит её и не вернёт фактический результат.

Моя зона ответственности — постановка задачи, аналитический смысл, структура данных, выбор решений, критерии проверки и приёмка фактического результата. В этом качестве AlphaLab Search Demand следует рассматривать как пример разработки с использованием AI, а не как демонстрацию самостоятельного ручного программирования.
