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
| `pipeline/make_episode.py` | Renders one episode to a 1080x1920 video with voice, captions and sound cues |
| `pipeline/autopost.py` | Schedules approved episodes through Buffer. Dry run unless you add `--live` |
| `tools/presenter_kit.py` | Makes the talking presenter clip for an episode, or exports what an avatar tool needs |
| `tools/gates.py` | Nine pass/fail checks on scripts and renders |
| `tests/test_autopost.py` | Offline tests for the scheduler |
| `rubric.md` | The frozen scoring rubric the scripts were judged against |

## Make the videos

```
pip install requests pillow numpy opencv-python imageio-ffmpeg kokoro-onnx
python tools/get_voice_model.py          # one-time, 120 MB voice model into models/
python pipeline/make_episode.py ep01     # or: all
python tools/gates.py --links            # nine checks, including that every source link answers
```

Renders land in `output/`. On a busy laptop without a graphics card one episode took 12 to 22 minutes
in the two measured runs; most of that is drawing the frames in Python.

## Presenter

The renderer looks for the presenter in this order: `assets/presenter/<id>.mp4` (a talking clip made from that
episode's own voice track, played in sync), then `assets/presenter.mp4` (a generic clip, looped), then the still
portrait `assets/vera.jpg`. The five episodes in `output/` currently use the still portrait.

To get a talking presenter:

```
python tools/presenter_kit.py export all     # writes output/_work/<id>/voice.wav for each episode
python tools/presenter_kit.py status         # which episodes already have a clip
```

Give `assets/vera.jpg` and one `voice.wav` to an audio-driven avatar tool, save the result as
`assets/presenter/<id>.mp4`, and render that episode again. Keep the full audio length and do not trim the
start, or the lips drift.

`python tools/presenter_kit.py sadtalker ep01` runs the open-source SadTalker model locally instead. It needs a
separate setup in `.presenter/` (not in this repo): a virtual environment with CPU PyTorch, a clone of SadTalker
with its weights, a few small patches for NumPy 2, and `ffmpeg.exe` in `.presenter/bin`. SadTalker moves lips,
eyes and head on a 256-pixel face. It does not move hands or body. On the laptop this was built on (no graphics
card) it ran through audio analysis but the face renderer did not finish its first 4 frames in five and a half
minutes, so no episode uses it. It needs a machine with a graphics card.

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
synthetic presenter). The videos and captions themselves do not mention it.

## Rules the channel keeps

- Vera never claims a human life story, a job or credentials, and never uses a real person's face, voice or name.
- No statistic is spoken unless its source page was opened and read.
- Example links use `.example` domains. No real company is named as the scammer's disguise.
- One human approves every episode before it goes out.

## What is not good enough yet

- The rendered episodes show Vera as a still portrait with camera movement. Her lips, face and hands do not
  move. A talking clip per episode fixes that; see "Presenter".
- One synthetic voice plays every part, so the "performed" scam calls do not change voice.
- The numbers in `niche.md` come from search summaries and are marked by confidence. The scoring matrix is a
  judgement, not a measurement.
- Whether the handle `@verachecks` is free has not been checked.
- "Beats the market" is a hypothesis. The 30-day test in `niche.md` is what decides it.

## Credits

- Voice: [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) (Apache-2.0), run locally.
- Portrait: generated with FLUX.1-schnell. The person does not exist.
- Optional lip-sync: [SadTalker](https://github.com/OpenTalker/SadTalker) (Apache-2.0). Not used in the current renders.
- Sources: FBI Internet Crime Complaint Center public service announcements, [ic3.gov](https://www.ic3.gov).
