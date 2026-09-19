import asyncio
import json
import os
import sys

import utils
import workflow
import Scheduler
import ai_generator
import Config

def _show_logs() -> None:
    if not os.path.exists(Config.LOG_FILE):
        print("No logs yet.")
        return
    
    with open(Config.LOG_FILE) as f:
        logs = json.load(f)

    print(f"\n {'='*60}")
    print(f" RUN LOG - Last {min(10, len(logs))} entries")
    print(f"{'='*60}")
    for e in logs[:10]:
        icon = "✅" if e["success"] else "❌"
        dr   = " [DRY RUN]" if e.get("dry_run") else ""
        print(f"\n{icon}{dr}  {e['timestamp']}")
        print(f"   Topic     : {e['topic'][:60]}")
        print(f"   Hook      : {e.get('hook','')[:60]}")
        print(f"   Rejections: {e.get('rejections', 0)}")
        if e.get("error"):
            print(f"   Error     : {e['error']}")
    print()

def Show_styles() -> None:
    print(f"\n{'_'*50}")
    print(" Available styles: ")
    print(f"{'_'*50}")
    for s in ai_generator.list_styles():
        print(f"{s['label']:<28} key:{s['key']}")
    print()

def main() -> None:
    utils.ensure_folders()
    args = sys.argv[1:]

    if "--log" in args:
        _show_logs() 
        return
    
    if "--styles" in args: 
        Show_styles()
        return
    
    if "--schedule" in args:
        idx = args.index("--schedule")
        time = args[idx + 1] if idx + 1 < len(args) and ":" in args[idx + 1] else None

        Scheduler.start(time)
        return
    
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    
    style = None
    if "--style" in args:
        idx = args.index("--style")
        if idx + 1 < len(args):
            style = args[idx + 1]
            args.pop(idx)
            args.pop(idx)

    topic = " ".join(args).strip() or None

    if topic:
        utils.log(f"📌 Topic: {topic}")
    else:
        utils.log("🎲 No topic — will pick randomly")

    asyncio.run(workflow.run(
        topic = topic,
        style = style,
        dry_run= dry_run,
    ))

if __name__ == "__main__":
    main()


        
