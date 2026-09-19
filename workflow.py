from __future__ import annotations

import json
import os
import random
import secrets
from datetime import datetime
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

import Config
import ai_generator
import Config
import utils

PENDING_QUEUE_FILE = "sessions/pending_queue.json"

class PostState(TypedDict):
    topic: str
    style: str
    extra_context: str
    image_path: Optional[str]
    auto_approve: bool

    generated: dict
    caption: str

    rejection_count: int
    rejection_note: str
    approved: bool

    success: bool
    error: Optional[str]
    posted_at: Optional[str]
    scheduled_for: Optional[str]


TOPIC_BANK: list[tuple[str,str,str]] = [
    ("one Python trick that saves me hours every week", "educational", ""),
    ("The mindset shift that changed how I approach failure at work", "storytelling", ""),
    ("Why automation will be biggest career skill in next 5 years", "thought_leadership", ""),
    ("Morning routine that doubled my focus and Output", "motivational", ""),
    ("3 things I wish I knew before starting  to code", "educational", ""),
    ("How I build side project that automates my social media", "achievement", ""),
    ("The diffrence between busy and productive", "thought_leadership", ""),
    ("what 1000 hours of python taught me about learning anything", "storytelling", ""),
]

async def _generate_image(prompt: str) -> Optional[str]:
    """Generate an image with Gemini and save it to the assets folder."""
    utils.log("Generating image with gemini...")
    result = await ai_generator.generate_image(prompt, Config.ASSETS_DIR)
    if result:
        utils.log(f"Image ready: {result}")
    else:
        utils.log("Image generation failed -- continuing without iamge")
    return result

async def pick_topic(state: PostState) -> PostState:
    """If o topic supplied, choose one at random from topic bank."""
    if state.get("topic"):
        utils.log(f"📌 Topic: {state['topic'][:70]}")
        return state
    
    topic, style, ctx = random.choice(TOPIC_BANK)
    utils.log(f"🎲 Random topic: {topic[:70]}")
    return {**state, "topic": topic, "style": style or state["style"], "extra_context": ctx}

async def generate_post(state: PostState) -> PostState:
    """call Gemini to produce LinkedIN post."""
    utils.log("\n" + "=" *55)
    utils.log("🧠 STEP 1 — AI is generating your post...")
    utils.log("=" * 55)

    try:
        generated = await ai_generator.generate_post(
            topic = state["topic"],
            style= state.get("style") or "motivational",
            extra_context= state.get("extra_context", ""),
        )
        
        # Download image for the initial post
        image_prompt = generated.get("image_prompt", state["topic"])
        image_path = await _generate_image(image_prompt)
        
        return {**state, "generated": generated, "caption": generated["caption"], "image_path": image_path, "error": None}
    except Exception as e:
        utils.log(f"❌ Generation failed: {e}")
        return {**state, "error": str(e), "success": False}
    
async def human_review(state: PostState) -> PostState:
    """
    Show the generated post and ask the human for approval.
    Accepts: yes | no (with optional feedback)
    """
    if state.get("error"):
        return state
    
    if state.get("auto_approve"):
        utils.log("🤖 Auto-approved (scheduler mode)")
        return{**state, "approved": True, "rejection_note": ""}
    
    g = state["generated"]
    caption = g.get("caption", "")

    print("\n" + "=" *65)
    print("🔍  REVIEW BEFORE POSTING")
    print("═" * 65)
    print(f"  📌 Topic     : {state['topic']}")
    print(f"  🎨 Style     : {state.get('style', 'motivational')}")
    print(f"  📏 Length    : {len(caption)} chars")
    print(f"  ⏰ Best time : {g.get('suggested_post_time', 'N/A')}")
    print(f"  💡 Why works : {g.get('why_it_works', '')}")
    if state.get("extra_context"):
        print(f"Extra context: {state['extra_context']}")

    if state.get("image_path"):
        print(f"  🖼️  Image    : {state.get('image_path')}")
    print("\n" + "─" * 65)
    print(caption[:500] + ("..." if len(caption) > 500 else ""))
    print("─" * 65)
    
    while True:
        try:
            choice = input("\n  ✅ Post this? (yes / no): ").strip().lower()
            if choice in ("yes", "y"):
                print("✅ Approved! Moving to post...\n")
                return{**state, "approved": True, "rejection_note": ""}
            elif choice in("no", "n"):
                note = input(" 📝 What to change? (Enter to skip): ").strip()
                print("🔄 Will regenerate with an image...\n")
                return{**state, "approved":False, "rejection_note": note}
            else:
                print("⚠️  Please enter 'yes' or 'no' ")
        except EOFError:
            utils.log("⚠️  No input detected, auto-approving")
            return{**state, "approved": True, "rejection_note": ""}

async def regenerate_with_image(state: PostState) -> PostState:
    """Regenerated the post using the User feedback, then download a matching ai image"""
    count = state.get("rejection_count", 0) + 1
    utils.log(f"\n🔄 Regeneration #{count}..")
    
    note = state.get("rejection_note") or ""
    extra = " ".join(filter(None,[state.get("extra_context", ""), note])).strip()
    try:
        generated = await ai_generator.generate_post(
            topic= state["topic"],
            style= state.get("style")or "motivational",
            extra_context= extra,
        )
        image_prompt = generated.get("image_prompt", state["topic"])
        image_path = await _generate_image(image_prompt)

        return{
            **state,
            "generated": generated,
            "caption": generated["caption"],
            "image_path": image_path or state.get("image_path"),
            "rejection_count": count,
            "error": None,
        }
    except Exception as e:
        utils.log(f"❌ Regeneration failed: {e}")
        return{**state,"error":str(e),"rejection_count": count}
    
