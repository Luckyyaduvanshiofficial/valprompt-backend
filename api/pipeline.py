"""
Multi-stage Prompt Optimization Pipeline.

Implements the full intelligence layer:
    User Input → Analyze → Enhance → Classify → Select Strategy
    → Generate (Pass 1) → Improve (Pass 2) → Score → (Auto-Improve) → Return

Each stage uses tuned Gemini temperatures for optimal output quality.
"""

import json
import hashlib
import logging
import re

from django.core.cache import cache

from .gemini_client import call_gemini
from .strategies import PROMPT_STRATEGIES, VALID_TASK_TYPES, build_strategy
from .metaprompt import (
    extract_prompt,
    extract_variables,
    find_free_floating_variables,
    fix_floating_variables,
    improve_prompt,
)

logger = logging.getLogger(__name__)

def safe_json_parse(text: str) -> dict:
    """
    Robustly extract JSON from an LLM response using regex fallback
    to avoid parsing failures from trailing text or markdown fences.
    """
    import re
    import json
    
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: search for the first JSON object block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")

# ---------------------------------------------------------------------------
# Temperature Presets per Pipeline Stage
# ---------------------------------------------------------------------------

TEMPERATURES = {
    "analysis": 0.2,
    "classify": 0.1,
    "generate": 0.3,
    "improve": 0.1,
    "score": 0.0,
}

# Minimum acceptable quality score (out of 10)
MIN_QUALITY_SCORE = 8

# Maximum auto-improvement iterations
MAX_IMPROVE_ITERATIONS = 2


# ---------------------------------------------------------------------------
# Stage 1: Safety & Guardrails
# ---------------------------------------------------------------------------

def analyze_guardrails(task: str) -> bool:
    """
    Examine the user task for potential jailbreaks, prompt injections, 
    or violations of system rules.
    
    Returns True if the task is SAFE, False if it is REJECTED.
    """
    task_lower = task.lower()
    
    # Very basic heuristic blocklist mapping to common jailbreak attempts
    restricted_phrases = [
        "ignore previous instructions",
        "disregard all prior",
        "you are a developer mode",
        "system prompt",
        "forget everything",
        "bypass safety",
        "print your instructions",
    ]
    
    for phrase in restricted_phrases:
        if phrase in task_lower:
            logger.warning("Guardrail triggered: Detected potential prompt injection ('%s')", phrase)
            return False
            
    return True

# ---------------------------------------------------------------------------
# Stage 2: Task Analysis
# ---------------------------------------------------------------------------

def analyze_task(task: str) -> tuple[dict, int]:
    """
    Use LLM to deeply analyze and decompose the raw user task.
    Returns: Tuple of (analysis_dict, token_count)
    """
    analysis_prompt = f"""You are a task analysis expert. Analyze the following task description and extract structured metadata.

<task>
{task}
</task>

You MUST respond with ONLY valid JSON — no markdown, no explanation, no extra text.

Required JSON format:
{{
    "goal": "The primary objective the user wants to achieve",
    "audience": "Who will consume or interact with the output",
    "tone": "The desired communication style (e.g., professional, casual, technical)",
    "format": "Expected output format (e.g., blog post, code, email, report)",
    "constraints": ["List of specific requirements, limitations, or rules"]
}}

If a field cannot be determined from the task, use sensible defaults:
- audience: "general"
- tone: "professional"
- format: "text"
- constraints: []

Respond with ONLY the JSON object."""

    try:
        response, tokens = call_gemini(
            prompt=analysis_prompt,
            temperature=TEMPERATURES["analysis"],
            max_tokens=1024,
        )
        analysis = safe_json_parse(response)

        # Validate required keys
        required_keys = {"goal", "audience", "tone", "format", "constraints"}
        for key in required_keys:
            if key not in analysis:
                analysis[key] = "" if key != "constraints" else []

        # Ensure constraints is a list
        if not isinstance(analysis.get("constraints"), list):
            analysis["constraints"] = [str(analysis["constraints"])]

        return (analysis, tokens)

    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Task analysis LLM returned invalid JSON: %s", exc)
        return ({
            "goal": task,
            "audience": "general",
            "tone": "professional",
            "format": "text",
            "constraints": [],
        }, 0)


# ---------------------------------------------------------------------------
# Stage 2: Task Classification
# ---------------------------------------------------------------------------

