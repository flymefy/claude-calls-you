"""خادم MCP محلي (stdio) يعرّض أداة call_user لـ Claude Code."""
import asyncio
import json

from mcp.server.fastmcp import FastMCP

import bridge

mcp = FastMCP("voice-call")


@mcp.tool()
async def call_user(message: str, wait_for_reply: bool = True, timeout_sec: int = 120) -> str:
    """اتصل بهاتف المستخدم وانطق رسالة عربية قصيرة، ويمكن للمستخدم الرد بضغط رقم.

    استخدمها فقط قبل إجراء حساس لا رجعة فيه، أو عند التوقف تماماً بانتظار قرار، أو عند انتهاء مهمة طويلة.
    message: بالعربية، بدون روابط أو أكواد أو إنجليزية. تكلم بلسان Claude Code بصيغة المتكلم: ماذا أنجزتَ بإيجاز، ثم ماذا تحتاج من المستخدم (قرار أو أوامر).
             في وضع الوكيل الصوتي يتحدث المستخدم معك بحرية ويعطيك أوامره، وتصلك في حقل text.
    wait_for_reply: True = تنتظر الضغط (1 موافق، 2 رفض، 3 إعادة، 4 سأكتب لك في التطبيق).
                    False = مكالمة إعلامية فقط.
    النتيجة JSON فيها status (وقد تكون instructions مع حقل text فيه رسالة المستخدم): approved / rejected / will_reply_in_app / delivered /
    no_reply / no_answer / timeout / failed / not_configured / rate_limited.
    """
    timeout_sec = max(30, min(int(timeout_sec), 600))
    result = await asyncio.to_thread(bridge.notify, message, wait_for_reply, timeout_sec)
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
