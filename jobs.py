"""Score generation runs in the background.

A five-minute piece takes a few minutes to write, which is too long to hold a
request open. Starting one returns a job id at once; the page asks about it
every couple of seconds, hears which stage it is at, and picks up the score
when it is done. The page keeps the id, so leaving and coming back finds the
same job.

Jobs live in this process's memory: a server restart forgets them, and a
finished one is dropped an hour after it was started.
"""

import threading
import time
import uuid

KEEP_SECONDS = 3600

_jobs = {}
_lock = threading.Lock()


def _forget_old():
    cutoff = time.time() - KEEP_SECONDS
    for job_id in [job_id for job_id, job in _jobs.items() if job["started"] < cutoff]:
        del _jobs[job_id]


def start(owner, work, failure):
    """Run work(progress) on a thread of its own and return the job id.

    `failure` is the exception type whose message can be shown as it is;
    anything else is reported as an unexpected error.
    """
    job_id = uuid.uuid4().hex
    job = {"owner": owner, "state": "running", "stage": "", "started": time.time(),
           "result": None, "error": ""}
    with _lock:
        _forget_old()
        _jobs[job_id] = job

    def progress(text):
        job["stage"] = text

    def run():
        try:
            job["result"] = work(progress)
            job["state"] = "done"
        except failure as error:
            job["error"], job["state"] = str(error), "failed"
        except Exception as error:  # a bug, not a GPT failure; say so plainly
            job["error"], job["state"] = f"예상하지 못한 오류가 났습니다: {error}", "failed"
            raise

    threading.Thread(target=run, daemon=True).start()
    return job_id


def status(job_id, owner):
    """The job as the page sees it, or None if there is no such job for this owner."""
    job = _jobs.get(job_id)
    if job is None or job["owner"] != owner:
        return None
    report = {"state": job["state"], "stage": job["stage"], "elapsed": round(time.time() - job["started"])}
    if job["state"] == "done":
        report["score"] = job["result"]
    elif job["state"] == "failed":
        report["error"] = job["error"]
    return report
