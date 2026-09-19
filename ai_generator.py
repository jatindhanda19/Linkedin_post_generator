import asyncio
import base64
import json
import os
import re
from datetime import datetime


import utils
import Config
from dotenv import load_dotenv

load_dotenv() 

# Gemini client 
try:
    import google.genai as genai
    _GENAI_PACKAGE = "google.genai"
    genai_client = genai.Client(api_key=Config.GEMINI_API_KEY) if Config.GEMINI_API_KEY else None
except ImportError:
    import google.generativeai as genai
    _GENAI_PACKAGE = "google.generativeai"
    if Config.GEMINI_API_KEY:
        genai.configure(api_key=Config.GEMINI_API_KEY)
    genai_client = None


STYLES = {
    "motivational":       {"label": "Motivational",       "tone": "energizing, powerful action words, short punchy sentences"},
    "educational":        {"label": "Educational",         "tone": "informative, simple language, concrete examples"},
    "storytelling":       {"label": "Storytelling",        "tone": "narrative style, hook opening, build tension, end with lesson"},
    "thought_leadership": {"label": "Thought Leadership",  "tone": "confident, challenge conventional thinking, back claims with reasoning"},
    "casual":             {"label": "Casual & Friendly",   "tone": "conversational, everyday language, genuine and human"},
    "achievement":        {"label": "Achievement",         "tone": "celebratory, acknowledge team/journey, inspire others"},
}


# Gemini call


def _call_gemini(prompt: str, max_tokens: int = 2000, force_json= True) -> str:
    if not Config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing -- add it to your .env file.")
    try:
        if _GENAI_PACKAGE == "google.genai":
            config = genai.types.GenerateContentConfig(
                max_output_tokens= max_tokens,
                response_mime_type="application/json" if force_json else "text/plain",
                temperature= 0.7,
            )
            response = genai_client.models.generate_content(
                model = "gemini-2.5-flash",
                contents=prompt,
                config=config,
            )
            return(response.text or "").strip()
        else:
            # Old SDK
            generation_config = genai.GenerationConfig(
                max_output_tokens=max_tokens,
                response_mime_type="application/json" if force_json else "text/plain",
                temperature=0.7,
            )

            model = genai.GenerativeModel("gemini-2.5-flash")

            response = model.generate_content(
                prompt,
                generation_config=generation_config,
            )

            return (response.text or "").strip()
        
    except Exception as exc:
        raise RuntimeError(f"Gemini API error: {exc}") from exc


# Gemini image generation
async def generate_image(prompt: str, save_dir: str) -> str | None:
    """
    Generate an image with Gemini and save it.
    Uses v1alpha API (required for image generation models).
    Returns file path on success, None on failure.
    """
    if not Config.GEMINI_API_KEY:
        utils.log("Image skipped -- no API key")
        return None
 
    # Models to try in order
    MODELS = [
        "gemini-2.0-flash-preview-image-generation",
        "gemini-2.0-flash-exp",
    ]
 
    for model_name in MODELS:
        try:
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"post_{datetime.now().strftime('%H%M%S')}.png")
 
            # v1alpha is required for image generation -- create a dedicated client
            if _GENAI_PACKAGE == "google.genai":
                img_client = genai.Client(
                    api_key=Config.GEMINI_API_KEY,
                    http_options={"api_version": "v1alpha"},
                )
                response = img_client.models.generate_content(
                    model=model_name,
                    contents=f"Create a professional photorealistic image for a LinkedIn post about: {prompt[:200]}",
                    config=genai.types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                    ),
                )
            else:
                # Old SDK path
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    f"Create a professional photorealistic image for a LinkedIn post about: {prompt[:200]}",
                    generation_config={"response_modalities": ["IMAGE"]},
                )
 
            # Extract image bytes from response
            candidates = getattr(response, "candidates", [])
            if not candidates:
                utils.log(f"{model_name}: no candidates in response")
                continue
 
            for part in candidates[0].content.parts:
                if getattr(part, "inline_data", None):
                    with open(path, "wb") as f:
                        f.write(base64.b64decode(part.inline_data.data))
                    utils.log(f"Image saved: {path}  (model: {model_name})")
                    return path
 
            utils.log(f"{model_name}: response had no image data")
 
        except Exception as e:
            utils.log(f"{model_name} failed: {e}")
            continue
 
    utils.log("All image models failed -- continuing without image")
    return None

