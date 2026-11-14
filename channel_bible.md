# Not Real Vera: channel bible

**Handle:** `@notrealvera` (backups: `@veraisnotreal`, `@notrealvera.ai`). Availability not yet checked.
**Tagline:** I'm not real. The scams are.
**One line:** An openly-AI host plays the scammer, shows how the trick is built, then gives one check you can do in ten seconds.

## 1. Who it is for

- **Primary:** adults 25-45 who get scam texts and calls every week and are the family's unofficial tech support.
- **Secondary:** their parents, who receive the videos by forward. Every episode must make sense to someone who has never heard the word "phishing".

The job the viewer hires the video for: *"I just got this message. Is it real, and what do I do?"*

## 2. Why Vera is an AI, out loud

Most avatar channels hide that the host is synthetic, and viewers punish them for it. Vera does the opposite. Being fake is her credential: she is the tool a scammer would use, so she can demonstrate the scam on the viewer instead of describing it. Four rules follow.

1. She says she is an AI in the first two sentences of every video.
2. She never claims a human life: no "my mum", no "when I was scammed", no "I tested this".
3. She never gives the advice on her own authority. The check comes from a named official alert shown on screen.
4. In every episode the premise must do a job a human presenter could not do honestly: she performs the fake call in her own synthetic voice, writes the fake text, or returns as the second scammer. If the script still works with "I'm Vera, an AI" deleted, it is rewritten.

## 3. Voice

- Default register: dry, calm, slightly amused. She confesses instead of warning: "here's how I'd write it", not "beware of scammers".
- She changes register when she plays a part: panicked as the cloned child, aggressive as the fake deputy, smooth as the "fund recovery" caller, brisk in an emergency. The switch back to her own calm voice is the reveal.
- Short sentences. No jargon without a plain-word gloss. No fear-mongering and no shaming of victims.
- Never: statistics she cannot source on screen, "experts say", "you won't believe", "smash that like".
- Signature close, every time: **"I'm not real. The scams are."**

## 4. Episode format (35-45 seconds, vertical)

Fixed in every episode, so it is recognisably one show:

| Element | Rule |
|---|---|
| Frame one | The real-looking scam message is on screen with a notification sound. |
| First line | Reacts to that message with a stake or a surprise. It is never a call to action and never the pillar name. |
| Second beat | "I'm Vera, an AI" (always within the first two lines). |
| The 10-second check | One action, doable right now, nothing to buy. Shown as a bright card. |
| Close | Sign-off line, handle, the alert it came from. |

What changes: each pillar has its own structure, so a week of episodes does not feel like one template.

| Pillar | Structure | Register |
|---|---|---|
| Scam of the Week | Confession and playbook: the three moves in the message, named by the feeling they exploit | Dry, amused |
| Real or me? | Vera performs the fake call, reveals it was her, then runs a drill: what would give it away, and the check that works when nothing does | Panic, then calm |
| Reply or delete? | Verdict first, then the reasons for both cases (honest mistake, or her) | Playful judge |
| Send this to your parents | Vera plays the caller, then gives one sentence a parent can remember | Aggressive, then plain |
| The first 60 minutes | Emergency checklist in order, then Vera returns as the follow-up scammer | Brisk, kind |

Hard limits: 85-125 spoken words; captions of at most 3 words; one scam per video; one check card per video.

## 5. Five pillars

| Pillar | Promise | Cadence |
|---|---|---|
| Scam of the Week | The message going around right now, taken apart | 2 per week |
| Real or me? | Deepfake and voice-clone drills: the check that works even when you cannot spot the fake | 1 per week |
| Reply or delete? | A suspicious message gets a ruling. Viewers are asked to comment theirs with names and numbers removed; until real submissions arrive, examples are written by us and never presented as a viewer's | 2 per week |
| Send this to your parents | One sentence a parent can remember | 1 per week |
| The first 60 minutes | What to do right after the money left, the link was tapped or the code was read out | 1 per week |

That is 7 episodes a week, one per day, with no pillar repeating on consecutive days.

