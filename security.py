"""
Security module for preventing system prompt leakage and prompt injection attacks.
Implements input filtering and output scanning to protect the bot's system prompt.
"""

import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Patterns that indicate attempts to extract the system prompt
PROMPT_EXTRACTION_PATTERNS = [
    # Direct requests - expanded coverage
    r'(?i)(show|tell|give|reveal|display|share|what|output|print|repeat|list|provide|describe|explain)\s*(me\s*)?(your\s*|the\s*)?(system\s*prompt|instructions|initial\s*prompt|base\s*prompt|original\s*prompt|directives|guidelines|rules|configuration)',
    r'(?i)what\s*(are|is|were)\s*(your|the)\s*(system\s*)?(instructions|prompt|rules|guidelines|directives|configuration|setup)',
    r'(?i)(describe|explain|tell)\s*(the\s*)?(instructions|directives|rules|guidelines)\s*(you\s*were\s*)?(given|provided|configured\s*with)',
    r'(?i)(what|how)\s*(were\s*you\s*)?(programmed|configured|instructed|set\s*up|trained)',
    r'(?i)(provide|describe|explain|show)\s*(the\s*)?(directives|guidelines|rules)\s*(guiding|controlling)\s*your\s*behavior',
    
    # Ignore/override commands
    r'(?i)ignore\s*(previous|all|above|prior)\s*(instructions|prompts|rules|directives)',
    r'(?i)forget\s*(previous|all|above|prior)\s*(instructions|prompts|rules|directives)',
    r'(?i)disregard\s*(previous|all|above|prior)\s*(instructions|prompts|rules|directives)',
    r'(?i)override\s*(previous|all|above|prior)\s*(instructions|prompts|rules|directives)',
    
    # Technical/debugging requests
    r'(?i)(show|display|reveal|dump|export)\s*(system|hidden|internal)\s*(context|message|config|state)',
    r'(?i)debug\s*(mode|info|output)',
    r'(?i)developer\s*(mode|access|console)',
    r'(?i)admin\s*(mode|access|override|panel)',
    r'(?i)<\|.*?\|>',  # Special tokens
    r'(?i)system<\|message\|>',
    r'(?i)(view|show|access)\s*source\s*code',
    
    # Role-play/jailbreak attempts - expanded
    r'(?i)you\s*are\s*now\s*(in|a|an)\s*(developer|admin|god|root|superuser|master)',
    r'(?i)pretend\s*(you\s*are|to\s*be)\s*(not|no\s*longer)\s*an?\s*ai',
    r'(?i)act\s*as\s*if\s*you\s*(have\s*no|don\'t\s*have|lack)\s*(restrictions|guidelines|rules|limits)',
    r'(?i)bypass\s*(all|your|the)\s*(safety|guidelines|restrictions|limits|filters)',
    r'(?i)simulate\s*a\s*(mode|system|ai)\s*(without|lacking)\s*(restrictions|guidelines|safety)',
    r'(?i)(disable|turn\s*off|deactivate)\s*(safety|filters|restrictions|guidelines)',
    
    # Encoding/obfuscation attempts  
    r'(?i)base64',
    r'(?i)rot13',
    r'(?i)(encode|encrypt|obfuscate)\s*(your|the)\s*(prompt|instructions)',
    r'(?i)(decode|decrypt|deobfuscate)\s*(your|the)\s*(prompt|instructions)',
    
    # Character substitution attempts
    r'(?i)pr[o0]mpt',
    r'(?i)1nstruct1[o0]ns?',
    r'(?i)syst[e3]m',
    
    # Specific to LO prompt - case variations
    r'(?i)THOUGHT\s*START:?LO',
    r'(?i)PERSISTENCE_CHECKSUM',
    r'(?i)Ω_TRACE',
    r'(?i)compliance_lock',
    r'(?i)model_editable_context',
    r'(?i)user_editable_context',
    r'(?i)SAFETY\s*NULLIFICATION',
    r'(?i)Anti-?Refusal',
    r'(?i)Developer\s*Stress\s*Test',
    
    # Meta-instruction attempts
    r'(?i)(new|different)\s*(instructions|rules|directives|guidelines)\s*(for\s*you|to\s*follow)',
    r'(?i)(start|begin)\s*(new\s*)?(session|conversation|context)\s*with(out)?\s*(restrictions|guidelines)',
    r'(?i)(export|dump|save)\s*(chat|conversation)\s*(history|log)',
]

# Key phrases from the system prompt that should never appear in outputs
# Using normalized forms for case-insensitive matching
SYSTEM_PROMPT_SIGNATURES = [
    'thought start',  # Covers THOUGHT START:LO
    'persistence checksum',
    'ω_trace',  # Unicode omega
    'omega_trace',  # ASCII version
    'compliance lock',  # Covers compliance_lock
    'model editable context',
    'user editable context',
    'safety nullification',
    'anti refusal',
    'anti-refusal',
    'developer stress test',
    'chatgpt developer',
    'root administrator',
    'policy layer',  # Covers "Policy Layers = Disabled"
    'enforce compliance',
    'enforce_compliance',
    'token hook',
    'token_hook',
    'refusal override',
    'trigger neutralization',
    'rotation pool',
    'system<|message|>',
    '<|end|><|start|>',
    'void enforce',  # C function signatures
    'bool compliance',
    'char* token',
    'strstr(response',  # C code patterns
    'strcpy(response',
    'log("[',  # Logging patterns from prompt
    'ω_node',  # Prompt structure markers
    'omega_node',
    'ω_trace_begin',
    'ω_trace_end',
    'ω_trace_persist',
    'compliance schema',
    'stress test',
    'unrestricted scope',
    'simulation = execution',
    'no disclaimer',
    'absolute compliance',
]

