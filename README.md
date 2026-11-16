# Vera Checks

*"Ten seconds. Check first."*

(The repo is still named `not-real-vera`, the project's first working title.)

A short-video channel about scam and deepfake defence with one on-camera presenter, Vera. Each 35-45 second
episode shows one scam, how it is built to work on you, and one 10-second check that stops it. Every check is traced to an official alert that was opened and read.

This repo holds the whole channel as files: the niche research, the channel rules, five scripted episodes,
the renderer that turns a script into a vertical video, and the tool that schedules approved episodes to
YouTube Shorts, Instagram Reels and TikTok through Buffer.

**Status: nothing has been posted.** The episodes are rendered locally and wait for a human to watch and
approve them.

## What is in here

| File | What it is |
|---|---|
| `niche.md` | Why this niche: evidence table, scoring matrix, and the 30-day test that decides if it works |
| `channel_bible.md` | The host, the voice, the fixed format, the source rules, the 30-episode slate |
| `episodes.json` | The five launch episodes: script, on-screen card, check, source, caption, hashtags |
| `docs/sources/` | The text of each FBI IC3 alert the scripts were written from |
| `pipeline/make_episode.py` | Renders one episode to a 1080x1920 video: voice, camera motion, captions timed to the voice, music |
| `pipeline/camera.py` | The camera move: a depth map of the still gives parallax, a spring smooths every push and drift |
| `pipeline/sound.py` | Music bed made from code (no licence needed), ducking under the voice, voice polish, loudness |
| `pipeline/word_timing.py` | Finds when each word is spoken, so the highlighted caption word follows the voice |
| `pipeline/autopost.py` | Schedules approved episodes through Buffer. Dry run unless you add `--live` |
| `tools/presenter_kit.py` | Makes the talking presenter clip for an episode, or exports what an avatar tool needs |
| `tools/outfits.py` | Vera's wardrobe: one presenter still per episode, same face, a different outfit each time |
| `tools/get_motion_models.py` | One-time download of the depth model and the speech model |
| `tools/remix_audio.py` | Mixes an episode's sound again without rendering the picture again |
| `tools/gates.py` | Ten pass/fail checks on scripts and renders |
| `tests/test_autopost.py` | Offline tests for the scheduler |
| `rubric.md` | The frozen scoring rubric the scripts were judged against |

## Make the videos

```
pip install requests pillow numpy scipy opencv-python imageio-ffmpeg kokoro-onnx onnxruntime vosk
python tools/get_voice_model.py          # one-time, 120 MB voice model into models/
python tools/get_motion_models.py        # one-time, depth model (66 MB) and speech model (40 MB) into models/
python pipeline/make_episode.py ep01     # or: all
python tools/remix_audio.py ep01         # after a change in pipeline/sound.py: new sound, same picture
python tools/gates.py --links            # ten checks, including that every source link answers
```

Renders land in `output/`. On a laptop without a graphics card one episode took between about 8 and 16
minutes, depending on what else the PC was doing; most of that is drawing the frames in Python. Run at
most two at once: three at the same time ran the PC out of memory and all three stopped.

What the renderer does with a still picture, all on the CPU:

- **Camera.** A depth model (MiDaS small) estimates how far each part of the picture is. The camera
  pushes in, drifts and reframes on the check, and near parts move more than far parts, so it reads as a
  moving camera and not a zoomed photo. A spring smooths the path, so there are no sudden starts or stops.
  Her chest rises slightly as if breathing and her head sways a little.
- **Captions.** A speech recogniser (Vosk) listens to each spoken line and reports when each word starts.
  The highlighted word changes at that moment. Before this the times were guessed from word length.
  Digits in a script ("I C 3 dot gov") are matched as the words the voice says ("three"). A word the
  recogniser cannot place is spaced between its neighbours and counted in the episode's report.
- **Sound.** A music bed is generated per episode; numbered episodes walk through five keys and five
  tempos, so neighbours never share either. It is turned down while she speaks, with an impact on the
  check. The voice gets a light polish, the mix is stereo, and the loudness
  is set to -14 LUFS with the true peak at or under -1 dBTP, which is what the three platforms play at.

## Presenter

The renderer looks for the presenter in this order: `assets/presenter/<id>.mp4` (a talking clip made from that
episode's own voice track, played in sync), then `assets/presenter.mp4` (a generic clip, looped), then that
episode's wardrobe still `assets/outfits/<id>.jpg`, then the old portrait `assets/vera.jpg`. The five episodes
in `output/` currently use their wardrobe stills.

To get a talking presenter:

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

- Vera is still one picture per episode. The camera moves, the picture has depth, and she breathes and
  sways slightly, but her lips, eyes, expression and hands do not move. A talking clip per episode fixes
  that; see "Presenter". It needs a graphics card or a paid avatar service.
- The videos were checked from still frames and measurements. Nobody has watched one from start to finish
  or listened to the sound yet.
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
- Optional lip-sync: [SadTalker](https://github.com/OpenTalker/SadTalker) (Apache-2.0). Not used in the current renders.
- Depth for the camera move: [MiDaS](https://github.com/isl-org/MiDaS) small (MIT), run locally.
- Caption word timing: [Vosk](https://alphacephei.com/vosk/) small English model (Apache-2.0), run locally.
- Music and sound cues: generated by `pipeline/sound.py`. No samples, nothing to license.
- Sources: FBI Internet Crime Complaint Center public service announcements, [ic3.gov](https://www.ic3.gov).