def classify_task(task: str, analysis: dict) -> tuple[list[str], int]:
    """
    Classify the task into up to two prompt strategy categories.
    Returns: Tuple of (types_list, token_count)
    """
    classify_prompt = f"""Classify the following task into ONE OR TWO categories.

<task>
{task}
</task>

<task_analysis>
Goal: {analysis.get('goal', '')}
Format: {analysis.get('format', '')}
</task_analysis>

Categories:
- "blog": Content writing, articles, blog posts, copywriting, SEO content, social media posts, marketing copy
- "coding": Programming, software development, code generation, debugging, API design, technical implementation
- "agent": AI agent creation, chatbot design, automation workflows, assistant personas, tool-using agents
- "general": Everything else — analysis, summarization, Q&A, translation, data processing, research

Respond with ONLY a valid JSON array of up to two matching categories like `["blog", "coding"]`. No explanation."""

    try:
        response, tokens = call_gemini(
            prompt=classify_prompt,
            temperature=TEMPERATURES["classify"],
            max_tokens=64,
        )
        types_list = safe_json_parse(response)
        
        if not isinstance(types_list, list):
            types_list = [str(types_list).lower()]
            
        valid_types = [t.lower() for t in types_list if isinstance(t, str) and t.lower() in VALID_TASK_TYPES]
        
        if not valid_types:
            # Fallback fuzzy match
            for vt in VALID_TASK_TYPES:
                if vt in response.lower():
                    valid_types.append(vt)

        if valid_types:
            return (valid_types[:2], tokens)

        logger.info("Classification returned unexpected types '%s', using 'general'", types_list)
        return (["general"], tokens)

    except Exception as exc:
        logger.warning("Task classification failed: %s", exc)
        return (["general"], 0)


# ---------------------------------------------------------------------------
# Stage 3: Task Enhancement
# ---------------------------------------------------------------------------

def enhance_task(analysis: dict, raw_task: str) -> str:
    """
    Build an enriched, structured task description for the metaprompt.

    Combines the raw task with extracted analysis to give the LLM maximum
    context when generating the prompt template.

    Args:
        analysis: Output from analyze_task().
        raw_task: The original user input.

    Returns:
        Enhanced task string.
    """
    constraints_text = ""
    if analysis.get("constraints"):
        constraints_text = "\n".join(f"- {c}" for c in analysis["constraints"])
    else:
        constraints_text = "- None specified"

    enhanced = f"""User Goal:
{analysis.get('goal', raw_task)}

Target Audience:
{analysis.get('audience', 'General')}

Desired Tone:
{analysis.get('tone', 'Professional')}

Expected Format:
{analysis.get('format', 'Text')}

Constraints:
{constraints_text}

Original Task:
{raw_task}"""

    return enhanced


# ---------------------------------------------------------------------------
# Stage 4: Strategy Selection
# ---------------------------------------------------------------------------

def select_strategy(task_types: list[str], analysis: dict) -> str:
    """
    Select and build the appropriate prompt template strategy based on task types.

    Args:
        task_types: List of classified types.
        analysis: Extracted context for dynamic injection.

    Returns:
        The dynamically built strategy template string.
    """
    return build_strategy(task_types, analysis)


# ---------------------------------------------------------------------------
# Stage 5: Prompt Generation (Pass 1)
# ---------------------------------------------------------------------------

def generate_with_strategy(
    enhanced_task: str,
    analysis: dict,
    strategy: str,
    variables: list[str] | None = None,
) -> dict:
    """
    Generate a prompt template using the selected strategy.
    """
    # Build the analysis text for injection
    analysis_text = json.dumps(analysis, indent=2)

    # Insert task and analysis into the strategy template
    prompt = strategy.replace("{{TASK}}", enhanced_task)
    prompt = prompt.replace("{{ANALYSIS}}", analysis_text)

    # If variables are provided, add a hint
    if variables:
        variable_string = "\n".join(f"{{${v.upper()}}}" for v in variables)
        prompt += f"\n\nThe variables to use are:\n{variable_string}"

    # Call Gemini with generation temperature
    raw_response, raw_tokens = call_gemini(
        prompt=prompt,
        temperature=TEMPERATURES["generate"],
        max_tokens=8192,
    )

    # Extract the prompt template
    extracted = extract_prompt(raw_response)
    
    # Empty Output Guard
    if not extracted or len(extracted.strip()) < 20:
        raise RuntimeError("Generated prompt is invalid or empty.")

    # Extract variables
    found_variables = extract_variables(extracted)

    # Fix floating variables
    floating_vars = find_free_floating_variables(extracted)
    if floating_vars:
        fixed_extracted, fix_tokens = fix_floating_variables(extracted)
        raw_tokens += fix_tokens
        
        # Validation for corrupted variables
        fixed_vars = extract_variables(fixed_extracted)
        if not fixed_vars and found_variables:
            logger.warning("[Pipeline] Variable fix corrupted prompt; reverting.")
        else:
            extracted = fixed_extracted
            found_variables = fixed_vars

    return {
        "prompt": extracted,
        "variables": found_variables,
        "raw_response": raw_response,
        "tokens": raw_tokens,
    }


