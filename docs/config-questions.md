# `config/questions.py` — Easy Apply answers

What the tool should say when an application asks you something. Open
`config/questions.py`, or use the **Profile** and **Run settings** tabs of the control panel.

## Resume

| Setting | What it is |
|---|---|
| `default_resume_path` | Relative path to the resume to upload, e.g. `"all resumes/default/resume.pdf"`. **Optional** — if the file is not found, the tool keeps using the resume you last uploaded to LinkedIn |

## Experience and profile

| Setting | What it is |
|---|---|
| `years_of_experience` | A number in quotes, e.g. `"6"`. This is what gets typed into "how many years of experience do you have" questions. It is **not** the same as `current_experience` in [`config/search.py`](config-search.md), which decides whether a job is skipped |
| `website` | Portfolio URL, or `""` to leave the question unanswered |
| `linkedIn` | Your LinkedIn profile URL |
| `linkedin_headline` | Your headline, e.g. `"Full Stack Developer with Masters in Computer Science and 4+ years of experience"`, or `""` |
| `linkedin_summary` | Your summary. Use `\n` for line breaks in a `"..."` string, or use `"""..."""` and write it across lines |
| `cover_letter` | Your cover letter. Same formatting rules as the summary |
| `user_information_all` | Free-form **addition** to the candidate profile the **AI** is given. The tool already builds that profile from your settings (name, location, years of experience, desired salary, notice period, recent employer, headline, summary, work authorization, visa need); put here anything those miss, such as key skills. Phone, email, street address, citizenship status and current salary are never sent. Only used when AI is on (see [secrets](config-secrets.md)) |
| `recent_employer` | Name of your most recent employer, e.g. `"Not Applicable"` |
| `confidence_level` | `"1"` to `"10"` in quotes. Used for "on a scale of 1-10, how much experience do you have..." questions |

Leaving any of these as `""` means the question is left unanswered. Some companies make
them compulsory.

## Work authorization

These are **three different questions**, and someone on a valid work visa answers them
differently. The tool matches them in this order — sponsorship, then authorization, then
citizenship — because "sponsor a new U.S. work visa or work authorization" is a
sponsorship question, not an authorization one.

| Setting | The question it answers | Valid values |
|---|---|---|
| `require_visa` | "Will you now or in the future require sponsorship, or a new/transferred visa?" | `"Yes"` or `"No"` |
| `legally_authorized` | "Are you legally authorized to work in this country?" — i.e. do you **already** have permission (citizen, permanent resident, or a valid work visa such as H-1B or OPT) | `"Yes"` or `"No"` |
| `us_citizenship` | "What is your citizenship status?" | `"U.S. Citizen/Permanent Resident"`, `"Non-citizen allowed to work for any employer"`, `"Non-citizen allowed to work for current employer"`, `"Non-citizen seeking work authorization"`, `"Canadian Citizen/Permanent Resident"`, `"Other"`, or `""` to leave it unanswered |

> **`legally_authorized` is not the opposite of `require_visa`.** Someone on a valid work
> visa answers **`"Yes"` to both**: they are authorized to work today, and they will need a
> transfer or a new petition later.

`legally_authorized` is only settable by editing `config/questions.py` — it has no field in
the control panel. It defaults to `"Yes"`.

`require_visa = "Yes"` is also the switch that activates the sponsorship filters in
[`config/search.py`](config-search.md#visa-sponsorship-filtering). With `require_visa = "No"`
those settings do nothing at all.

## Salary and notice period

| Setting | What it is |
|---|---|
| `desired_salary` | Numbers only, no quotes, e.g. `1200000`. Some companies only accept digits |
| `current_ctc` | Your current salary, numbers only, no quotes |
| `notice_period` | Days, no quotes, e.g. `30` |

The tool reshapes these to fit the question it is asked:

- If a salary question contains the word **"lakhs"**, a `.` is inserted before the last five
  digits — `2400000` is answered as `"24.00"`, `850000` as `"8.50"`.
- If a salary question asks **per month**, the value is divided by 12 — `2400000` is
  answered as `"200000"`, `850000` as `"70833"`.
- If a notice-period question contains **"month"** or **"week"**, the value is divided by 30
  or 7 respectively — `notice_period = 66` is answered as `"66"`, or `"2"` in months, or
  `"9"` in weeks.

## Manual-input and answer settings

| Setting | Default | What it does |
|---|---|---|
| `pause_before_submit` | `True` | Pause on the final screen of every application so you can check it before it is sent. The dialog offers **Submit Application**, **Discard Application**, or **Disable Pause** (which turns pausing off for the rest of this run only). **Treated as `False` when `run_in_background = True`** |
| `pause_at_failed_question` | `True` | Pause and wait for you when the tool cannot confidently answer a question. **If set to `False` it answers randomly.** Also treated as `False` when `run_in_background = True` |
| `overwrite_previous_answers` | `False` | The tool remembers the answer it gave to a question and reuses it. Set to `True` to overwrite a saved answer with the current config value |

For a dry run that fills everything in and stops without submitting, see
[`stop_before_submit`](config-settings.md#dry-runs-stop_before_submit).

## Remembered answers: `answers_memory.json`

When a question matches none of the settings above, the tool asks the AI (if it is on) and
**remembers** the answer in `answers_memory.json` at the project root. The next time the same
question appears, at any company, the remembered answer is used and the AI is not asked
again. Small rewordings count as the same question; the log says when a match was approximate.

Each remembered answer records the question, the control kind, the answer, who gave it
(`ai` or `user`), its review state (`pending` until you confirm it, then `approved`), how many
times it was used and the last job it was used on. Remembered answers are used immediately,
including pending ones; reviewing them improves future applications, it does not block the
current one.

When AI is on, it also answers dropdowns and radio buttons it does not recognise: it is shown
the real options and must name one of them exactly, otherwise the control is left alone.

Dropdowns and radio buttons work the same way: the remembered answer is text, and the tool
picks whichever option on the current form means the same thing, so a remembered "Yes" fits a
form offering "Yes / No" and one offering "Yes, I am / No, I am not". Checkboxes are stricter:
the tool never ticks a box on its own. An unticked box it does not recognise is added to the
file as a pending `checked` answer; once you approve it, the tool ticks that box next time.

Running from a terminal with `pause_at_failed_question` on, the answers you give by hand
during the "Help Needed" pause are captured too, already approved. Only the fields that were
empty when the pause began count; stay on the same page of the form until you click Continue.

**Sensitive questions never use this**: work authorization, visa, citizenship, security
clearance, salary, disability and veteran status are answered only from the settings above.

The file is yours and is ignored by git. Delete a remembered answer to make the tool treat that question
as new again, or delete the file to start over.

## Not yet implemented

`currency` (the currency tag appended to salary answers for employers that accept text
input) is commented out in the file and marked *In development*.

---

[← Back to docs index](README.md) · [Configuration overview](configuration.md)
