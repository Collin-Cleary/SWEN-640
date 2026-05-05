# PROPOSAL.md

## 1. The "Problem"
**Area of Interest:** Developer productivity and issue resolution efficiency in Open Source Software (OSS).

**The Gap:** 
In open-source repositories, a notable presence in the development cycle and a prominent source of communication between developers and users are the issues. The lifespan of issues tends to vary from open to close. I want to know what factors affect this. I want to analyze the effect had by certain factors on the efficiency of an issue's resolution. namely, verbosity in initial body/description, length of discussion, and wether an issue addresses a feature or not. I intend to measure "efficiency of resolution" through number of commits during the issue's duration, how many commits were likely related, the length of the issue's duration, and type of resolution.

## 2. Research Questions
1. **RQ1:** Is the volume of communication (measured by the word count of the initial issue body and the total number of comments) positively correlated with an issue's total resolution time?
2. **RQ2:** Do feature-request issues experience a higher degree of "multitasking" (defined as a lower ratio of issue-related commits to total repository commits during the issue's open period) and longer resolution times compared to non-feature (bug/fix) issues, and how does this affect their efficiency?

*Constraint Check:* My research questions are falsifiable. They rely on quantitative metrics (word counts, comment counts, timestamps, and commit ratios) that can be extracted directly from a repository's history and statistically tested.

## 3. Methodology & Dataset
**Define your data source(s):** I will collect data using the GitHub REST API. I plan to target 1-3 large, open-source repositories (e.g., `junit-team/junit4` or `pallets/flask`) to ensure a large selection of closed issues, hopefully, with labels (e.g., "enhancement/feature" vs "bug"). 

**Define your sample:**
* **Sample Size:** Using a 95% Confidence Interval and a 5% Margin of Error on a repository with tens of thousands of issues, the required sample size is approximately **385 issues**.
* **Sampling Approach:** I will use **stratified random sampling**. I'll try to stratify the issues based on their labels (50% feature-related issues and 50% bug/non-feature issues) to ensure a balanced comparison. Though depending on the needs of my study or preliminary results, I might just evaluate these issue types separately from each other. I will have to slightly alter my tools to record more information from issue gathering. 

## 4. Preliminary Related Work
**Paper 1:**
* **Citation:** Kikas, R., Dumas, M., & Pfahl, D. (2016). Using dynamic and contextual features to predict issue lifetime in GitHub projects. *Proceedings of the 13th International Conference on Mining Software Repositories (MSR)*, 291-302.
* **Relation to Project:** The authors of this paper built machine learning models to predict issue lifetime using "dynamic features", specifically citing the number of comments an issue receives over time as a primary predictive feature. This validates my first research question by confirming that comment volume is a significant metric in issue resolution, giving me a baseline to compare my own correlation results against.

**Paper 2:**
* **Citation:** Qiao, Y., Lu, X., et al. (2024). Predicting Issue Resolution Time of OSS Using Multiple Features. *Journal of Software: Evolution and Process*.
* **Relation to Project:** This recent study combines static text features and dynamic developer behaviors to predict resolution time, talking about how issue-related behaviors heavily impact time distributions. This relates perfectly to my focus on tracking the ratio of issue-related commits versus unrelated commits as an indicator of developer focus and efficiency.