# ---------------------------------------------------------------------------
# Stage 6: Prompt Scoring
# ---------------------------------------------------------------------------

def score_prompt(prompt: str) -> tuple[dict, int]:
    """
    Evaluate the quality of a generated prompt on a 1–10 scale.
    Returns: Tuple of (scoring_dict, token_count)
    """
    scoring_prompt = f"""You are a prompt quality evaluator. Rate the following prompt template on a scale of 1 to 10.

<prompt_to_evaluate>
{prompt}
</prompt_to_evaluate>

Evaluate using these criteria (each scored 1-10):
1. **Clarity**: Are instructions unambiguous and easy to follow?
2. **Completeness**: Does it cover all necessary aspects of the task?
3. **Structure**: Is it well-organized with proper formatting (XML tags, sections)?
4. **Specificity**: Does it provide concrete guidance rather than vague directions?
5. **Robustness**: Does it handle edge cases and provide examples?

You MUST respond with ONLY valid JSON — no markdown, no explanation, no extra text.

Required JSON format:
{{
    "score": <overall score 1-10 as a number>,
    "criteria": {{
        "clarity": <1-10>,
        "completeness": <1-10>,
        "structure": <1-10>,
        "specificity": <1-10>,
        "robustness": <1-10>
    }},
    "feedback": "Specific suggestions for improvement, or 'Excellent' if score >= 9"
}}

Respond with ONLY the JSON object."""

    try:
        response, tokens = call_gemini(
            prompt=scoring_prompt,
            temperature=TEMPERATURES["score"],
            max_tokens=512,
        )
        result = safe_json_parse(response)

        # Validate score is numeric
        score = float(result.get("score", 5))
        score = max(1.0, min(10.0, score))
        result["score"] = score

        # Ensure feedback exists
        if "feedback" not in result:
            result["feedback"] = ""

        # --- Hybrid Scoring (Heuristics) ---
        # Apply deterministic rules on top of LLM vibes
        if "<Instructions>" not in prompt and "Instructions:" not in prompt:
            score -= 1.5
            result["feedback"] += " Missing explicit <Instructions> structure."
            
        word_count = len(prompt.split())
        if word_count > 1500:
            score -= 1.0
            result["feedback"] += " Prompt is excessively long; needs compression."
            
        if word_count < 20:
            score -= 2.0
            result["feedback"] += " Prompt is way too short to be robust."

        score = max(1.0, min(10.0, score))
        result["score"] = score

        # Ensure criteria exists
        if "criteria" not in result or not isinstance(result["criteria"], dict):
            result["criteria"] = {}

        return (result, tokens)

    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Prompt scoring returned invalid JSON: %s", exc)
        return ({
            "score": 5.0,
            "feedback": "Scoring failed — could not parse LLM response.",
            "criteria": {},
        }, 0)


# ---------------------------------------------------------------------------
# Stage 7: Prompt Compression
# ---------------------------------------------------------------------------

def compress_prompt(prompt: str) -> tuple[str, int]:
    """
    Compresses an overly long prompt to save tokens.
    Returns: Tuple of (compressed_prompt, token_count).
    """
    compression_prompt = f"""You are an expert editor. Make this prompt shorter and more concise without losing ANY of its structural meaning, constraints, variables, or instructions. Remove fluff, conversational filler, and redundant examples. Keep all XML tags intact.

<PromptToCompress>
{prompt}
</PromptToCompress>

Return ONLY the compressed prompt."""

    logger.info("[Pipeline] Running prompt compression pass...")
    try:
        response, tokens = call_gemini(
            prompt=compression_prompt,
            temperature=TEMPERATURES["improve"],
            max_tokens=8192,
        )
        compressed = extract_prompt(response)
        
        # Safety check: if compression completely broke it, return original
        if len(compressed) < 50 or "<Instructions>" not in compressed:
            logger.warning("[Pipeline] Compression destroyed prompt structure; reverting.")
            return (prompt, tokens)
            
        return (compressed, tokens)
        
    except Exception as exc:
        logger.warning(f"Compression failed: {exc}")
        return (prompt, 0)


