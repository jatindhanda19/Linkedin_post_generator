import os
from playwright.async_api import Page, async_playwright

import Config
import utils

async def _click_first_match(page:Page, selectors: list[str], label:str, timeout: int =5000) -> bool:
    """Try selectors in oreder , Click the first that works. Return True on success"""
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=timeout)
            el = await page.query_selector(sel)
            if el:
                await el.scroll_into_view_if_needed()
                await utils.random_sleep(0.3, 0.7)
                await page.click(sel)
                utils.log(f"✅ Clicked {label}")
                return True
        except Exception:
            continue

        utils.log(f"⚠️  Trying JS fallback for {label}...")
        found = await page.evaluate(f"""() => {{
                                    const els = document.querySelectorAll('button, div[role="button"], input');
                                    for (const el of els) {{
                                    const txt = (el.textContent || el.placeholder || '').toLowerCase();
                                    if(txt.includes('{label.lower()}')){{
                                    el.scrollIntoView({{block: 'centre'}});
                                    el.click();
                                    return true;
                                    }}
                                    }}
                                    return false;
        }}""" )
        if found:
            utils.log(f"✅ Clicked {label} via JS")
        return found
        
#####
async def click_start_post(page: Page) -> None:
    await page.wait_for_load_state("domcontentloaded", timeout=10000)
    await utils.random_sleep(1, 2)
    
    ok = await _click_first_match(page,[
        'button[aria-label="Start a post"]',
        'button[data-control-name="share.sharebox_open"]',
        '[role="button"][aria-label*="Start a post"]',
        '.share-box-feed-entry_trigger',
        'div[role="button"]:has-text("Start a post")',
        'input[placeholder*="Start a post"]',
        'button.artdeco-button--muted:has-text("Start a post")',
    ], "Start a post")
    if not ok:
        raise RuntimeError("Could not find 'Start a post' button..")
    await utils.random_sleep(2, 3)
    
   
async def upload_image(page: Page, image_path: str) -> None:
    if not image_path or not os.path.exists(image_path):
        utils.log("⚠️  No image provided or file not found — skipping upload")
        return
    
    utils.log(f"🖼️  Uploading image: {image_path}")

    await _click_first_match(page,[
        'button[aria-label*="Add a photo"]',
        'button[aria-label*="photo"]',
        'button[aria-label*="media"]',
        '.share-creation-state_additional-toolbar button:first-child',
        'button.share-image-action',
    ],"media button", timeout= 4000)

    try:
        async with page.expect_file_chooser(timeout=5000) as fc_info:
            await page.locator('input[type="file"]')
        fc = await fc_info.value
        await fc.set_files(image_path)
    except Exception:
        await page.set_input_files('input[type="file"]', image_path)

    await utils.random_sleep(2, 4)
    utils.log("✅ Image uploaded")    
    
async def type_caption(page: Page, caption: str):
    utils.log("🖊️  Typing caption...")
    await utils.random_sleep(1, 2)

    editor_selectors = [
        'div[data-root-id="artdeco-modal__header"] ~ div div[contenteditable="true"]',
        '.share-creation-state_editor div[contenteditable="true"]',
        'div[role="textbox"][contenteditable="true"]',
        '.ql-editor',
        '[contenteditable="true"]',
        'div.public_DraftEditor_content',
        'div[class*="editor"]',
    ]

    for sel in editor_selectors:
        try:
            await page.wait_for_selector(sel, timeout=7000)
            await page.click(sel)
            await utils.random_sleep(0.5, 1)
            await page.keyboard.type(caption, delay=Config.TYPE_DELAY_MIN)
            utils.log("✅ Caption typed")
            await utils.random_sleep(1, 2)
            return
        except Exception:
            continue
    await page.evaluate("""() => {
                        const eds = document.querySelectorAll('[contenteditable="true"]');
                        if (eds.length) eds[eds.length -1].focus();
                        }""")
    await utils.random_sleep(0.5, 1)
    await page.keyboard.type(caption, delay=Config.TYPE_DELAY_MIN)
    utils.log("✅ Caption typed via fallback")
    await utils.random_sleep(1, 2)
        

async def click_post_button(page):
    ok = await _click_first_match(page,[
        'button[aria-label="Post"]',
        'button:has-text("Post")',
        'button.share-actions_primary-action',
        '.share-box_actions button.artdeco-button--primary',
        'button[data-control-name="share.comment_comptroller.post"]',
        'button.artdeco-button--primary:has-text("Post")',
    ],"Post")
    if not ok:
        utils.log("⚠️  Could not find Post button")
    await utils.random_sleep(2, 4)
    utils.log("🎉 Post should be published now!")

async def create_post(page: Page, caption: str, image_path: str = None) -> bool:
    """
    Full end to end LinkedIN post flow:
    navigate -> Start post ->(optional image) -> type caption -> submit.
    Returns true or success
    """
    utils.log("=" * 45)
    utils.log("📝 Starting LinkedIn post creation...")
    utils.log("=" * 45)

    try:
        await page.goto(Config.LINKEDIN_FEED_URL, wait_until="domcontentloaded", timeout=15000)
        await utils.random_sleep(2, 4)

        await click_start_post(page)

        if image_path:
            await upload_image(page, image_path)

        await type_caption(page, caption)

        await click_post_button(page)

        utils.log("✅ LinkedIn post created successfully!")
        return True
    
    except Exception as e:
        utils.log(f"❌ Error during post creation: {e}")
        await page.screenshot(path="post_error.png")
        return False
    
