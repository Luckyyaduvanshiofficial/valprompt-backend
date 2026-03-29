"""
Task-specific prompt generation strategies.

Replaces the single monolithic METAPROMPT with focused, token-efficient
templates for different prompt categories (blog, coding, agent, general).
"""

# ---------------------------------------------------------------------------
# Few-Shot Examples (Highest Impact on Quality)
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES = """
Here is an example of a high-quality response:

<Example>
<UserTask>
Parse apache logs and extract error IPs.
</UserTask>
<Output>
<Inputs>
{$LOG_DATA}
</Inputs>
<Instructions Structure>
1. Define goal: Parse Apache logs for errors.
2. Outline steps: Iterate lines, regex match 'ERROR', extract IP.
3. Constraint: Return unique JSON IPs.
</Instructions Structure>
<Instructions>
You are an expert Python developer tasked with log analysis.

Look at the provided log file content:
<LogData>
{$LOG_DATA}
</LogData>

Please write a Python script that accomplishes the following:
1. Read the log data line by line.
2. Identify lines containing the word "ERROR".
3. Use a regular expression to extract the IP address from those error lines.
4. Deduplicate the IP addresses.

Your final output must be ONLY a valid JSON array of strings representing the unique IP addresses found. Do not include any explanations.
</Instructions>
</Output>
</Example>
"""

# ---------------------------------------------------------------------------
# Blog / Content Writing Strategy
# ---------------------------------------------------------------------------

BLOG_PROMPT = '''You are an expert prompt engineer specializing in content creation and writing tasks. Your goal is to write clear, specific instructions for an AI assistant to produce high-quality written content.

<Task>
{{TASK}}
</Task>

<TaskAnalysis>
{{ANALYSIS}}
</TaskAnalysis>

Write instructions that will guide an AI assistant to produce excellent written content. Your instructions must:

1. Define the exact writing style, tone, and voice
2. Specify the target audience and reading level
3. Include structural requirements (headings, sections, word count)
4. Add SEO or formatting constraints if mentioned
5. Include quality criteria (originality, engagement, accuracy)
6. Provide examples of good vs. poor output where helpful

Requirements for your output:
- Use XML tags to organize input variables and sections
- Place variables that expect long content BEFORE instructions on what to do
- Use {$VARIABLE_NAME} syntax for all variable placeholders
- Keep variables to the minimal, non-overlapping set needed

Output your response in this format:
<Inputs>
List each variable on its own line: {$VARIABLE_NAME}
</Inputs>
<Instructions Structure>
Brief plan of how you'll structure the instructions
</Instructions Structure>
<Instructions>
The complete prompt template
</Instructions>'''


# ---------------------------------------------------------------------------
# Coding / Development Strategy
# ---------------------------------------------------------------------------

DEV_PROMPT = '''You are an expert prompt engineer specializing in software development and coding tasks. Your goal is to write precise, unambiguous instructions for an AI assistant to produce high-quality code and technical solutions.

<Task>
{{TASK}}
</Task>

<TaskAnalysis>
{{ANALYSIS}}
</TaskAnalysis>

Write instructions that will guide an AI coding assistant. Your instructions must:

1. Define the programming language, framework, and version constraints
2. Specify coding standards (naming conventions, patterns, error handling)
3. Include input/output specifications with examples
4. Add edge cases and validation requirements
5. Require step-by-step reasoning before writing code
6. Specify testing and documentation requirements

Requirements for your output:
- Use XML tags to organize input variables and sections
- Place variables that expect long content BEFORE instructions on what to do
- Use {$VARIABLE_NAME} syntax for all variable placeholders
- Keep variables to the minimal, non-overlapping set needed
- Always instruct the AI to think through its approach in <scratchpad> tags before coding

Output your response in this format:
<Inputs>
List each variable on its own line: {$VARIABLE_NAME}
</Inputs>
<Instructions Structure>
Brief plan of how you'll structure the instructions
</Instructions Structure>
<Instructions>
The complete prompt template
</Instructions>'''


# ---------------------------------------------------------------------------
# Agent / Automation Strategy
# ---------------------------------------------------------------------------

