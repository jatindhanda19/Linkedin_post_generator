import asyncio
from playwright.async_api import Playwright, BrowserContext

import Config
import utils

async def _launch_browser(playwright: Playwright, storage_state: str = None):
    """Launch chrominum and return(browser, context, page)"""

    browser = await playwright.chromium.launch(
        headless=Config.HEADLESS,
        slow_mo =Config.SLOW_MO,
        args =["--Start-maximized"],
    )

    ctx_options = {'viewport': {"width": 1280, "height":800}}
    if storage_state:
        ctx_options["storage_state"] = storage_state

    context = await browser.new_context(**ctx_options)
    page = await context.new_page()
    return browser, context, page

async def save_session(context: BrowserContext) -> None:
    await context.storage_state(path=Config.SESSION_FILE)
    utils.log("💾 Session Saved")

async def _try_selector(page, selectors: list[str], action, timeout: int = 5000):
    """Try each selector in order, raise Runtime error if none work """

    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=timeout)
            await action(sel)
            return sel
        except Exception:
            continue
    raise RuntimeError(f"None of the selector matched: {selectors}")
    
async def do_login(playwright: Playwright) -> tuple:
    """Fresh login flow- fills email/password, waits for feed."""
    utils.log("🚀 Starting fresh login...")
    browser, context, page = await _launch_browser(playwright)
    await page.goto(Config.LINKEDIN_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    await utils.random_sleep(2,3)

    # Email
    utils.log("📧 Entering email...")
    await _try_selector(
        page,
        ["#username", "input[name='session_key']", "input[autocomplete='username']"],
        lambda sel: utils.human_type(page, sel, Config.LINKEDIN_EMAIL),
    )
    await utils.random_sleep(0.5, 1.5)

    # Password
    utils.log("🔒 Entering password...")
    await _try_selector(
        page,
        ["#password", "input[name='session_password']","input[autocomplete='current-password']"],
        lambda sel: utils.human_type(page, sel, Config.LINKEDIN_PASSWORD),
        )
    await utils.random_sleep(0.5, 1.5)

    # Submit
    utils.log(" 🔑 Submitting...")
    await _try_selector(
        page, 
        ["button[type='submit']", "button:has-text('sign in')"],
        lambda sel: page.click(sel),
        )
    
    try:
        await page.wait_for_url("**/feed/**", timeout=20000)
        utils.log("✅ Login successful!")
    except Exception:
        utils.log("⚠️  Verification required — you have 30 seconds...")

        await asyncio.sleep(30)
        if "login" in page.url:
            raise RuntimeError("Login time out - still on login page")
        
    await save_session(context)
    return browser, context, page

async def get_browser_and_page(playwright : Playwright) -> tuple:
    """
    Smart entry point: Load saved session if valid, otherwise log fresh.
    Returns (browser, context, page) ready to use on the LinkedIN feed.
    """

    if utils.session_exists():
        utils.log("🔍 Found saved session — loading...")
        browser, context, page = await _launch_browser(playwright, Config.SESSION_FILE)
        try:
            await page.goto(Config.LINKEDIN_FEED_URL, wait_until="domcontentloaded", timeout=15000)
            await utils.random_sleep(0.5, 1.5)
            if "login" not in page.url:
                utils.log("✅ Session valid — ready to post!")
                return browser, context, page
            utils.log("Session Expired - logging again...")
        except Exception as e:
            utils.log(f"✅ Session valid — ready to post!")
        await browser.close()

    return await do_login(playwright)  