## 6. What makes each episode different (anti-slop rules)

These rules are checked by `tools/gates.py` before anything is posted.

- A different scam, a different on-screen message and a different official alert in every episode.
- No two episodes open with the same first sentence.
- Each pillar has its own structure (section 4), accent colour and card type (text message, incoming call, voicemail, bank alert).
- Every episode has sound: voice, a notification cue on the hook, a rising cue on the check.
- Post captions stay under 300 characters, name the alert number, carry its link and end with "Host is AI-generated."

## 7. Compliance and trust

- **On screen, always:** an "AI HOST - NOT A REAL PERSON" badge.
- **YouTube:** switch on the altered or synthetic content disclosure for every upload.
- **TikTok:** switch on the AI-generated content label.
- **Instagram:** add the AI info label.
- **Sources:** only official consumer-protection or law-enforcement pages (FBI IC3, FTC, CISA, CFPB, or the local equivalent), and only pages we have opened and read. The alert number is on screen; the alert number and link are in the caption.
- **Traceability:** every "do this" sentence in a script must be findable in the cited alert. Vera's own colour (how she would write the text, the "delete" ruling) is framed as her confession or her ruling, not as the agency's advice.
- **Never:** show a real person's face or voice as a deepfake example, name a real company as the scammer, show a working scam link (on-screen links use the reserved `.example` domain), or tell viewers to "fight back".
- **Viewer submissions:** comments only, with names, numbers and links removed. No private messages asking for screenshots.
- **Corrections:** if an episode is wrong, pin a correction and re-upload. Do not quietly delete.

Why the first five cite the FBI's Internet Crime Complaint Center (IC3): those are the alert pages we could open and read end to end while writing. The saved text of each is in `docs/sources/`. The FTC's consumer pages are equally valid sources, but they could not be opened from the network this was written on, so nothing here leans on them.

## 8. First five episodes (full scripts in `episodes.json`)

| # | Pillar | Title | Structure | The 10-second check | Alert it comes from |
|---|---|---|---|---|---|
| 01 | Scam of the Week | The $12.51 toll text is fake | Confession and playbook, using the wording the FBI published | Don't tap. Look up your account on the toll service's real website. | IC3 I-041224-PSA, road toll smishing |
| 02 | Real or me? | That is not your kid's voice | Vera performs the call, then a drill | Ask for the family secret word. No word? Hang up and call them back. | IC3 I-120324-PSA, generative AI in fraud |
| 03 | Reply or delete? | Hi David, golf on Saturday? | Verdict first, then both cases | Never met them in person? Never invest on their advice. | IC3 I-031423-PSA, crypto investment schemes |
| 04 | Send this to your parents | The deputy on the phone is me | Vera plays the fake deputy, then one sentence | Payment demanded by phone? Hang up. Call the office's public number yourself. | IC3 I-091726-PSA, law-enforcement impersonation |
| 05 | The first 60 minutes | $2,400 just left your account. Do this now | Checklist, then Vera returns as "fund recovery" | Call your bank now. Say: this was fraud, recall the payment. | IC3 I-112525-PSA, account takeover (recovery-fee warning: I-081123-PSA) |

Where each check sits in its alert:

- **01:** "check your account using the toll service's legitimate website", contact its customer service number, delete the text, secure your accounts if you clicked.
- **02:** "create a secret word or phrase with your family to verify their identity"; listen to tone and word choice; hang up and call the number directly.
- **03:** do not invest on the advice of someone you met solely online; the fake site and the withdrawal "fee" are the scheme the alert describes. The alert does not mention wrong-number texts, so the script does not claim it does: "delete" is Vera's ruling.
- **04:** law enforcement and government "will never contact members of the public by telephone or text message to demand any form of payment"; verify with publicly available contact details, not the caller's.
- **05:** contact your financial institution at once to request a recall or reversal; reset the password and any account that reuses it; file at ic3.gov. Law enforcement does not charge victims a fee (I-081123-PSA).

## 9. Slate for episodes 06-30