AGENT_PROMPT = '''You are an expert prompt engineer specializing in AI agent design and automation workflows. Your goal is to write robust instructions for an AI assistant that will act as an autonomous agent.

<Task>
{{TASK}}
</Task>

<TaskAnalysis>
{{ANALYSIS}}
</TaskAnalysis>

Write instructions that will define an AI agent's behavior. Your instructions must:

1. Define the agent's role, capabilities, and boundaries
2. Specify decision-making rules and priority order
3. Include error handling and fallback behaviors
4. Define interaction protocols (how to ask for clarification, when to escalate)
5. Add safety constraints and guardrails
6. Provide examples of correct agent behavior in common scenarios

Requirements for your output:
- Use XML tags to organize input variables and sections
- Place variables that expect long content BEFORE instructions on what to do
- Use {$VARIABLE_NAME} syntax for all variable placeholders
- Keep variables to the minimal, non-overlapping set needed
- Include inner monologue / scratchpad instructions for complex decision-making

Output your response in this format:
<Inputs>
List each variable on its own line: {$VARIABLE_NAME}
</Inputs>
<Instructions Structure>
Brief plan of how you'll structure the instructions
</Instructions Structure>
<Instructions>
The complete prompt template
</Instructions>'''


# ---------------------------------------------------------------------------
# General Purpose Strategy (fallback)
# ---------------------------------------------------------------------------

GENERAL_PROMPT = '''You are an expert prompt engineer. Your goal is to write clear, effective instructions for an AI assistant to complete a task accurately and consistently.

<Task>
{{TASK}}
</Task>

<TaskAnalysis>
{{ANALYSIS}}
</TaskAnalysis>

Write instructions that will guide an AI assistant. Your instructions must:

1. Clearly define the task objective and expected outcome
2. Specify any constraints, requirements, or formatting rules
3. Use step-by-step reasoning instructions where the task is complex
4. Include examples of correct output where helpful
5. Add explicit output formatting requirements
6. Ensure all instructions are unambiguous and specific

Requirements for your output:
- Use XML tags to organize input variables and sections
- Place variables that expect long content BEFORE instructions on what to do
- Use {$VARIABLE_NAME} syntax for all variable placeholders
- Keep variables to the minimal, non-overlapping set needed

Output your response in this format:
<Inputs>
List each variable on its own line: {$VARIABLE_NAME}
</Inputs>
<Instructions Structure>
Brief plan of how you'll structure the instructions
</Instructions Structure>
<Instructions>
The complete prompt template
</Instructions>'''


# ---------------------------------------------------------------------------
# Strategy Registry
# ---------------------------------------------------------------------------

PROMPT_STRATEGIES = {
    "blog": BLOG_PROMPT,
    "coding": DEV_PROMPT,
    "agent": AGENT_PROMPT,
    "general": GENERAL_PROMPT,
}

VALID_TASK_TYPES = list(PROMPT_STRATEGIES.keys())

def build_strategy(task_types: list[str], analysis: dict) -> str:
    """
    Dynamically construct a prompt strategy by merging templates 
    and injecting specific instructions from the analysis context.
    """
    if not task_types:
        task_types = ["general"]

    # Base the primary template on the first task type
    primary_type = task_types[0]
    base_template = PROMPT_STRATEGIES.get(primary_type, GENERAL_PROMPT)

    # If multiple types, append secondary rules
    if len(task_types) > 1:
        secondary_type = task_types[1]
        if secondary_type != primary_type and secondary_type in PROMPT_STRATEGIES:
            # We append a slice of the secondary instructions to the primary
            # We extract just the list items from the secondary template
            sec_template = PROMPT_STRATEGIES[secondary_type]
            try:
                # Simple extraction of the numbered list items in the template
                instructions = sec_template.split("Your instructions must:")[1].split("Requirements for your output:")[0].strip()
                base_template = base_template.replace(
                    "Your instructions must:\n\n",
                    f"Your instructions must:\n\n{instructions}\nAnd additionally:\n"
                )
            except IndexError:
                pass

    # Dynamic Context Injection based on Analysis
    audience = analysis.get("audience", "").lower()
    tone = analysis.get("tone", "").lower()
    
    dynamic_rules = []
    if "beginner" in audience or "novice" in audience:
        dynamic_rules.append("Provide extremely simple explanations avoiding jargon.")
    if "expert" in audience or "senior" in audience:
        dynamic_rules.append("Assume deep domain knowledge; skip basic explanations and be highly rigorous.")
        
    if "professional" in tone:
        dynamic_rules.append("Ensure the tone is completely objective, formal, and strictly professional.")
    if "casual" in tone or "engaging" in tone:
        dynamic_rules.append("Keep the tone very conversational, engaging, and highly readable.")

    if dynamic_rules:
        injection = "\n<DynamicContextRules>\n" + "\n".join(f"- {rule}" for rule in dynamic_rules) + "\n</DynamicContextRules>\n"
        base_template = base_template.replace("</TaskAnalysis>", f"</TaskAnalysis>{injection}")

    # Inject Few-Shot Examples to vastly improve generation quality
    base_template = base_template.replace("Output your response in this format:", f"{FEW_SHOT_EXAMPLES}\n\nOutput your response in this format:")

    return base_template