async def post_to_linkedin(state: PostState) -> PostState:
    """Log in with Playwright and publish the post."""
    utils.log("\n" + "=" * 55)
    utils.log("🌐 STEP 2 — Opening browser and posting...")
    utils.log("=" * 55)

    if state.get("dry_run"):
        utils.log("🔍 DRY RUN — post generated but NOT published.")
        return{**state, "success": True, "posted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    
    from playwright.async_api import async_playwright
    import Login
    import Post

    async with async_playwright() as pw:
        browser = None
        try:
            browser, context, page = await Login.get_browser_and_page(pw)
            success = await Post.create_post(
                page = page,
                caption = state["caption"],
                image_path= state.get("image_path")
            )
            return{
                **state,
                "success": success,
                "posted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": None if success else "Playwright post returned False", 
            }
        except Exception as e:
            utils.log(f"Browser error: {e}")
            return{**state, "success": False, "error":str(e)}
        finally:
            if browser:
                await browser.close()

async def save_log(state: PostState) -> PostState:
    """Append this run result to session/run_log""" 
    os.makedirs("sessions", exist_ok=True)

    logs: list = []
    if os.path.exists(Config.LOG_FILE):
        try:
            with open(Config.LOG_FILE) as f:
                logs = json.load(f)
        except Exception:
            pass

    g = state.get("generated", {})
    logs.insert(0, {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "topic": state.get("topic", ""),
        "style": state.get("style", ""),
        "success": state.get("success", False),
        "char_count": len(state.get("caption","")),
        "rejections": state.get("rejection_count", 0),
        "posted_at": state.get("posted_at"),
        "error": state.get("error"),
        "hook": g.get("hook", ""),
        "caption_preview": state.get("caption", "")[:150],
    })

    with open(Config.LOG_FILE, "w") as f:
        json.dump(logs[:50], f, indent=2)
    utils.log(f"📝 Logged to {Config.LOG_FILE}")

    print("\n" + "=" *55)
    if state.get("success"):
        print("🎉  POST PUBLISHED SUCCESSFULLY!")
        print(f"    Topic    : {state.get('topic', '')[:60]}")
        print(f"    Style    : {state.get('style', '')}")
        print(f"    Length   : {len(state.get('caption',''))} chars")
        print(f"    Rejections: {state.get('rejection_count', 0)}")
        print(f"    Posted   : {state.get('posted_at')}")
    else:
        print(f"❌  FAILED: {state.get('error')}")
    print("═" * 55 + "\n")
 
    return state

def _route_after_review(state: PostState) -> str:
    """Decide what happens after the human review the post"""
    if state.get("error"):
        return"save_log"
    return "post_to_linkedin" if state["approved"] else "regenerate_with_image"

### Schedule
def load_pending_queue() -> list:
    """Load pending posts from queue file"""
    if not os.path.exists(PENDING_QUEUE_FILE):
        return[]
    try:
        with open(PENDING_QUEUE_FILE) as f:
            return json.load()
    except:
        return[]
    
def save_pending_queue(queue: list) -> None:
    """Save pending posts to queue file."""
    os.makedirs("sessions", exist_ok=True)
    with open(PENDING_QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2, default=str)

def add_to_pending_queue(post_data: dict) -> None:
    """Add a generated post to the pending queue."""
    queue = load_pending_queue()
    queue.append({
        "id": secrets.token_hex(8),
        "added_at": datetime.now().isoformat(),
        "status": "pending",
        **post_data
    })
    save_pending_queue(queue)
    utils.log(f"📋 Added to pending queue: {post_data.get('topic', 'Unknown')}")

def remove_from_queue(post_id: str) -> bool:
    """Remove a post from the pending queue."""
    queue = load_pending_queue()
    original_length = len(queue)
    queue = [p for p in queue if p.get("id") != post_id]
    if len(queue) < original_length:
        save_pending_queue(queue)
        return True
    return False

def update_queue_item(post_id: str, updates: dict) -> bool:
    """Update a post in the pending queue."""
    queue = load_pending_queue()
    for i, post in enumerate(queue):
        if post.get("id") == post_id:
            queue[i].update(updates)
            save_pending_queue(queue)
            return True
    return False
###

def build_graph():
    g = StateGraph(PostState)

    g.add_node("pick_topic", pick_topic )
    g.add_node("generate_post", generate_post )
    g.add_node("human_review", human_review )
    g.add_node("regenerate_with_image", regenerate_with_image)
    g.add_node("post_to_linkedin", post_to_linkedin )
    g.add_node("save_log", save_log )

    g.set_entry_point("pick_topic")

    g.add_edge("pick_topic", "generate_post")
    g.add_edge("generate_post", "human_review")
    g.add_edge("regenerate_with_image", "human_review")

    g.add_edge("post_to_linkedin", "save_log" )
    g.add_edge("save_log", END)

    g.add_conditional_edges(
        "human_review", 
        _route_after_review,
        {
            "post_to_linkedin": "post_to_linkedin",
            "regenerate_with_image": "regenerate_with_image",
            "save_log": "save_log",
        }
    )

    return g.compile()

async def run(
        topic: str =None,
        style: str=None,
        extra_context: str="",
        image_path: str=None,
        auto_approve: bool=False,
) -> PostState:
    utils.ensure_folders()
    app = build_graph()

    initial: PostState ={
         "topic":           topic or "",
        "style":           style or "",
        "extra_context":   extra_context,
        "image_path":      image_path,
        "auto_approve":    auto_approve,
        "generated":       {},
        "caption":         "",
        "rejection_count": 0,
        "rejection_note":  "",
        "approved":        False,
        "success":         False,
        "error":           None,
        "posted_at":       None,
    }
    return await app.ainvoke(initial)