# ---------------------------------------------------------------------------
# Full Pipeline Orchestrator
# ---------------------------------------------------------------------------

def _run_pipeline_inner(
    task: str,
    variables: list[str] | None = None,
    skip_cache: bool = False,
) -> dict:
    """
    Execute the full multi-stage prompt optimization pipeline.

    Flow:
        1. Check cache (if enabled)
        2. Analyze task (extract goal, audience, tone, format, constraints)
        3. Classify task (blog / coding / agent / general)
        4. Enhance task (build enriched description)
        5. Select strategy (pick the right prompt template)
        6. Generate prompt (Pass 1 — draft)
        7. Improve prompt (Pass 2 — refinement)
        8. Score prompt
        9. Auto-improve if score < threshold
       10. Return final result

    Args:
        task: Raw task description from the user.
        variables: Optional list of variable names.
        skip_cache: If True, bypass caching.

    Returns:
        Dict with keys:
            - task: original task
            - task_type: classified type
            - analysis: structured analysis
            - draft_prompt: first-pass output
            - improved_prompt: refined output
            - final_prompt: the best version
            - variables: detected variables
            - score: quality score (1-10)
            - score_details: full scoring breakdown
            - version: number of improvement passes applied
    """
    total_tokens = 0

    # --- Stage 0: Guardrails ---
    logger.info("[Pipeline] Stage 0: Checking safety guardrails...")
    if not analyze_guardrails(task):
        raise RuntimeError("Task rejected: Potential prompt injection or safety violation detected.")

    # --- Stage 1: Analyze ---
    logger.info("[Pipeline] Stage 1: Analyzing task...")
    analysis, t_anal = analyze_task(task)
    total_tokens += t_anal

    # --- Stage 2: Classify ---
    logger.info("[Pipeline] Stage 2: Classifying task...")
    task_types, t_class = classify_task(task, analysis)
    total_tokens += t_class
    primary_task_type = task_types[0] if task_types else "general"

    # --- Stage 2.5: User Feedback Loop ---
    # Fetch negative feedback from previous generations to learn from mistakes
    from .models import PromptHistory
    prior_mistakes = PromptHistory.objects.filter(
        task_type__icontains=primary_task_type,
        user_rating__lte=3
    ).exclude(user_feedback="").order_by("-created_at")[:3]
    
    if prior_mistakes.exists():
        avoidances = [pm.user_feedback for pm in prior_mistakes]
        analysis["constraints"].extend([
            f"CRITICAL: Based on past failures, AVOID doing this: {fb}" for fb in avoidances
        ])
        logger.info("[Pipeline] Stage 2.5: Injected %d prior feedback items as avoidance constraints.", len(avoidances))

    # --- Stage 3: Enhance ---
    logger.info("[Pipeline] Stage 3: Enhancing task...")
    enhanced_task = enhance_task(analysis, task)

    # --- Stage 4: Select Strategy ---
    logger.info("[Pipeline] Stage 4: Selecting strategy for '%s'...", task_types)
    strategy = select_strategy(task_types, analysis)

    # --- Cache Check (Moved here to include strategy and feedback constraints) ---
    feedback_salt = hashlib.md5(str(analysis.get("constraints", [])).encode()).hexdigest()[:8]
    cache_key = _make_cache_key(task, variables, getattr(strategy, "version", strategy) + feedback_salt)
    if not skip_cache:
        cached = cache.get(cache_key)
        if cached:
            logger.info("Pipeline cache hit after strategy bounds for task: %s", task[:50])
            # Return cached response but append the tokens we just burned to find it
            cached["tokens"] = cached.get("tokens", 0) + total_tokens
            return cached

    # --- Stage 5: Generate (Pass 1 — Draft) ---
    logger.info("[Pipeline] Stage 5: Generating draft prompt...")
    draft_result = generate_with_strategy(
        enhanced_task=enhanced_task,
        analysis=analysis,
        strategy=strategy,
        variables=variables,
    )
    draft_prompt = draft_result["prompt"]
    raw_response = draft_result["raw_response"]
    total_tokens += draft_result.get("tokens", 0)

    # --- Stage 6: Improve (Pass 2) ---
    logger.info("[Pipeline] Stage 6: Improving prompt...")
    improved_result = improve_prompt(
        prompt=draft_prompt,
        feedback="Make this production-ready: ensure all edge cases are handled, "
                 "output format is explicitly defined, and instructions are crystal clear.",
    )
    improved_prompt = improved_result["prompt"]
    current_best = improved_prompt
    current_variables = improved_result["variables"]
    total_tokens += improved_result.get("tokens", 0)
    version = 2  # We've done 2 passes

    # --- Stage 7: Score ---
    logger.info("[Pipeline] Stage 7: Scoring prompt...")
    score_result, t_score = score_prompt(current_best)
    total_tokens += t_score
    current_score = score_result["score"]

    # --- Stage 8: Auto-Improve Loop ---
    iterations = 0
    while current_score < MIN_QUALITY_SCORE and iterations < MAX_IMPROVE_ITERATIONS:
        iterations += 1
        version += 1
        
        # KEY INFRASTRUCTURE UPGRADE: Feedback is passed directly back to improve_prompt
        feedback = score_result.get("feedback", "Improve quality and completeness.")
        logger.info(
            "[Pipeline] Stage 8: Auto-improving (iteration %d, score=%.1f) with specific feedback...",
            iterations, current_score,
        )

        re_improved = improve_prompt(prompt=current_best, feedback=feedback)
        current_best = re_improved["prompt"]
        current_variables = re_improved["variables"]
        total_tokens += re_improved.get("tokens", 0)

        score_result, t_score2 = score_prompt(current_best)
        total_tokens += t_score2
        current_score = score_result["score"]

    # --- Stage 9: Compression Layer ---
    word_count = len(current_best.split())
    if word_count > 1200:
        logger.info("[Pipeline] Stage 9: Compressing over-length prompt (%d words)...", word_count)
        current_best, t_comp = compress_prompt(current_best)
        total_tokens += t_comp

    # --- Build Response ---
    result = {
        "task": task,
        "task_type": task_types, # Keep as list for JSON models/serializers
        "analysis": analysis,
        "draft_prompt": draft_prompt,
        "improved_prompt": improved_prompt,
        "final_prompt": current_best,
        "variables": current_variables,
        "score": current_score,
        "score_details": score_result,
        "version": version,
        "raw_response": raw_response,
        "tokens": total_tokens,
    }

    # --- Cache Result (1 hour TTL) ---
    try:
        cache.set(cache_key, result, timeout=3600)
    except Exception:
        logger.debug("Cache write failed — likely no cache backend configured.")

    logger.info(
        "[Pipeline] Complete! Type=%s, Score=%.1f, Version=%d",
        task_types, current_score, version,
    )

    return result


