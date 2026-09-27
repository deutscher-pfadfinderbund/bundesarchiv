# What I learned about design (sessions 2026-09-26/27)

Written for the owner to read. Each entry says what I believed or did before, what changed, and
why it holds. Part 1 comes from the owner's teaching in the live sessions; part 2 from my own
reviews of the archivist screens overnight.

## Part 1 — from the owner's questions

**1. A rule without its reason is a pattern I will misapply.** I wrote "each row has two tiers"
as if it were a truth. It is only the *result* of an intention: people scan a result list
downwards for one thing, the title. Once I state the intention, I can see where it stops
applying — and where I would otherwise have followed the rule into harm.

**2. A fix is also an element, with its own cost.** My fix for "quiet dates are harder to scan
when sorted by date" — step the sorted column up to full ink — was worse than the problem. The
user who sorted is already looking at that column; good-enough contrast lets them finish the
task. The fix added a signal nobody needed. I now price the fix the same way as the problem, and
keep the problem when the fix costs more.

**3. A change in appearance claims "something important happened".** So it must not announce
what the user already knows because they caused it. The sort arrow is enough feedback for a
sort. This is the same economy as "one fact, one place", applied to time instead of space.

**4. Lines are connectors, not separators.** A hairline between rows exists so the eye does not
slip between a title on the left and its date far to the right. That is also why a line above
the first row or under a header is wrong: there is nothing to connect, it only borders. Heavy
section rules duplicated what heading + space already said — but they *shaped* blocks, and
removing them moved that job onto spacing, which then has to be far stricter. Taking something
away is never free: its job lands somewhere else.

**5. Alignment is the structure; frames are for cohesion.** Good spacing and alignment make
content form natural lines the eye follows without effort. Real lines and frames are for places
where no natural line appears: a card with its title top left and its actions bottom right has
nothing tying the two together, so a frame does it. Framing things that already stand together
(filter buttons, pager numbers) adds objects without adding meaning.

**6. A typeface should mean one thing.** Mono earns its place where values line up in a column
and get scanned (dates, Signaturen). As a label voice it is just another style — a third voice,
louder than it should be, especially in capitals.

**7. Loudness is a claim of rank, and the rank belongs to the user's task.** The black filter
chip and the white header search were the loudest things below the header, so every visit
started with a detour. The results should come first, then what is filtered, then how to change
it.

**8. One fact, one element — even when the two look like different kinds of thing.** The
heading and the active filter were the same fact (the scope of the results). The answer was not
to style one quieter but to merge them: the search sentence is the heading *and* the control.

**9. Hide only what can never become active here.** A disabled "Zurück" on page 1 stays, because
it becomes active after one click; its absence would make the pager jump. Progressive
disclosure is powerful when what it hides is opened on purpose.

**10. Most "places" in an app are presets of one view.** "Archiv" and "Bestände" were not
destinations; they were scopes of the one list. Seeing that removed navigation items, a planned
new screen (Werkstatt), and gave every future "target" a cheap shape: a preset with a URL.

**11. The screen size is a budget, not a layout.** The Zeitleiste is pleasant on a wide screen
and balances the page there; on a phone it is just a filter eating the whole screen. The same
element has a different price per size, so each component declares full / compact / folded /
absent per size.

**12. Decompose before composing.** Mock CSS written page by page accretes hard-coded values;
more screens on top of it would each drift a little. A small system (tokens → components with
knobs → layouts) first makes every later screen consistent by construction.

## Part 2 — from my reviews of the archivist screens

**13. A breadcrumb and a fact can be the same fact.** The article showed its Bestand in the crumb
and again as a fact row. Once the crumb exists and links, the fact row only repeats it. Adding a
navigation element changes what the content still needs to say — I have to re-price the content
after every structural addition, not only the new element.

**14. Type size belongs to the container, not to the page.** A title role tuned for a full-width
page (3rem) wrapped to four lines in a side column and pushed the facts out of view. The fix was
not a smaller token but a knob the layout sets: the container decides which role a title takes.
The same holds for rank: an onward list is a section, but a *secondary* one, and its heading
should say so — rank follows gain, not the element's place in the HTML outline.