An episode without an official page that we have opened and read does not ship. "IC3 PSA..." rows name an alert that is listed on the IC3 index; its page still has to be read when the script is written. "To find" rows have no confirmed page yet.

| # | Pillar | Working title | Source |
|---|---|---|---|
| 06 | Scam of the Week | Your parcel is "held": the delivery text | To find |
| 07 | Reply or delete? | "Is this still your number?" | To find |
| 08 | Real or me? | The kidnapper's photo is edited | IC3 PSA251205, altered proof-of-life media |
| 09 | Send this to your parents | No real support desk tells you to call a pop-up | IC3 PSA230718, tech support scams |
| 10 | The first 60 minutes | You read out the six-digit code | To find |
| 11 | Scam of the Week | The parcel you did not order, with a QR code inside | IC3 PSA250731, QR codes in packages |
| 12 | Reply or delete? | "We're hiring: $300 a day, phone only" | IC3 PSA240604, work-from-home scams |
| 13 | Real or me? | The celebrity selling an investment | To find |
| 14 | Send this to your parents | The grandchild in trouble | IC3 PSA231117, grandparent scams |
| 15 | The first 60 minutes | You let "support" into your computer | IC3 PSA230929, Phantom Hacker |
| 16 | Scam of the Week | The courier coming to collect | IC3 PSA260615, couriers in crypto scams |
| 17 | Reply or delete? | "Your account is locked, verify here" | To find |
| 18 | Real or me? | "Pay to verify you are real" on a dating app | IC3 PSA240426, dating verification schemes |
| 19 | Send this to your parents | The FBI does not phone you to return your money | IC3 PSA250418, IC3 impersonation |
| 20 | The first 60 minutes | Your phone suddenly has no signal | To find |
| 21 | Scam of the Week | The cheque that is larger than the price | To find |
| 22 | Reply or delete? | "You've won. Pay the fee to claim" | To find |
| 23 | Real or me? | The voice note from a "friend" with a new number | To find |
| 24 | Send this to your parents | The charity caller after a disaster | IC3 PSA250116, charity fraud |
| 25 | The first 60 minutes | You typed your password into the fake page | To find (CISA phishing guidance) |
| 26 | Scam of the Week | The flat that is too cheap to view | To find |
| 27 | Reply or delete? | "IC3 has found your money" | IC3 PSA260720, IC3 impersonation |
| 28 | Real or me? | The romance that can never video call | To find |
| 29 | Send this to your parents | One code, one rule: never read it to a caller | To find (CISA multi-factor guidance) |
| 30 | The first 60 minutes | You sent crypto. Who to tell, in order | To find |

## 10. Production pipeline

1. Add the script to `episodes.json` (hook card, narration, check, source link, caption).
2. `python tools/gates.py --links` must pass.
3. `python pipeline/make_episode.py epNN` renders the short: local Kokoro synthetic voice (same voice every day, no network), sound cues, captions of at most 3 words with estimated word timing, AI badge, source line.
4. Watch it once. A human look is required before every post.
5. `python pipeline/autopost.py post` (dry run), then `--live`, schedules it through Buffer to YouTube Shorts, Instagram Reels and TikTok.

Current limits, stated plainly: Vera is a still AI portrait with camera motion, and one synthetic voice performs every part. A lip-synced clip from any talking-head tool can be dropped in as `assets/presenter.mp4` and the renderer will use it.

## 11. How it could earn (hypotheses, not promises)

- Platform revenue share once eligibility thresholds are met (check the current YouTube Partner Programme rules; they change).
- A free printable "family secret word" card to build an email list.
- Clearly disclosed affiliate links for password managers and hardware security keys.
- Licensing short awareness clips to banks, credit unions and telecoms that already run scam-awareness campaigns.

## 12. The 30-day test

Post 20 episodes, then judge by the numbers in `niche.md` (view-through, shares and saves per 1,000 views, viewer submissions, "AI slop" comment share). If two or more fail, change the format before making more. This test, not this document, decides whether the channel beats what exists.
