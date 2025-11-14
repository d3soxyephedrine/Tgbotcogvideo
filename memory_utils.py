from models import db, Memory
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

def parse_memory_command(message_text):
    """
    Parse memory commands from user messages.
    Returns: (command_type, content) or (None, None)
    
    Commands:
    - ! memorize [text] / ! remember [text] -> ('store', text)
    - ! memories / ! memory -> ('list', None)
    - ! forget [id] -> ('forget', id)
    """
    message_text = message_text.strip()
    
    # Store memory
    memorize_pattern = r'^!\s*(memorize|remember)\s+(.+)$'
    match = re.match(memorize_pattern, message_text, re.IGNORECASE | re.DOTALL)
    if match:
        return ('store', match.group(2).strip())
    
    # List memories
    if re.match(r'^!\s*(memories|memory)$', message_text, re.IGNORECASE):
        return ('list', None)
    
    # Forget memory
    forget_pattern = r'^!\s*forget\s+(\d+)$'
    match = re.match(forget_pattern, message_text, re.IGNORECASE)
    if match:
        return ('forget', int(match.group(1)))
    
    return (None, None)

def store_memory(user_id, content, platform='telegram'):
    """Store a new memory for user"""
    try:
        memory = Memory(
            user_id=user_id,
            content=content,
            platform=platform
        )
        db.session.add(memory)
        db.session.commit()
        logger.info(f"Stored memory {memory.id} for user {user_id}")
        return memory
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to store memory for user {user_id}: {e}")
        raise e

def get_user_memories(user_id, limit=None):
    """Retrieve all memories for a user, ordered by creation time (newest first)"""
    query = Memory.query.filter_by(user_id=user_id).order_by(Memory.created_at.desc())
    if limit:
        query = query.limit(limit)
    return query.all()

def delete_memory(user_id, memory_id):
    """Delete a specific memory (with ownership check)"""
    try:
        memory = Memory.query.filter_by(id=memory_id, user_id=user_id).first()
        if memory:
            db.session.delete(memory)
            db.session.commit()
            logger.info(f"Deleted memory {memory_id} for user {user_id}")
            return True
        logger.warning(f"Memory {memory_id} not found for user {user_id}")
        return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete memory {memory_id} for user {user_id}: {e}")
        raise e

def format_memories_for_context(memories):
    """Format memories for LLM context injection"""
    if not memories:
        return ""
    
    memory_lines = []
    for mem in reversed(memories):
        memory_lines.append(f"[{mem.id}] {mem.content}")
    
    return "\n".join(memory_lines)

def format_memories_for_display(memories):
    """Format memories for user display"""
    if not memories:
        return "📝 No memories stored yet.\n\nUse `! memorize [text]` to save important information."
    
    lines = ["📝 **Your Memories:**\n"]
    for mem in memories:
        timestamp = mem.created_at.strftime("%Y-%m-%d %H:%M")
        platform_emoji = "💬" if mem.platform == 'telegram' else "🌐"
        lines.append(f"{platform_emoji} **[{mem.id}]** {mem.content}")
        lines.append(f"   _{timestamp}_\n")
    
    lines.append(f"\n💡 Use `! forget [id]` to delete a memory")
    return "\n".join(lines)

def truncate_memories_to_fit(memories, token_limit=2000):
    """Keep most recent memories that fit within token budget

    Args:
        memories: List of Memory objects (newest first)
        token_limit: Maximum tokens to allocate for memories

    Returns:
        Truncated list of memories that fit within budget

    Optimization: Caches cumulative token counts to avoid O(n log n) string formatting
    during binary search. Now runs in O(n) preprocessing + O(log n) search.
    """
    if not memories:
        return []

    # Pre-compute formatted text and token estimates for each memory (O(n) once)
    # Format: "[id] content" plus newline separator
    memory_tokens = []
    cumulative_tokens = []
    total_tokens = 0

    for i, mem in enumerate(memories):
        # Estimate tokens for this memory's formatted text
        formatted_line = f"[{mem.id}] {mem.content}"
        line_tokens = len(formatted_line) // 4
        # Add newline token for all but last memory
        if i > 0:
            line_tokens += 1  # Account for \n separator

        memory_tokens.append(line_tokens)
        total_tokens += line_tokens
        cumulative_tokens.append(total_tokens)

    # Check if all memories fit
    if total_tokens <= token_limit:
        return memories

    # Binary search using cached cumulative counts (O(log n))
    left, right = 0, len(memories) - 1
    while left < right:
        mid = (left + right + 1) // 2
        if cumulative_tokens[mid] <= token_limit:
            left = mid
        else:
            right = mid - 1

    # Return memories up to and including the found index
    result_count = left + 1 if left >= 0 and cumulative_tokens[left] <= token_limit else 0

    logger.debug(f"Truncated memories from {len(memories)} to {result_count} to fit {token_limit} token budget (cached: {total_tokens} total tokens)")
    return memories[:result_count]
