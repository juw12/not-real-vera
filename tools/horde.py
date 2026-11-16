"""Small client for AI Horde (https://aihorde.net), the free volunteer image service used for Vera's wardrobe.

Anonymous key, so requests wait in the low-priority queue. Images come back inline (base64), not as links.
"""
import base64
import io
import time

import requests
from PIL import Image

API = "https://aihorde.net/api/v2"
HEADERS = {
    "apikey": "0000000000",
    "Client-Agent": "verachecks:1:github.com/juw12/not-real-vera",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) verachecks/1",
}
NEGATIVE = (
    "nsfw, nude, lingerie, see-through, child, teen, cartoon, illustration, 3d render, painting, doll, "
    "plastic skin, airbrushed, deformed, extra fingers, bad hands, text, watermark, logo"
)


def encode_image(image):
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", lossless=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def request_json(method, path, attempts=5, **arguments):
    """The office proxy drops a request now and then; retry with a pause."""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.request(method, API + path, headers=HEADERS, timeout=90, **arguments)
            if response.status_code in (429, 502, 503, 504):
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:160]}")
            return response
        except (requests.RequestException, RuntimeError) as error:
            print(f"  {method} {path} attempt {attempt} failed: {str(error)[:160]}", flush=True)
            if attempt == attempts:
                raise
            time.sleep(8 * attempt)


def generate(
    prompt,
    model,
    seed,
    width,
    height,
    steps=30,
    cfg_scale=5.0,
    source_image=None,
    source_mask=None,
    denoising_strength=1.0,
    max_wait_seconds=1500,
):
    """Return one PIL image, or raise RuntimeError with the service's reason."""
    payload = {
        "prompt": f"{prompt} ### {NEGATIVE}",
        "params": {
            "sampler_name": "k_dpmpp_2m",
            "karras": True,
            "cfg_scale": cfg_scale,
            "steps": steps,
            "width": width,
            "height": height,
            "seed": str(seed),
            "n": 1,
        },
        "models": [model],
        "nsfw": False,
        "censor_nsfw": True,
        "r2": False,
        "shared": False,
        "slow_workers": True,
        "trusted_workers": False,
    }
    if source_image is not None:
        payload["source_image"] = encode_image(source_image)
        payload["params"]["denoising_strength"] = denoising_strength
        if source_mask is not None:
            payload["source_processing"] = "inpainting"
            payload["source_mask"] = encode_image(source_mask)
        else:
            payload["source_processing"] = "img2img"

    submitted = request_json("POST", "/generate/async", json=payload)
    if submitted.status_code != 202:
        raise RuntimeError(f"submit refused ({submitted.status_code}): {submitted.text[:300]}")
    job_id = submitted.json()["id"]
    started = time.time()
    while True:
        time.sleep(8)
        check = request_json("GET", f"/generate/check/{job_id}").json()
        waited = int(time.time() - started)
        print(
            f"  job {job_id[:8]} waited {waited}s queue={check.get('queue_position')} "
            f"eta={check.get('wait_time')}s done={check.get('done')}",
            flush=True,
        )
        if check.get("faulted"):
            raise RuntimeError("job faulted on the worker")
        if not check.get("is_possible", True):
            raise RuntimeError("no worker can do this job right now")
        if check.get("done"):
            break
        if waited > max_wait_seconds:
            request_json("DELETE", f"/generate/status/{job_id}")
            raise RuntimeError(f"gave up after {waited}s in the queue")
    status = request_json("GET", f"/generate/status/{job_id}").json()
    generations = status.get("generations") or []
    if not generations:
        raise RuntimeError(f"finished without an image: {str(status)[:300]}")
    generation = generations[0]
    if generation.get("censored"):
        raise RuntimeError("the worker's safety filter blanked this image")
    image = Image.open(io.BytesIO(base64.b64decode(generation["img"]))).convert("RGB")
    return image, generation.get("model", model), generation.get("worker_name", "")
