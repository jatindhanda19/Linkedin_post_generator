import asyncio
import json
import os
import secrets
import threading
import random
import time as time_lib
from datetime import datetime

import schedule as schedule_lib
from flask import Flask, jsonify, render_template, request, send_from_directory

import ai_generator
import Config
import utils
import workflow
from workflow import(
    PostState,
    generate_post,
    pick_topic,
    post_to_linkedin,
    regenerate_with_image,
    save_log,
)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

_STATE_FILE = "sessions/web_state.json"
_SCHEDULER_FILE = "sessions/scheduler_config.json"

def _save_state(state: dict) -> None:
    os.makedirs("sessions", exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
 
 
def _load_state() -> dict:
    if not os.path.exists(_STATE_FILE):
        return {}
    with open(_STATE_FILE) as f:
        return json.load(f)
 
 
def _blank_state(topic="", style="motivational", extra_context="") -> PostState:
    return {
        "topic": topic, "style": style, "extra_context": extra_context,
        "dry_run": False, "image_path": None, "auto_approve": False,
        "generated": {}, "caption": "",
        "rejection_count": 0, "rejection_note": "",
        "approved": False, "success": False, "error": None, "posted_at": None,
    }
 
 
def _post_response(state: dict) -> dict:
    """Slim dict the frontend needs — no raw state bleed."""
    g = state.get("generated", {})
    image_path = state.get("image_path")
    image_url = (
        f"/assets/{os.path.basename(image_path)}"
        if image_path and os.path.exists(image_path) else None
    )
    return {
        "topic":               state.get("topic", ""),
        "style":               state.get("style", ""),
        "caption":             state.get("caption", ""),
        "hook":                g.get("hook", ""),
        "hashtags":            g.get("hashtags", []),
        "why_it_works":        g.get("why_it_works", ""),
        "suggested_post_time": g.get("suggested_post_time", ""),
        "image_url":           image_url,
        "char_count":          len(state.get("caption", "")),
        "rejection_count":     state.get("rejection_count", 0),
    }
 
 

# Scheduler — background thread management

 
_sched_thread: threading.Thread | None = None
_sched_stop   = threading.Event()
_sched_stop.set()   # starts in "stopped" state
 
 
def _load_sched_cfg() -> dict:
    if not os.path.exists(_SCHEDULER_FILE):
        return {"enabled": False, "jobs": []}
    with open(_SCHEDULER_FILE) as f:
        return json.load(f)
 
 
def _save_sched_cfg(cfg: dict) -> None:
    os.makedirs("sessions", exist_ok=True)
    with open(_SCHEDULER_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
 
 
def _scheduler_loop(stop_event: threading.Event) -> None:
    """Blocking loop — runs in its own daemon thread."""
    while not stop_event.is_set():
        schedule_lib.run_pending()
        stop_event.wait(30)   # wake every 30 s to check pending jobs
 
 
# In App.py, replace the _make_job_fn function with this:

def _make_job_fn(topic, style, dry_run):
    """Return a plain sync function for schedule.do() - saves to queue."""
    def _fn():
        utils.log(f"⏰ Scheduler: firing job at {datetime.now().strftime('%H:%M')}")
        asyncio.run(_scheduled_job(topic, style, dry_run))
    return _fn

async def _scheduled_job(topic, style, dry_run):
    """
    Scheduled job: Generate post and save to pending queue.
    Does NOT post directly - user must approve from queue.
    """
    import workflow
    import ai_generator
    
    utils.log("=" * 55)
    utils.log("⏰ SCHEDULED JOB — Generating post for queue...")
    utils.log("=" * 55)
    
    # Use random topic if none provided
    if not topic:
        topic, auto_style, _ = random.choice(workflow.TOPIC_BANK)
        if not style:
            style = auto_style
    
    utils.log(f"📌 Topic: {topic}")
    utils.log(f"🎨 Style: {style or 'motivational'}")
    
    try:
        # Generate the post using AI
        generated = await ai_generator.generate_post(
            topic=topic,
            style=style or "motivational",
            extra_context="",
        )
        
        # Generate image
        image_path = None
        image_prompt = generated.get("image_prompt", topic)
        try:
            image_path = await ai_generator.generate_image(image_prompt, Config.ASSETS_DIR)
        except Exception as e:
            utils.log(f"⚠️ Image generation skipped: {e}")
        
        # Create queue item
        queue_item = {
            "topic": topic,
            "style": style or "motivational",
            "caption": generated.get("caption", ""),
            "generated": generated,
            "image_path": image_path,
            "scheduled_for": datetime.now().isoformat(),
        }
        
        # Save to pending queue
        workflow.add_to_pending_queue(queue_item)
        utils.log(f"📋 Saved to pending queue: {topic[:50]}")
        
    except Exception as e:
        utils.log(f"❌ Scheduled job failed: {e}")
 
def _start_scheduler(jobs: list) -> None:
    global _sched_thread, _sched_stop
 
    # Tear down any running scheduler first
    _sched_stop.set()
    schedule_lib.clear()
 
    if not jobs:
        utils.log("⚠️  No jobs — scheduler not started")
        return
 
    _sched_stop = threading.Event()
 
    for job in jobs:
        t       = job.get("time", "09:00")
        topic   = job.get("topic", "").strip()
        style   = job.get("style", "")
        dry_run = bool(job.get("dry_run", False))
        schedule_lib.every().day.at(t).do(_make_job_fn(topic, style, dry_run))
        utils.log(f"📅 Job registered: {t} | topic={topic or 'random'} | style={style or 'random'}")
 
    _sched_thread = threading.Thread(
        target=_scheduler_loop, args=(_sched_stop,), daemon=True
    )
    _sched_thread.start()
    utils.log(f"✅ Scheduler started with {len(jobs)} job(s)")
 
 
def _stop_scheduler() -> None:
    global _sched_thread
    _sched_stop.set()
    schedule_lib.clear()
    _sched_thread = None
    utils.log("⏹️  Scheduler stopped")
 
 
def _sched_is_running() -> bool:
    return _sched_thread is not None and _sched_thread.is_alive()
 
 
# Static assets (AI-generated images)
 
@app.route("/assets/<path:filename>")
def serve_asset(filename):
    return send_from_directory(Config.ASSETS_DIR, filename)
 
 

# Pages

@app.route("/")
def index():
    return render_template("index.html", styles=ai_generator.list_styles())
 
 

# Post API

 
@app.route("/api/generate", methods=["POST"])
def api_generate():
    data  = request.get_json(silent=True) or {}
    state = _blank_state(
        topic=data.get("topic", ""),
        style=data.get("style", "motivational"),
        extra_context=data.get("extra_context", ""),
    )
 
    async def _run():
        s = await pick_topic(state)
        return await generate_post(s)
 
    try:
        state = asyncio.run(_run())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
    if state.get("error"):
        return jsonify({"error": state["error"]}), 500
 
    _save_state(state)
    return jsonify(_post_response(state))
 
 
@app.route("/api/regenerate", methods=["POST"])
def api_regenerate():
    state = _load_state()
    if not state:
        return jsonify({"error": "No active session — generate a post first."}), 400
 
    data                  = request.get_json(silent=True) or {}
    state["rejection_note"] = data.get("note", "")
 
    try:
        state = asyncio.run(regenerate_with_image(state))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
    if state.get("error"):
        return jsonify({"error": state["error"]}), 500
 
    _save_state(state)
    return jsonify(_post_response(state))
 
 
@app.route("/api/post", methods=["POST"])
def api_post():
    state = _load_state()
    if not state:
        return jsonify({"error": "No active session — generate a post first."}), 400
 
    data              = request.get_json(silent=True) or {}
    state["approved"] = True
    state["dry_run"]  = bool(data.get("dry_run", False))
 
    async def _run():
        s = await post_to_linkedin(state)
        return await save_log(s)
 
    try:
        final = asyncio.run(_run())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
    return jsonify({
        "success":   final.get("success", False),
        "posted_at": final.get("posted_at"),
        "error":     final.get("error"),
    })
 
 
@app.route("/api/logs")
def api_logs():
    if not os.path.exists(Config.LOG_FILE):
        return jsonify([])
    try:
        with open(Config.LOG_FILE) as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify([])
 
 

# Scheduler API
 
@app.route("/api/scheduler/status")
def sched_status():
    """Running state, next fire time, and current job list."""
    running  = _sched_is_running()
    next_run = None
    if running and schedule_lib.next_run():
        next_run = schedule_lib.next_run().strftime("%Y-%m-%d %H:%M:%S")
    cfg = _load_sched_cfg()
    return jsonify({
        "running":  running,
        "next_run": next_run,
        "jobs":     cfg.get("jobs", []),
    })
 
 
@app.route("/api/scheduler/start", methods=["POST"])
def sched_start():
    """Save jobs config and start the background scheduler thread."""
    data = request.get_json(silent=True) or {}
    jobs = data.get("jobs", [])
    if not jobs:
        jobs = _load_sched_cfg().get("jobs", [])
    if not jobs:
        return jsonify({"error": "Add at least one job before starting."}), 400
 
    _save_sched_cfg({"enabled": True, "jobs": jobs})
    _start_scheduler(jobs)
    return jsonify({"ok": True, "job_count": len(jobs)})
 
 
@app.route("/api/scheduler/stop", methods=["POST"])
def sched_stop():
    """Stop the scheduler thread and persist the disabled state."""
    _stop_scheduler()
    cfg = _load_sched_cfg()
    cfg["enabled"] = False
    _save_sched_cfg(cfg)
    return jsonify({"ok": True})
 
 
@app.route("/api/scheduler/save", methods=["POST"])
def sched_save():
    """Persist job list without starting/stopping the scheduler."""
    data = request.get_json(silent=True) or {}
    cfg  = _load_sched_cfg()
    cfg["jobs"] = data.get("jobs", [])
    _save_sched_cfg(cfg)
    return jsonify({"ok": True})
 
 
@app.route("/api/scheduler/run-now", methods=["POST"])
def sched_run_now():
    """Immediately fire a one-off post (saves to queue)."""
    data = request.get_json(silent=True) or {}
    
    def _fire():
        asyncio.run(_scheduled_job(
            topic=data.get("topic", "").strip() or None,
            style=data.get("style", "") or None,
            dry_run=bool(data.get("dry_run", False)),
        ))
    
    threading.Thread(target=_fire, daemon=True).start()
    return jsonify({
        "ok": True, 
        "message": "Post generated and saved to Pending Approvals queue. Check the queue to review and post."
    })

 ###
@app.route("/api/queue/list")
def api_queue_list():
    """Get all pending posts in the queue."""
    queue = workflow.load_pending_queue()
    return jsonify(queue)

@app.route("/api/queue/post/<post_id>", methods=["POST"])
def api_queue_post(post_id):
    """Post a specific item from the queue to LinkedIn."""
    queue = workflow.load_pending_queue()

      # Find the post in queue
    post_data = None
    for post in queue:
        if post.get("id") == post_id:
            post_data = post
            break
    
    if not post_data:
        return jsonify({"error": "Post not found in queue"}), 404
    
    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run", False))
    
    # Create state from queue item
    async def _post():
        state = {
            "topic": post_data.get("topic", ""),
            "style": post_data.get("style", "motivational"),
            "caption": post_data.get("caption", ""),
            "generated": post_data.get("generated", {}),
            "image_path": post_data.get("image_path"),
            "approved": True,
            "success": False,
            "error": None,
            "posted_at": None,
            "rejection_count": 0,
        }
        
        state = await workflow.post_to_linkedin(state)
        state = await workflow.save_log(state)
        
        if state.get("success"):
            workflow.update_queue_item(post_id, {
                "status": "posted",
                "posted_at": state.get("posted_at")
            })
            return state
    
    try:
        final = asyncio.run(_post())
        return jsonify({
            "success": final.get("success", False),
            "posted_at": final.get("posted_at"),
            "error": final.get("error"),
            "dry_run": final.get("dry_run", False),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/api/queue/remove/<post_id>", methods=["POST"])
def api_queue_remove(post_id):
    """Remove a post from the pending queue."""
    success = workflow.remove_from_queue(post_id)
    if success:
        return jsonify({"ok": True})
    return jsonify({"error": "Post not found"}), 404

@app.route("/api/queue/regenerate/<post_id>", methods=["POST"])
def api_queue_regenerate(post_id):
    """Regenerate a post in the queue."""
    queue = workflow.load_pending_queue()
    
    post_data = None
    for post in queue:
        if post.get("id") == post_id:
            post_data = post
            break
    
    if not post_data:
        return jsonify({"error": "Post not found in queue"}), 404
    
    data = request.get_json(silent=True) or {}
    
    async def _regen():
        state = {
            "topic": data.get("topic") or post_data.get("topic", ""),
            "style": data.get("style") or post_data.get("style", "motivational"),
            "extra_context": data.get("extra_context", ""),
            "rejection_note": data.get("note", ""),
            "rejection_count": post_data.get("rejection_count", 0) + 1,
            "generated": {},
            "caption": "",
            "error": None,
        }
        
        state = await workflow.regenerate_with_image(state)
        
        if not state.get("error") and state.get("caption"):
            # Update queue item with regenerated content
            updates = {
                "caption": state["caption"],
                "generated": state.get("generated", {}),
                "image_path": state.get("image_path"),
                "rejection_count": state.get("rejection_count", 0),
                "topic": state.get("topic", ""),
                "style": state.get("style", ""),
            }
            workflow.update_queue_item(post_id, updates)
        
        return state
    
    try:
        final = asyncio.run(_regen())
        return jsonify({
            "success": not final.get("error"),
            "caption": final.get("caption", ""),
            "generated": final.get("generated", {}),
            "image_url": f"/assets/{os.path.basename(final.get('image_path', ''))}" if final.get("image_path") else None,
            "error": final.get("error"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/queue/edit/<post_id>", methods=["POST"])
def api_queue_edit(post_id):
    """Edit a post in the queue manually."""
    data = request.get_json(silent=True) or {}
    
    updates = {}
    if "caption" in data:
        updates["caption"] = data["caption"]
    if "topic" in data:
        updates["topic"] = data["topic"]
    if "style" in data:
        updates["style"] = data["style"]
    if "scheduled_for" in data:
        updates["scheduled_for"] = data["scheduled_for"]
    
    if updates:
        workflow.update_queue_item(post_id, updates)
        return jsonify({"ok": True})
    
    return jsonify({"error": "No updates provided"}), 400
# Entry point

 
if __name__ == "__main__":
    utils.ensure_folders()
 
    # Auto-resume scheduler if it was enabled when the server last shut down
    cfg = _load_sched_cfg()
    if cfg.get("enabled") and cfg.get("jobs"):
        utils.log("▶️  Auto-resuming scheduler from saved config...")
        _start_scheduler(cfg["jobs"])
 
    print("\n🚀  LinkedIn Auto Poster — Web UI")
    print("   Open: http://localhost:5000\n")
    app.run(debug=False, port=5000)  