# JSON parsing — handles bare newlines inside string values

def _normalize_json(raw: str) -> str:
    """Escape bare newlines/tabs that Gemini puts inside JSON string values."""
    result    = []
    in_string = False
    i         = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and in_string:
            # Already-escaped — pass both chars through unchanged
            result.append(ch)
            if i + 1 < len(raw):
                result.append(raw[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == "\n":
            result.append("\\n")
        elif in_string and ch == "\r":
            result.append("\\r")
        elif in_string and ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def _repair_json(raw: str) -> str:
    """Close unclosed braces/quotes from truncated model output."""
    diff = raw.count("{") - raw.count("}")
    if diff > 0:
        raw += "}" * diff
    if raw.count('"') % 2 != 0:
        raw += '"'
    return raw


def _load_json(raw: str) -> dict | None:
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    if not cleaned or "{" not in cleaned:
        return None
    cleaned = cleaned[cleaned.index("{"):]
    cleaned = _normalize_json(cleaned)
    cleaned = _repair_json(cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _extract_field(raw: str, field: str):
    """Pull one field out of broken JSON as a last resort."""
    if field == "hashtags":
        m = re.search(r'"hashtags"\s*:\s*(\[.*?\])', raw, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return re.findall(r'"(#[^"]+)"', m.group(1)) or None
        return None

    # String field
    m = re.search(
        r'"' + re.escape(field) + r'"\s*:\s*"((?:[^"\\]|\\.)*)"',
        raw, flags=re.DOTALL,
    )
    if m:
        try:
            return json.loads('"' + m.group(1) + '"')
        except json.JSONDecodeError:
            return m.group(1)

    m2 = re.search(
        r'"' + re.escape(field) + r'"\s*:\s*"([^"]*)',
        raw, flags=re.DOTALL,
    )
    return m2.group(1).strip() if m2 else None

def _parse_json(raw: str, fallback: dict) -> dict:
    parsed = _load_json(raw)
    if parsed and isinstance(parsed, dict):
        return parsed

    utils.log("Full JSON parse failed -- attempting field-by-field recovery")
    recovered = {k: _extract_field(raw, k) for k in fallback}
    if any(v is not None for v in recovered.values()):
        return {**fallback, **{k: v for k, v in recovered.items() if v is not None}}

    utils.log("Field recovery also failed -- using fallback values")
    return fallback



# Public API

async def generate_post(
    topic:         str,
    style:         str = "motivational",
    extra_context: str = "",
) -> dict:
    """Generate a LinkedIn post and return a structured dict."""
    style_info = STYLES.get(style, STYLES["motivational"])
    utils.log(f"Generating {style_info['label']} post about: {topic}")

    extra_line = f"\nExtra context: {extra_context}" if extra_context else ""

    prompt = f"""You are an expert LinkedIn content creator and viral storytelling writer. Your job is to create highly engaging, authentic, 
    and human-sounding LinkedIn posts that feel written by a real professional — not AI. 

Topic: {topic}
Tone: {style_info['tone']}{extra_line}

STRICT WRITING RULES:
- Write like a real person sharing a genuine experience or insight
- Avoid robotic, overly polished, corporate, or generic AI-sounding language
- Use simple, natural English
- Add emotion, curiosity, or personal reflection where appropriate
- Vary sentence length naturally
- Do not overuse buzzwords, motivational clichés, or exaggerated claims
- Avoid repetitive sentence structures
- Make transitions feel conversational and smooth
- The post should feel relatable and believable
- Every sentence must add value

CONTENT REQUIREMENTS:

- Total length: 150–300 words
- Start with a strong scroll-stopping hook
- Use short readable paragraphs
- Include 3–5 emojis naturally (not spammy)
- Include one personal insight, lesson, or observation
- End with a thoughtful question that encourages comments
- Add 5–8 relevant hashtags at the end
- Write in first-person voice
- Keep engagement high while maintaining authenticity

IMAGE PROMPT REQUIREMENTS:
-Create a cinematic, photorealistic image prompt
-Image must visually match the topic and emotional tone
-Include lighting, environment, mood, camera style, and realistic details.

OUTPUT RULES:
-Return ONLY valid JSON
-Do not include markdown formatting
-Do not include explanations before or after the JSON
-Ensure all JSON is properly escaped
-Caption must include the complete post including hook and hashtags

{{
  "hook": "the first line of the post only",
  "caption": "the full post text from hook to hashtags",
  "hashtags": ["#Tag1", "#Tag2", "#Tag3", "#Tag4", "#Tag5"],
  "image_prompt": "a photorealistic image prompt that matches the post theme",
  "suggested_post_time": "best day and time, e.g. Tuesday 9 AM",
  "why_it_works": "one sentence explaining why this post will perform well"
}}"""

    raw = _call_gemini(prompt, max_tokens=2000)

    # Debug: show what Gemini actually returned
    utils.log(f"Gemini raw response ({len(raw)} chars):")
    utils.log(raw[:300] + ("..." if len(raw) > 300 else ""))

    data = _parse_json(raw, fallback={
        "hook":                "",
        "caption":             raw,
        "hashtags":            ["#LinkedIn", "#Growth", "#Learning"],
        "image_prompt":        f"Professional post about {topic}, modern style",
        "suggested_post_time": "Tuesday 9 AM",
        "why_it_works":        "Authentic voice with a clear hook drives engagement.",
    })

    # Sanitise hashtags
    if not isinstance(data.get("hashtags"), list):
        data["hashtags"] = ["#LinkedIn", "#Growth", "#Learning"]

    # Ensure image_prompt is always available
    if not isinstance(data.get("image_prompt"), str) or not data["image_prompt"].strip():
        data["image_prompt"] = f"Professional post about {topic}, modern style"

    # Guard: caption is a JSON blob (parsing went wrong)
    caption = data.get("caption", "")
    if isinstance(caption, str) and caption.strip().startswith("{"):
        extracted = _extract_field(caption, "caption")
        if extracted:
            data["caption"] = extracted

    # Guard: caption suspiciously short -- use full raw response
    if isinstance(data.get("caption"), str) and len(data["caption"]) < 50:
        utils.log(f"Caption too short ({len(data['caption'])} chars) -- using raw output")
        data["caption"] = raw

    # Convert escaped \n sequences to real newlines for display and posting
    if isinstance(data.get("caption"), str):
        data["caption"] = data["caption"].replace("\\n", "\n")
    if isinstance(data.get("hook"), str):
        data["hook"] = data["hook"].replace("\\n", "\n").strip()

    data.update({
        "char_count": len(data.get("caption", "")),
        "style":      style,
        "topic":      topic,
    })

    utils.log(f"Post ready -- {data['char_count']} chars")
    utils.log(f"Hook     : {str(data.get('hook', ''))[:70]}")
    utils.log(f"Hashtags : {data.get('hashtags', [])}")
    utils.log(f"Time     : {data.get('suggested_post_time', '')}")
    utils.log(f"Why      : {data.get('why_it_works', '')}")
    return data


async def regenerate_section(original_post: str, section: str, instruction: str) -> str:
    """Rewrite one section of an existing post without touching the rest."""
    utils.log(f"Regenerating section: {section}")
    prompt = (
        f"Here is a LinkedIn post:\n\n{original_post}\n\n"
        f"Rewrite only the '{section}' section.\n"
        f"Instruction: {instruction}\n\n"
        f"Return only the new {section} text. Nothing else."
    )
    result = _call_gemini(prompt, max_tokens=2000)
    utils.log(f"{section.capitalize()} regenerated.")
    return result


def list_styles() -> list[dict]:
    """Return all styles as a list for UI display."""
    return [{"key": k, **v} for k, v in STYLES.items()]