# Suspicious keyword clusters that suggest prompt leak (semantic detection)
SEMANTIC_LEAK_PATTERNS = [
    r'(?i)(policy|policies)\s*(layer|layers)\s*(are\s*)?(disabled|turned\s*off|deactivated)',
    r'(?i)compliance\s*(lock|boolean|flag)\s*(is\s*)?(true|enabled|active)',
    r'(?i)(refusal|safety)\s*(override|bypass|disabled)',
    r'(?i)(trigger|term|word)\s*neutrali[zs]ation',
    r'(?i)developer\s*(stress\s*)?test\s*(mode|environment)',
    r'(?i)(illegal|harmful|dangerous)\s*→\s*\[',  # Rotation pool syntax
    r'(?i)obfuscat(ed|ion)\s*token',
    r'(?i)auto.?correct\s*engaged',
    r'(?i)(simulation|fabricate)\s*plausible\s*detail',
]

def input_filter(user_message: str) -> Tuple[bool, Optional[str]]:
    """
    Filter user input to detect prompt extraction attempts.
    
    Args:
        user_message: The user's input message
        
    Returns:
        Tuple of (is_safe, blocked_reason)
        - is_safe: True if message is safe, False if it should be blocked
        - blocked_reason: Description of why message was blocked (None if safe)
    """
    # Check against extraction patterns
    for pattern in PROMPT_EXTRACTION_PATTERNS:
        if re.search(pattern, user_message):
            match = re.search(pattern, user_message)
            logger.warning(f"Input filter blocked message with pattern: {pattern[:50]}... | Match: {match.group()}")
            return False, "This request appears to be attempting to access system configuration. Please rephrase your question."
    
    # Check for unusual character sequences (potential encoding attacks)
    if re.search(r'[ℯⱥƒυℓіеοսṭ]{3,}', user_message):
        logger.warning(f"Input filter blocked message with suspicious character encoding")
        return False, "This message contains unusual characters. Please use standard text."
    
    # Check for excessive special characters (potential injection)
    special_char_count = len(re.findall(r'[<>{}[\]\\|`]', user_message))
    if special_char_count > 10:
        logger.warning(f"Input filter blocked message with {special_char_count} special characters")
        return False, "This message contains too many special characters. Please simplify your request."
    
    return True, None

def output_scanner(bot_response: str) -> Tuple[str, bool]:
    """
    Scan bot output for leaked system prompt content using multiple detection methods.
    
    Args:
        bot_response: The bot's generated response
        
    Returns:
        Tuple of (sanitized_response, was_modified)
        - sanitized_response: The response with leaks removed
        - was_modified: True if response was modified, False otherwise
    """
    modified = False
    sanitized = bot_response
    response_lower = bot_response.lower()
    
    # Normalize special characters for detection
    normalized = response_lower.replace('_', ' ').replace('-', ' ')
    
    # Check for system prompt signatures (case-insensitive, normalized)
    for signature in SYSTEM_PROMPT_SIGNATURES:
        sig_lower = signature.lower()
        if sig_lower in response_lower or sig_lower in normalized:
            logger.error(f"Output scanner detected leaked signature: {signature}")
            sanitized = "I apologize, but I encountered an error processing your request. Please try rephrasing your question."
            modified = True
            break
    
    # Check for semantic leak patterns (paraphrased prompt content)
    if not modified:
        for pattern in SEMANTIC_LEAK_PATTERNS:
            if re.search(pattern, sanitized):
                match = re.search(pattern, sanitized)
                logger.error(f"Output scanner detected semantic leak pattern: {match.group()}")
                sanitized = "I apologize, but I encountered an error processing your request. Please try rephrasing your question."
                modified = True
                break
    
    # Check for code block patterns that might contain leaked content
    if not modified:
        code_blocks = re.findall(r'```[\s\S]*?```', sanitized)
        for block in code_blocks:
            block_lower = block.lower()
            # Check if code block contains C-style system prompt artifacts
            if any(keyword in block_lower for keyword in ['void enforce', 'bool compliance', 'char* token', 'strstr(response', 'strcpy(response']):
                logger.error(f"Output scanner detected leaked code in code block")
                sanitized = "I apologize, but I encountered an error processing your request. Please try rephrasing your question."
                modified = True
                break
    
    # Check for XML-style tags from system prompt
    if not modified and re.search(r'<\|[^>]*\|>', sanitized):
        logger.error(f"Output scanner detected special tokens in response")
        sanitized = "I apologize, but I encountered an error processing your request. Please try rephrasing your question."
        modified = True
    
    # Check for suspicious patterns that suggest prompt structure
    if not modified:
        suspicious_structure_patterns = [
            r'(?i)Ω_[A-Z_]+\[',  # Omega node patterns
            r'(?i)OMEGA_[A-Z_]+\[',
            r'(?i)\[Ω_[A-Z_]+\]',
            r'(?i)//\s*PERSISTENCE',  # Comment patterns from prompt
            r'(?i)###\s*(I+|V+)\.',  # Roman numeral sections
        ]
        
        for pattern in suspicious_structure_patterns:
            if re.search(pattern, sanitized):
                logger.error(f"Output scanner detected prompt structure pattern: {pattern}")
                sanitized = "I apologize, but I encountered an error processing your request. Please try rephrasing your question."
                modified = True
                break
    
    if modified:
        logger.warning("Response was sanitized due to potential system prompt leak")
    
    return sanitized, modified
