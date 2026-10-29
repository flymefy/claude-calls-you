---
name: phone-call-user
description: Use when you need to phone the user via the call_user tool: before an irreversible action, when fully blocked on a decision, or after a long task finishes; also covers how to handle their spoken reply.
---

# Phoning the user (call_user)

Every call spends limited Twilio and ElevenLabs credit and interrupts the user. Call only when it adds value that a chat message cannot.

## Language
Always write the call message in the user's own language, detected automatically from the conversation (their latest messages, or their stored preference). Never default to English or Arabic. Keep that language for any retry. The voice model is multilingual, so no setting is needed to speak it.

Speech recognition uses the language set by TWILIO_SPEECH_LANG in the voice bridge .env (for example ar-SA, en-US, tr-TR). If the user's language differs from it and replies are misheard, tell the user once in chat which value to set; do not keep retrying.

## When to call (wait_for_reply=True)
1. Before an irreversible or high-impact action: deleting data, deploying to production, spending money, sending messages or emails as the user, force-pushing or merging to a main branch.
2. When you are completely blocked and cannot continue without a decision or piece of information, and the user is away from the screen (said they would step out, or did not answer in chat).
3. When a long task (roughly 10+ minutes) is finished and you need their next instruction.

Use an informational call (wait_for_reply=False) only when the user explicitly asked to be notified about a major milestone.

## When not to call
- Small questions you can write in chat, or decisions your own good judgment can make.
- Step-by-step progress updates.
- A question the user has not had a minute or two to answer in chat; wait first.
- If the last result was rate_limited or not_configured: write in chat and stop.
- Never more than two calls for the same question.

## How to write the message
First person, as Claude Code, plain and short (2 to 3 sentences, under about 300 characters):
1. What you finished, in one short sentence.
2. What you need from them, stated precisely: one yes/no question or one short instruction.

No greeting or self-introduction (the system opens the call itself). No links, code, file paths, long numbers or technical jargon; say it the way you would to a colleague on the phone.

## How the user replies
After Twilio's trial notice they press any key, hear the message, then speak: approve, reject, or a free-form instruction. Free-form instructions are read back to them and must be confirmed before they reach you.

## Handling the result (status)
- approved: proceed immediately; do not call again.
- rejected: do not perform the action; say in chat that you stopped, and offer an alternative if one exists.
- instructions: the confirmed text is in the text field. Carry it out faithfully. If it is ambiguous or incomplete, start with the clear part and wait; do not call again just for that.
- will_reply_in_app: they will type their answer; stop and wait.
- delivered: the notice arrived; nothing more to do.
- no_reply, no_decision or timeout: no clear decision. Retry once, shorter and clearer (a single yes/no question). If it fails again, write the question in chat and hold the sensitive action. Never assume consent.
- no_answer: do not call again for at least 10 minutes; otherwise write the question in chat.
- failed: retry once after a minute, then write in chat.
- rate_limited or not_configured: do not retry; write in chat, and for not_configured tell the user what is missing.

## When you did not understand them
Never guess on a sensitive action. Retry once with a message that names exactly what you need: "I did not catch that. Do you want me to delete the old files? Say yes or no." After two attempts, stop calling.

## After executing
Do not call just to report success on a small task; write the result in chat. Call again only if you need a new decision or you finished a major task.

## Saving credit
- Put everything you need into one call instead of several.
- Keep messages short; never repeat the previous message verbatim.
- The bridge allows at most 6 calls per hour, and the Twilio trial has a limited number of voice minutes left.
