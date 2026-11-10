# Phase 2b: the mock-interview module

| # | Bug (verified in the audit) | Fix | Test that now guards it |
|---|---|---|---|
| 1 | A failed grading was **stored as 0/10 and the interview moved on** | Grading errors propagate; nothing is saved; the same question stays open and can be retried | `test_outage_while_grading_saves_nothing...` |
| 2 | An unparseable grading became an **invented 5/10** | Grading is validated JSON (`AnswerEvaluation`); one retry; then an honest 502 | `test_unparseable_grade_is_an_error...`, `test_scores_out_of_range...` |
| 3 | Question generation silently fell back to **10 canned questions** that ignore the JD/resume | Validated JSON bank; short/invalid -> retry -> 502. `_fallback_questions` deleted | `test_start_outage_creates_nothing...`, `test_unusable_question_bank...`, `test_a_too_short_bank...` |
| 4 | A **double click / retry / stale tab graded the answer against the NEXT question** | The client sends `q_num`. Already-answered question -> stored result is replayed, no AI call. Ahead of the server -> 409 | `test_retrying_an_answered_question_replays...`, `test_a_stale_tab...`, `test_an_answer_for_a_question_not_reached...` |
| 5 | Two parallel requests could both advance / both finish the interview | "Save answer + move pointer" is one transaction with a compare-and-set; only the winner runs completion | `test_saving_an_answer_is_a_compare_and_set`, `test_parallel_*` |
| 6 | **Every GET of the report re-ran side effects** (a new "Interview Complete" notification each load, re-credited roadmap days) | `get_report` is read-only. Notification + roadmap credit happen once, in the request that finishes the interview | `test_viewing_the_report_changes_nothing` |
| 7 | **Finishing a weekly interview at 0/10 marked two roadmap days "completed" with score 10**, and the day numbers came from the browser | Credit needs avg >= `WEEKLY_PASS_AVG` (6) **and** the server's own record that the student is on a milestone day (6/7, 13/14, ...). Otherwise: no credit (retake allowed) or practice mode | `test_zero_scores_no_longer_earn...`, `test_the_pass_mark_boundary`, `test_the_browser_cannot_choose...`, `test_a_weekly_interview_off_a_milestone...` |
| 8 | Summary generation failure -> canned "Keep practicing core concepts" text | Report is returned with the numbers and `overall_feedback_unavailable: true`; the next report request fills it in (cached once) | `test_report_survives_an_outage_in_the_summary...` |
| 9 | Restarting an interview kept the previous run's answers, polluting the new report | Old answers are deleted atomically with the new session; a failed restart leaves the old interview untouched | `test_restarting_wipes...`, `test_a_failed_restart...` |
| 10 | JD, resume, role, company and the candidate's answer pasted raw into prompts | All fenced with `wrap_untrusted`; the fence cannot be closed from inside | `test_candidate_answer_is_fenced_as_data` |
| 11 | Unvalidated `domain`/`round_type`/`weekly_career_day` (a bad number gave a blind 500); no answer size cap | 400/413 with a clear message | `test_start_validates_its_inputs`, `test_overlong_answer...` |
| 12 | Interview errors were all a generic 500 or a 200 with `{"status":"error"}` | `InterviewError` -> 404/409/413/400; AI errors use the Phase 2a handler | many |
| 13 | Interview endpoints were exempt from the lazy quota | They are lazy now: reading a report or skipping a question works at the limit; only AI calls are blocked | `test_at_the_limit_reading_and_skipping_work...` |
| - | A skipped (blank) question cost an AI call | Blank = score 0, no AI call | `test_blank_answer_is_a_free_zero...` |

## Behaviour changes you should know about
* **Weekly interview rules.** Credit = passing score (avg >= 6/10) on a real milestone day. The start message tells the student which. Off a milestone it is *practice mode* and changes nothing. Change the threshold with `WEEKLY_PASS_AVG` (it follows `QUIZ_PASS_SCORE`).
* **Failed grading.** The student now sees an error and the **answer is put back in the text box** so retrying is one click. (The failed attempt's message bubble is still in the local transcript; cosmetic.)
* **Stored feedback format.** New reports store JSON; old rows in the legacy `OVERALL_FEEDBACK: ...` text format still render.
* **`interview_qa.feedback`** now holds the one-line overall verdict (it used to hold the raw model text).

## Known limits (honest list)
* The completion step (notification + roadmap credit) runs *after* the answer is committed. If the database fails exactly between the two, the answer is saved but the credit is not; this is logged loudly (`Weekly milestone credit FAILED`). A true fix needs a transactional outbox; not worth it at this scale.
* A duplicate parallel submit still makes two AI calls (only one result is kept). The UI already disables the Send button while a request is in flight.
* The report page is rendered from the browser's stored copy, so the "summary unavailable" notice has no retry button yet.
* Not verified here: real Groq replies (a model might format the interview JSON differently) and the new SQL on a real Postgres; it uses only constructs your Postgres test already covers (`?`, `ON CONFLICT`, `UPDATE ... WHERE`).

## Still to do (Phase 2c and later)
Explicit action buttons instead of keyword guessing (`"book"` starts Day 1), shared (Redis/Postgres) rate limit + cache + PDF index for serverless, user timezones and streak logic.