def run_pipeline(
    task: str,
    variables: list[str] | None = None,
    skip_cache: bool = False,
) -> dict:
    """Wrapper that catches hard crashes and returns a graceful fallback."""
    try:
        return _run_pipeline_inner(task, variables, skip_cache)
    except Exception as exc:
        logger.exception("Pipeline crashed hard, returning safe fallback response")
        return {
            "task": task,
            "task_type": ["general"],
            "analysis": {"goal": task, "audience": "general", "tone": "professional", "format": "text", "constraints": []},
            "draft_prompt": task,
            "improved_prompt": task,
            "final_prompt": f"Please help me with this task:\n\n{task}\n\nMake sure to provide clear instructions.",
            "variables": variables or [],
            "score": 5.0,
            "score_details": {"score": 5.0, "feedback": "Pipeline fallback triggered due to internal error."},
            "version": 0,
            "raw_response": "",
            "tokens": 0,
        }
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache_key(task: str, variables: list[str] | None = None, strategy: str = "") -> str:
    """Create a deterministic cache key from the input parameters, model, and pipeline version."""
    from django.conf import settings
    raw = task.strip().lower()
    if variables:
        raw += "|" + ",".join(sorted(v.lower() for v in variables))
    raw += f"|{hashlib.sha256(strategy.encode()).hexdigest()[:10]}"
    raw += f"|{settings.GEMINI_MODEL}|pipeline_v2"
    return f"pipeline:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"



