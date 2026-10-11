---
name: adversarial-input
description: Rules for code that parses, serializes or gates input — adversarial round-trip tests for every encode/decode pair, the full input contract for fail-closed and visibility functions, and the bar for which slips and states to guard. Preloaded by the writer agent.
when_to_use: Writing or changing an encode/decode pair, a form field's parse, or a fail-closed, visibility or security function.
---

# Adversarial input

## Serialization is adversarial by default

Every encode/decode or serialize/parse pair ships with an adversarial round-trip test in the commit
that introduces it: the delimiter itself, empty, unicode, percent, leading/trailing whitespace.
Joining externally-controlled values with an in-band delimiter and no escaping is a defect, not a
style call.

A form field is such a pair: the value the form pre-fills is parsed back on save, so an unchanged
field must save unchanged. Values from the legacy import count as external (Schlagworte contain
commas). A pair older than this rule that you touch without such a test gets the test in your
commit.

An absent field never means a value: a visibility-relevant field missing from a request keeps the
stored value (a stale pre-deploy form posts old names).

## The full input contract for fail-closed functions

For a fail-closed, visibility or security function, derive the full input validity contract first:
every shape an input can take, valid or not. Then test the least-visible output for every invalid
shape — an invalid input must fall to the narrowest result, never to a wider one.

## Which slips to guard

Handle the slips a normal user makes on a normal path (a confirm against an accidental delete) and
the states our own code produces. Do not build machinery against constructed scenarios that need a
deliberate unusual act outside our code.
