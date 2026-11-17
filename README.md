# Vera Checks

*"Ten seconds. Check first."*

(The repo is still named `not-real-vera`, the project's first working title.)

A short-video channel about scam and deepfake defence with one on-camera presenter, Vera. Each 35-45 second
episode shows one scam, how it is built to work on you, and one 10-second check that stops it. Every check is traced to an official alert that was opened and read.

This repo holds the whole channel as files: the niche research, the channel rules, five scripted episodes,
the renderer that turns a script into a vertical video, and the tool that schedules approved episodes to
YouTube Shorts, Instagram Reels and TikTok through Buffer.

**Status: cancelled on 2026-11-17. Nothing was ever posted.** This repo is the one remaining copy of the
project. The local working files, the voice and depth models and the five rendered videos were deleted;
the videos can be rendered again from this repo with the commands below.

## What is in here

| File | What it is |
|---|---|
| `niche.md` | Why this niche: evidence table, scoring matrix, and the 30-day test that decides if it works |
| `channel_bible.md` | The host, the voice, the fixed format, the source rules, the 30-episode slate |
| `episodes.json` | The five launch episodes: script, the two short on-screen chips, check, source, caption, hashtags |
| `docs/sources/` | The text of each FBI IC3 alert the scripts were written from |
| `pipeline/make_episode.py` | Renders one episode to a 1080x1920 video: voice, moving presenter, camera, word-by-word captions, music |
| `pipeline/camera.py` | The camera and her head: a jump cut per spoken line, depth parallax, drift, breathing, nods, and a meter for how much the picture moves |
| `pipeline/lipsync.py` | Mouth shapes for every frame, worked out from the words' sounds and the loudness of the voice |
| `pipeline/face_rig.py` | Draws those mouth shapes, blinks and raised eyebrows by warping the still |
| `pipeline/sound.py` | Music bed made from code (no licence needed), ducking under the voice, voice polish, loudness |
| `pipeline/word_timing.py` | Finds when each word is spoken, so the highlighted caption word follows the voice |
| `pipeline/autopost.py` | Schedules approved episodes through Buffer. Dry run unless you add `--live` |
| `tools/presenter_kit.py` | Makes the talking presenter clip for an episode, or exports what an avatar tool needs |
| `tools/outfits.py` | Vera's wardrobe: one presenter still per episode, same face, a different outfit each time |
| `tools/get_motion_models.py` | One-time download of the depth model and the speech model |
| `tools/remix_audio.py` | Mixes an episode's sound again without rendering the picture again |
| `tools/face_landmarks.py` | One-time: finds eyes, mouth and jaw on each outfit still and saves them to `assets/outfits/landmarks.json` |
| `tools/motion_check.py` | Measures how much the picture moves in a finished video |
| `tools/gates.py` | Fourteen pass/fail checks on scripts and renders (thirteen without `--links`) |
| `tests/` | Offline tests: scheduler, sound, word timing, lip-sync, face rig, camera |
| `rubric.md` | The frozen scoring rubric the scripts were judged against |

## Make the videos

```
pip install requests pillow numpy scipy opencv-python imageio-ffmpeg kokoro-onnx onnxruntime vosk
python tools/get_voice_model.py          # one-time, 120 MB voice model into models/
python tools/get_motion_models.py        # one-time, depth model (66 MB) and speech model (40 MB) into models/
python pipeline/make_episode.py ep01     # or: all
python tools/remix_audio.py ep01         # after a change in pipeline/sound.py: new sound, same picture
python tools/motion_check.py             # how much the picture moves in each finished video
python tools/gates.py --links            # fourteen checks, including that every source link answers
```

Renders land in `output/`. On a laptop without a graphics card one episode took about 10 to 12 minutes
with two rendering at once, and 23 minutes when another program was also using the processor; most of
that is drawing the frames in Python. Run at most two at once: three at the same time ran the PC out of
memory and all three stopped.

What the renderer does with a still picture, all on the CPU:

- **Presenter.** The still is warped frame by frame so she talks: her mouth opens, closes and rounds with
  the words, she blinks, her eyebrows lift at the start of a line and on a question, her head shifts, tilts
  and dips on loud syllables, and her chest rises as she breathes. See "Lip-sync and motion".
- **Camera.** Every spoken line is its own shot: the framing jumps at the start of the line (a jump cut,
  the way talking-head shorts are edited) and creeps in until the next one. A depth model (MiDaS small)
  estimates how far each part of the picture is, so the room slides behind her as the camera drifts. The
  sign-off shot pushes in until the last frame, so the picture is still moving after her last word.
- **Captions.** A speech recogniser (Vosk) listens to each spoken line and reports when each word starts.
  Captions are at most three words and each word appears at the moment she says it, in the accent colour
  with a small pop. Digits in a script ("I C 3 dot gov") are matched as the words the voice says
  ("three"). A word the recogniser cannot place is spaced between its neighbours and counted in the
  episode's report.
- **Text on screen.** Nothing to read at length: the pillar name, one chip of at most five words that names
  the scam and then the check, a short source credit ("Source: FBI IC3"), and the sign-off. The scam's
  wording is spoken, not shown; the alert number and its link are in the post caption.
- **Sound.** A music bed is generated per episode; numbered episodes walk through five keys and five
  tempos, so neighbours never share either. It is turned down while she speaks, with an impact on the
  check. The voice gets a light polish, the mix is stereo, and the loudness
  is set to -14 LUFS with the true peak at or under -1 dBTP, which is what the three platforms play at.

## Lip-sync and motion

The presenter is one still per episode, and the renderer makes it move on the CPU with no model download:

1. `pipeline/word_timing.py` already knows when each word is spoken.
2. `pipeline/lipsync.py` turns each word into its sounds with the voice engine's own phonemizer and gives
   every sound a mouth shape (how far open, how wide). B, M and P close the lips for at least 85 ms. How far
   the mouth opens follows how loud the voice is at that instant, so silence returns to the still's smile.
3. `pipeline/face_rig.py` draws that shape by warping the picture around 98 face landmarks: the lower lip
   and chin slide down and a dark mouth shows behind the upper teeth, or the lips slide together until they
   meet. It also draws blinks (every 2 to 5 seconds) and raised eyebrows.
4. `pipeline/camera.py` moves her head as one piece about the base of her neck and moves the camera.

This is the lip-sync a game character gets, applied to a photo. It is not a neural talking-head model
(Wav2Lip, SadTalker): those need a graphics card, and on this laptop SadTalker did not finish four frames
in five and a half minutes.

Measured on the five renders in `output/` (each `output/epNN.json` holds its own numbers):

| Episode | Lip-sync correlation | Best shift (frames) | Lip closures | Blinks | Motion, mean (before → after) | Quietest second (before → after) | Cuts (before → after) |
|---|---|---|---|---|---|---|---|
| ep01 | 0.654 | 0 | 29 | 10 | 0.372 → 0.711 | 0.026 → 0.455 | 2 → 9 |
| ep02 | 0.595 | 0 | 31 | 11 | 0.380 → 0.739 | 0.073 → 0.254 | 2 → 10 |
| ep03 | 0.627 | 0 | 33 | 11 | 0.338 → 0.701 | 0.029 → 0.231 | 3 → 9 |
| ep04 | 0.631 | 0 | 36 | 10 | 0.394 → 0.705 | 0.050 → 0.337 | 2 → 10 |
| ep05 | 0.619 | 0 | 37 | 12 | 0.374 → 0.747 | 0.037 → 0.287 | 2 → 10 |

- *Lip-sync* is the correlation between how far the drawn mouth is open and how loud the voice is, frame by
  frame, and the shift at which that correlation is highest (0 frames means the mouth is neither early nor
  late). The mouth is drawn from the voice, so this catches timing mistakes. It does not measure whether the
  mouth looks real.
- *Motion* is the mean change in brightness between neighbouring frames (0 to 255) in the part of the frame
  that holds her face and shoulders, measured on the finished frames before encoding. *Quietest second* is
  the stillest one-second stretch of the video. "Before" is the previous version: camera drift on a still.
- The first version of this change left the last second of episode 3 at 0.141, under the 0.15 the gate asks
  for: after her last word the darkened end card barely moved. The sign-off push-in fixed that; the
  threshold was not lowered.

## Presenter

The renderer looks for the presenter in this order: `assets/presenter/<id>.mp4` (a talking clip made from that
episode's own voice track, played in sync), then `assets/presenter.mp4` (a generic clip, looped), then that
episode's wardrobe still `assets/outfits/<id>.jpg`, then the old portrait `assets/vera.jpg`. The five episodes
in `output/` use their wardrobe stills, moved by the built-in lip-sync above. A still needs its face
landmarks in `assets/outfits/landmarks.json` for the face to move; without them only the camera, her head
and her breathing move. After a new outfit still, run `tools/face_landmarks.py` once (it needs the
`.presenter` environment below).

A talking clip replaces the moving still and is the way to get hands, a turning head and a real mouth:

```
python tools/presenter_kit.py export all     # writes output/_work/<id>/voice.wav for each episode
python tools/presenter_kit.py status         # which episodes already have a clip
```

Give `assets/outfits/<id>.jpg` and that episode's `voice.wav` to an audio-driven avatar tool, save the result as
`assets/presenter/<id>.mp4`, and render that episode again. Keep the full audio length and do not trim the
start, or the lips drift.

`python tools/presenter_kit.py sadtalker ep01` runs the open-source SadTalker model locally instead. It needs a
separate setup in `.presenter/` (not in this repo): a virtual environment with CPU PyTorch, a clone of SadTalker
with its weights, a few small patches for NumPy 2, and `ffmpeg.exe` in `.presenter/bin`. SadTalker moves lips,
eyes and head on a 256-pixel face. It does not move hands or body. On the laptop this was built on (no graphics
card) it ran through audio analysis but the face renderer did not finish its first 4 frames in five and a half
minutes, so no episode uses it. It needs a machine with a graphics card.

## Wardrobe

Vera wears a different top in every episode. `assets/outfits/base.jpg` is one generated picture of her. Each
`assets/outfits/<id>.jpg` is made from it in two steps: `dress` paints only the clothing area again, then
`finish` runs the whole picture through the model once more at low strength, which removes the seam around the
new clothing, and copies the face back from the base picture. So the face is the same pixels in every episode;
hair, arms and room are close but not identical. `assets/outfits/outfits.json` records the prompt and seeds.

The base picture has her arms at her sides, and the repainted area is everything below the collarbone
including both arms, so sleeves of any length work. Name what she wears below the top, and write a
full-length top or a one-piece dress: a top with no bottoms named can come back as nightwear, and a cropped
top with a bare midriff was blanked by the service's safety filter. When that happens, add fabric. Do not
try other seeds to get past the filter.

```
python tools/outfits.py base             # four trial base pictures into assets/candidates/
python tools/outfits.py base --use 611   # keep one
python tools/outfits.py dress            # one outfit per episode (edit OUTFIT_BY_EPISODE to change them)
python tools/outfits.py dress ep03 --seed 5   # redo one
python tools/outfits.py finish           # remove the seams and put the base face back, all episodes
python tools/outfits.py finish ep03 --seed 5  # redo one
```

Pictures come from [AI Horde](https://aihorde.net), a free volunteer service, with the anonymous key: about 5
to 10 minutes per picture in the queue. Vera is written as an adult of twenty-seven and reads as late
twenties; the prompt rules out anyone who looks younger than an adult. The styling is glamorous and fitted
with low necklines, and stops where YouTube, Instagram and TikTok stop for the normal feed: no lingerie,
nothing see-through, no bare midriff, nothing explicit. The service's own safety filter stays on. A new base
picture needs a new `CLOTHING_POLYGON` and `FACE_CENTER` in `tools/outfits.py`.

## Post them

1. Create the YouTube, Instagram and TikTok accounts for the channel.
2. Connect all three in one Buffer login. The free plan holds three channels.
3. Create an API key in Buffer and save it as one line in `~/.notrealvera/buffer_key.txt`
   (or set the environment variable `BUFFER_API_KEY`). The key never goes in this folder.
4. Then:

```
python pipeline/autopost.py check          # are the three channels connected, are the video links public
python pipeline/autopost.py approve ep01   # after you watched output/ep01.mp4
python pipeline/autopost.py publish        # copies approved episodes to media/ and pushes, so Buffer can fetch them
python pipeline/autopost.py post           # dry run: prints the exact request, sends nothing
python pipeline/autopost.py post --live    # schedules one episode on all three platforms
```

5. When the first live post looks right, double-click `schedule_task.bat`. It runs `run_daily.bat` once a day,
   which schedules the next approved episode. Unapproved episodes are never published or scheduled, and an
   episode is never scheduled twice.

Posts carry each platform's own AI-content label (YouTube, Instagram and TikTok require it for a realistic
synthetic presenter). The videos and captions themselves do not mention it. The label is the
`isAiGenerated` setting in `pipeline/autopost.py` and it stays on: all three platforms can remove a video
or restrict an account when a realistic generated person is posted without it, and a channel that teaches
people to spot fakes loses its reason to exist if it is caught hiding one. Nothing in this repo tries to
get past the platforms' own detection.

## Rules the channel keeps

- Vera never claims a human life story, a job or credentials, and never uses a real person's face, voice or name.
- No statistic is spoken unless its source page was opened and read.
- Example links use `.example` domains. No real company is named as the scammer's disguise.
- One human approves every episode before it goes out.

## What is not good enough yet

- Vera is one picture per episode, warped. Her lips, eyelids, eyebrows and head move by rule, in time with
  the voice. Her hands and body do not gesture and her head cannot turn. The tongue and lower teeth are not
  drawn: an open mouth is a dark crescent under upper teeth that stay where they are. A blink is a flat
  painted eyelid. Up close and at full speed this may read as an animated photo, not as a filmed person.
  A talking clip per episode fixes that; see "Presenter". It needs a graphics card or a paid avatar service.
- The videos were checked from still frames and measurements. Nobody has watched one from start to finish
  or listened to the sound yet, so nobody has judged how the lip-sync looks in motion.
- Only the face is identical between episodes. Hair, arms, hands and the room behind her change a little
  with each outfit. Episode 2 came out as velvet where satin was asked for, and episode 3 as a cream
  scoop-neck dress where pure white with a square neckline was asked for.
- The music is turned down under the voice, but the pauses between lines are short, so it only comes up
  about 1 dB between them. It sits 17 dB under the voice throughout.
- One synthetic voice plays every part, so the "performed" scam calls do not change voice.
- Suggestive styling on a scam-defence channel may cost trust with the people the channel is for, and
  platforms give less reach to videos they class as suggestive. The 30-day test will show it.
- The numbers in `niche.md` come from search summaries and are marked by confidence. The scoring matrix is a
  judgement, not a measurement.
- Whether the handle `@verachecks` is free has not been checked.
- "Beats the market" is a hypothesis. The 30-day test in `niche.md` is what decides it.

## Credits

- Voice: [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) (Apache-2.0), run locally.
- Presenter pictures: generated with Juggernaut XL through AI Horde (`assets/outfits/`); the older portrait
  `assets/vera.jpg` with FLUX.1-schnell. The person does not exist.
- Lip-sync, blinks and head movement: this repo's own code (`pipeline/lipsync.py`, `pipeline/face_rig.py`,
  `pipeline/camera.py`). Face landmarks for it: [facexlib](https://github.com/xinntao/facexlib) (MIT), run once per still.
- Optional lip-sync: [SadTalker](https://github.com/OpenTalker/SadTalker) (Apache-2.0). Not used in the current renders.
- Depth for the camera move: [MiDaS](https://github.com/isl-org/MiDaS) small (MIT), run locally.
- Caption word timing: [Vosk](https://alphacephei.com/vosk/) small English model (Apache-2.0), run locally.
- Music and sound cues: generated by `pipeline/sound.py`. No samples, nothing to license.
- Sources: FBI Internet Crime Complaint Center public service announcements, [ic3.gov](https://www.ic3.gov).
