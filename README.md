# Not Real Vera

*"I'm not real. The scams are."*

A short-video channel about scam and deepfake defence, hosted by a presenter who says in the first two lines
that she is an AI. Each 35-45 second episode shows one scam, how an AI would write it, and one 10-second check
that stops it. Every check is traced to an official alert that was opened and read.

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

Renders land in `output/`. On a laptop without a graphics card one episode takes about five minutes.

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

Posts are marked as AI-generated on all three platforms, and the caption ends with "Host is AI-generated."

## Rules the channel keeps

- Vera never pretends to be human and never uses a real person's face, voice or name.
- No statistic is spoken unless its source page was opened and read.
- Example links use `.example` domains. No real company is named as the scammer's disguise.
- One human approves every episode before it goes out.

## What is not good enough yet

- Vera is a still AI portrait with camera movement, not a lip-synced talking head. Drop a lip-synced clip at
  `assets/presenter.mp4` and the renderer uses it instead.
- One synthetic voice plays every part, so the "performed" scam calls do not change voice.
- The portrait is a free-tier image, upscaled, and keeps a small pollinations.ai corner mark.
- The numbers in `niche.md` come from search summaries and are marked by confidence. The scoring matrix is a
  judgement, not a measurement.
- Whether the handle `@notrealvera` is free has not been checked.
- "Beats the market" is a hypothesis. The 30-day test in `niche.md` is what decides it.

## Credits

- Voice: [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) (Apache-2.0), run locally.
- Portrait: generated with [pollinations.ai](https://pollinations.ai). The person does not exist.
- Sources: FBI Internet Crime Complaint Center public service announcements, [ic3.gov](https://www.ic3.gov).
