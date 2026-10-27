# Problem statement

## The problem

Regulated firms need answers about their complaints that they can audit.

Today a question like "are complaints about accounts opened without consent rising at this company?" goes to an analyst, who writes SQL against raw tables, makes judgement calls about which rows count, and hands back a number with no trail. Two analysts can get two different numbers, and the definition lives in someone's head.

AI tools that answer in plain English make this worse when they guess from raw tables: fast, confident answers that nobody can check.

## What Complaint Radar does

Complaint Radar is an AI data analyst over 15 years of US financial complaints. Ask a question in plain English and get back a number, a chart or a short report, with the SQL, row count and assumptions behind it.

It answers only from metrics defined in a semantic layer, which sits on an audited warehouse where every row traces back to the batch it arrived in.

## Who it's for

- **Complaints operations lead:** needs quick, quotable answers about volumes, issues and response times.
- **Risk analyst:** needs answers they can check, re-run and defend.

See [personas](01-personas.md).

## Showcase question

> Were unauthorised-account complaints rising at Wells Fargo before September 2016?

The scandal broke that month, so the answer is a real test of the analyst. The answer is not known yet. It is run through the analyst in phase 7, and nothing is claimed before then.

## Scope

**In scope**

- The CFPB Consumer Complaint Database narratives archive: 21 exports covering complaints received 1 Dec 2011 to 14 Aug 2026.
- MVP (phases 0-5): one product, for example credit cards, and the last five years; then widen.
- Read-only questions answered from defined metrics.

**Out of scope**

- Live data. The CFPB stopped publishing narratives in August 2026, so the archive is fixed.
- Judging whether a complaint is true. Narratives are unverified consumer statements, so answers describe what was reported, not what happened.
- Any write to the warehouse from the analyst.
- The FSPO document layer, until its terms of use are checked.

## What success looks like

- Every answer shows its SQL, row count and assumptions.
- No generated query reaches the warehouse unless it is read-only and touches only allowed tables.
- A question that needs an undefined metric is refused, not guessed.
- Accuracy is measured on a 50-question evaluation set, reported by difficulty, and re-run before any model change.
- Every number traces back through the warehouse to the batch it came from.
- Anyone can rebuild the warehouse from raw with one command.
