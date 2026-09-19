import schedule
import time
import asyncio
import sys
import copy
from datetime import datetime

import workflow
import utils

# Scheduled post definitions
# add as many slots as you like 
SCHEDULE: list[dict] = [
    {
        "time": "9:00",
        "topic": None,
        "style": None,
        "extra_context": "",
    },
]


def _make_job_fn(topic, style, dry_run):
    """Return a plain sync function for schedule.do() - saves to queue."""
    def _fn():
        utils.log(f"⏰ Scheduler: firing job at {datetime.now().strftime('%H:%M')}")
        asyncio.run(workflow.run(
            topic=topic or None,
            style=style or None,
            dry_run=dry_run,
            auto_approve=False,  # Don't auto-post
            save_to_queue=True,  # Save to pending queue
        ))
    return _fn


def _run_job(slot: dict) -> None:
    """ Sync wrapper so schedule  can call our async workflow."""
    utils.log(f"⏰ Scheduled job triggered at {datetime.now().strftime('%H:%M')}")
    asyncio.run(workflow.run(
        topic = slot.get("topic"),
        style = slot.get("style"),
        extra_context = slot.get("extra_context", ""),
        dry_run = slot.get("dry_run", False)

))
    
def start(daily_time: str = None) -> None:
    """
    Register all slots and start the blocking scheduler loop.
    If daily_time is given it overrides the first slot time.
    """
    utils.ensure_folders()
    slots = copy.deepcopy(SCHEDULE)

    if daily_time:
        slots[0]["time"] = daily_time

    utils.log("📅 Registering scheduled posts...")
    for i , slot in enumerate(slots):
        t = slot["time"]
        schedule.every().day.at(t).do(_run_job, slot=slot)
        label = slot.get("topic") or "random topic"
        utils.log(f" [{i+1}] {t} daily -- {label[:50]}")

    utils.log("\n🤖 Scheduler running. Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        nxt = schedule.next_run()
        if nxt:
            utils.log(f"💤 Next run: {nxt.strftime('%Y-%m-%d %H:%M')}")
        time.sleep(60)

if __name__ == "__main__":
    arg_time = sys.argv[1] if len(sys.argv)> 1 else None
    start(arg_time)



