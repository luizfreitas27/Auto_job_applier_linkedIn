# Auto Job Applier

A local bot that searches LinkedIn for jobs matching the user's criteria and submits Easy Apply applications on their behalf, optionally drafting answers with an AI model. Everything runs on the user's machine with the user's own account.

## Language

### Jobs and applications

**Job**:
A single LinkedIn job posting, identified by its LinkedIn job ID.
_Avoid_: listing, posting, position, card

**Easy Apply job**:
A job whose application form is LinkedIn's own in-page modal, so the bot can fill and submit it.
_Avoid_: internal job, in-app job

**External job**:
A job whose Apply button leaves LinkedIn for the company's own site. The bot records its link and does not apply.
_Avoid_: redirect job, off-site job

**Applied job**:
A job whose Easy Apply form the bot submitted. Recorded in the applied-jobs history.
_Avoid_: submitted, done

**Skipped job**:
A job the bot deliberately did not apply to because a rule said so: blacklist, bad words, experience, sponsorship, dry run, or an unanswerable question. Not a failure.
_Avoid_: rejected, ignored, filtered

**Failed job**:
A job the bot tried to apply to and could not finish because something broke.
_Avoid_: errored, crashed, skipped

**Dry run**:
A run with `stop_before_submit` on: the bot fills every form and discards it at the Review step instead of submitting.
_Avoid_: test mode, preview

**Search term**:
One keyword query the bot types into LinkedIn's job search. A run visits every search term in turn.
_Avoid_: query, keyword, role

**Run**:
One full pass over all search terms. In non-stop mode runs repeat with pauses until the daily Easy Apply limit is reached.
_Avoid_: session, cycle, loop

**Market**:
The set of values that differ between applying in Brazil and abroad: currency, desired and current salary (monthly in Brazil, annual abroad), search location and search terms. One market is active per run.
_Avoid_: region, locale, country mode, profile

### Form questions

**Question**:
One field in an Easy Apply form, identified by its visible label. Its **control kind** is text, textarea, select (dropdown), radio or checkbox.
_Avoid_: field, input, prompt, control type

**Configured answer**:
An answer the user set in `config/questions.py` or the control panel for a known kind of question (years of experience, salary, authorization...).
_Avoid_: default, preset, static answer

**Unrecognised question**:
A question whose label matches none of the bot's known kinds, so no configured answer applies.
_Avoid_: unknown, failed question, missing answer

**Answer memory**:
The bot's persistent record of answers it has given to unrecognised questions, kept so each question has to be resolved once.
_Avoid_: cache, learned answers, Q&A store

**Remembered answer**:
One answer in the answer memory: a question (normalised label plus control kind), the answer text, where it came from (the AI, the user, or a form control the bot saw and left alone) and its review state.
_Avoid_: memory entry, record, saved answer, learned answer

**Review state**:
Whether a remembered answer is **pending** (not yet confirmed by the user) or **approved** (the user confirmed or corrected it). Only approved answers may tick a checkbox.
_Avoid_: status, verified, confirmed

**Review queue**:
The list of pending remembered answers the user works through in the control panel, approving, correcting or deleting each one.
_Avoid_: inbox, backlog, pending list

**Captured answer**:
A remembered answer taken from what the user typed into the form by hand after a "Help Needed" pause. Approved on creation.
_Avoid_: manual answer, learned from user

**Sensitive question**:
A question about work authorization, visa, citizenship, security clearance, salary, disability or veteran status. Answered only from configured answers, never by the AI or the answer memory.
_Avoid_: protected question, legal question

**Candidate profile**:
The description of the applicant the bot hands to the AI, assembled from the configured personal and application answers plus the free-text `user_information_all`. Excludes phone, email and street address.
_Avoid_: user info, context, persona

### Scheduling and notifications

**Schedule window**:
A weekday-and-time span during which the control panel starts the bot on its own and stops it at the end.
_Avoid_: cron, timer, slot

**Run summary**:
The counts the bot reports when a run ends: applied, external links collected, failed, skipped, and pending answers.
_Avoid_: report, stats, results

### Running the tool

**Control panel**:
The local web page served by `app.py` where the user edits settings, starts and stops the bot and views history.
_Avoid_: dashboard, UI, web app, admin

**Safe mode**:
Running Chrome with a throwaway profile instead of the user's real Chrome profile.
_Avoid_: guest mode, incognito

**Blacklist**:
Company names, and words in a job's "About the company" text, that make the bot skip the job.
_Avoid_: blocklist, banned companies
