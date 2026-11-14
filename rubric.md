# Rubric for the Vera Checks channel bible and scripts (frozen 2026-11-14, before any scoring)

Changed after freezing, 2026-11-14, at the owner's direction: the on-screen AI disclosure was removed, so
gates 3 and 6 and criteria C3 and C5 were rewritten. The earlier judge score (8.75) was given against the old
wording and does not carry over. The scripts have not been re-judged against this version.

Artifact under test: `channel_bible.md` together with the five scripts in `episodes.json`.

## Hard gates (objective, checked by `tools/gates.py`; a failed gate caps the result at "not done")

1. Every episode cites a source on an official domain (ftc.gov, ic3.gov, fbi.gov, cisa.gov, consumerfinance.gov).
2. Every narration is 85-125 spoken words (about 35-45 seconds).
3. The last line is the sign-off, and no line makes an identity claim (neither "I am an AI" nor "I am a real person", and no invented job or credentials).
4. No two episodes share a first line, an on-screen message, a source link or a pillar.
5. No narration contains a percentage or a million/billion/trillion figure (no statistic without an on-screen source).
6. Every post caption is 300 characters or fewer, carries the source link, and makes no identity claim.
7. No spoken line is longer than 24 words.
8. Every source link answers HTTP 200.
9. Each rendered episode is 30-50 seconds, has an audio stream that is not silent, and no caption longer than 3 words.

## Soft criteria (scored 1-10 by an outside judge)

- C1 Hook (w=0.25): would a stranger stop scrolling in the first 3 seconds? 4 = generic warning opener, 7 = specific message on screen with a clear stake, 10 = specific, surprising, and impossible to mistake for another channel
- C2 Usefulness (w=0.25): is the 10-second check concrete, correct and doable right now? 4 = vague ("be careful"), 7 = one clear action, 10 = one clear action that also works when the viewer cannot tell real from fake, traceable to the cited source
- C3 Differentiation (w=0.20): does the format do real work? 4 = a generic warning video, 7 = the scam-on-screen plus one sourced 10-second check is recognisable as this show, 10 = a viewer could name the show from ten seconds with the sound off, and the check is something no competing video gives
- C4 Variety (w=0.15): do the five episodes feel like five videos? 4 = same template with swapped nouns, 7 = different scams and checks, 10 = different scams, emotional registers, structures and checks while still recognisably one show
- C5 Trust and compliance (w=0.15): sourcing, no harm, no false identity. 4 = unsourced or implies a human expert, 7 = sourced, no identity or credential claims, platform AI label on, 10 = all of that and nothing a platform or a regulator would object to

Weighted score = sum of weight x score. Done at 8.5 with all gates passing. Stop after 5 rounds, or 2 rounds in a row gaining less than 0.3.