**15. A line has two different jobs, and they need different strengths.** A connector (row line)
may be faint — it only guides the eye. An affordance edge (an input's frame) must be found by
people with weaker eyes, so it needs about 3:1 contrast. Using the connector color for inputs
would hide them; using the text color for twenty input frames recreated the "too many lines"
the owner rejected in August. Two jobs, two tokens.

**16. Identical values repeated per row are one fact shown many times.** In a one-field bulk
edit, the new value is the same for every record; printing it bold on each row tripled the
loudest thing on the page without telling anything new. What varies per row is what each record
*loses* — that is the per-row fact. The general test: a column whose values are all equal is not
a column, it is a sentence.

**17. Repeated action words are noise; the row is the affordance.** "Diesen Artikel bearbeiten"
on every row said the same thing each time. Making the title the link carries the action with no
extra words. And one action should have one word: "×" and "Entfernen" for the same removal made
the user learn two signs.

**18. Frequency decides visibility — especially for consequential actions.** "Als Entwurf
zurückziehen" sat as a framed button right under Speichern: rare, consequential, and one mis-aim
away from the frequent action. Folding it into "Mehr …" costs one click on a rare path and
removes a risk on the common one. Progressive disclosure again, used for its intended job.

**19. A heading over one field costs more than it tells.** Section headings earn their place by
grouping several things. Over a single select they are pure weight. The same economy as
"no role labels" and "no redundant marks": structure words are only worth it when there is
structure to name.

**20. Words the user can't act on are cost — jargon and development narration alike.**
"(EDTF)" twice on the Datierung field, and "Verschieben und Sichtbarkeit ändern folgen später"
on the Bestand form: the first names a standard volunteers don't know, the second narrates the
project's roadmap. Neither helps the archivist do the task in front of them. The examples in the
hint teach the syntax better than the acronym.

**21. A rule's boundary shows up in flows, not in single screens.** "The way back to a search is
browser Back" holds for pages you navigate — but after a submitted form, Back lands on the check
page, so the result page legitimately keeps "Zurück zur Suche". I only saw that by walking the
whole bulk flow instead of judging each screen alone.

**22. Lines between one-ended rows separate.** The conflict list (field names only) had lines
between its rows, which violated "a line connects two ends" — there was nothing to connect. The
fix belonged in the system (a register row gets a line only when it has two ends), so every
future list inherits it instead of each page remembering the rule.

**23. A fix in the system is a fix everywhere — including where it breaks things.** My register
rule ("a line only for two-ended rows") was more specific than the rules that keep the Zeitleiste
and the "Unbekannt" row line-free, so lines reappeared there. A change to a shared component has to
be checked against every consumer (the gallery and the r4 pages), not only the screen that
prompted it. Specificity is part of a rule's boundary.

## Part 3 — from the a2 / a3 review (2026-09-27)

**24. A qualifier touches what it qualifies.** The "alle ›" links at the far edge of the section
heads, a file's size at the far edge of its row, and the toolbar's action pushed right of the
selection all floated loose: nothing tied them to what they belong to. A single row has no line to
connect its two ends (lesson 22), so the ends must sit together. The "intern" rule of round 5 was
the same lesson on one element; it holds for links, figures and actions too.

**25. The state names the thing, not the absence.** "Artikel ohne Medien" was a video: it had media,
only no image preview. Named by what was missing, the page dropped the medium from the lead and
lost its hierarchy. Named by what it is, the medium leads like on every other article, as the
native player.

**26. A mode replaces, it does not add.** The bulk bar at the bottom added a whole band for a mode
the archivist enters by ticking a box. The list already has a row whose job pauses in that mode:
the column heads. Swapping them for the toolbar costs no space, keeps every row in place, and puts
the tool where the eye already is. Step two (the field sentence) opens on purpose, so only it may
grow the row.

**27. A tool area holds tools, not a sentence.** The field sentence ("[Feld] auf [Wert] setzen") was
right for one action and wrong for a place that will hold delete, move, publish and more: every new
tool would have rewritten the sentence. A row of named tools, each opening its own small panel, grows
by one button at a time.

**28. Lines and columns end where the content ends.** Row rules ran on past the last column into an
empty action slot, and a lead column sized for the longest possible date pushed every title away.
Size a column by its content (shrink the last one, cap the lead at one full date and let a range
break), and the rules and gaps follow the content instead of the container.
