---
alwaysApply: false
applyTo: "** — when drafting an email or other prose the operator will send under their name, or a talk abstract he rewrites or publishes"
---

# Humanize Outbound Prose

## When It Applies

- Any email draft written for the operator: a new email, a reply, a forwarding note
- Any other prose the operator will send under their name to someone else: a LinkedIn or Slack message, a comment, a cover note, an abstract
- A talk abstract or session description he rewrites or publishes, including another speaker's, such as a PortCon agenda entry or a Sessionize session
- Not chat replies to the operator, status posts, or summaries of inbound mail

## Required Behavior

- Write the draft, then run `Skill(skill: "tessl__blog-writer")` on it as a humanization pass before posting it to the chat
- Ask the skill to humanize the existing draft, keeping its format, language, recipient and purpose
- Post only the humanized draft, never the pre-pass draft
- Names, dates, numbers, links, quotes and commitments stay exactly as given; the pass changes wording, never content
- For an abstract or session description, run `Skill(skill: "tessl__cfp-abstract")` on it before the blog-writer pass, also for another speaker's talk: keep that speaker's facts and claims, and apply no voice calibration to them
- Write and show one abstract text even when the form has separate Summary and Description fields; split it only when filling the form

## Missing Skill

- Narrow exception for a container without `tessl__blog-writer` or `tessl__cfp-abstract`.
- Preconditions (all required):
  1. The `Skill()` call fails because that skill is not installed
  2. The posted draft carries one line naming the pass that did not run
- Every other draft runs its passes before it is posted
