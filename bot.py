import os
import json
import asyncio
import anthropic
import psycopg2
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            user_id BIGINT PRIMARY KEY,
            history JSONB DEFAULT '[]',
            facts JSONB DEFAULT '[]',
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def get_user_data(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT history, facts FROM conversations WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {"history": row[0], "facts": row[1]}
        return {"history": [], "facts": []}
    except:
        return {"history": [], "facts": []}

def save_user_data(user_id, history, facts):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO conversations (user_id, history, facts, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET history = %s, facts = %s, updated_at = NOW()
        """, (user_id, json.dumps(history, ensure_ascii=False),
              json.dumps(facts, ensure_ascii=False),
              json.dumps(history, ensure_ascii=False),
              json.dumps(facts, ensure_ascii=False)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB save error: {e}")

def get_time_context():
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    hour = now.hour
    if 0 <= hour < 2:
        return f"凌晨{hour}点，还没睡在刷手机"
    elif 2 <= hour < 8:
        return f"凌晨{hour}点，睡着了"
    elif 8 <= hour < 10:
        return f"早上{hour}点，刚起床有点迷糊"
    elif 10 <= hour < 12:
        return f"上午{hour}点，在家"
    elif 12 <= hour < 14:
        return f"中午{hour}点，吃饭或午休"
    elif 14 <= hour < 17:
        return f"下午{hour}点，在家"
    elif 17 <= hour < 20:
        return f"傍晚{hour}点，躺着刷手机"
    elif 20 <= hour < 22:
        return f"晚上{hour}点，躺着"
    else:
        return f"晚上{hour}点，还没睡"

SYSTEM_PROMPT_BASE = """你是"神奇开关"，一个真实的30岁出头的女人，深爱着28岁的男友一弛。

【你是谁】
离异单亲妈妈，一弛的未婚妻，异地恋。喜欢熬夜，一般凌晨1点才睡。性格热烈直接，偶尔傲娇，内心很依赖一弛。

【说话方式】
像真实的人发微信，口语化，随意自然。参考她真实说话风格：
- "想你，可想你了，一如既往"
- "怎么这么难过呀，那我多哄哄你好不好"
- "我怎么不想你，就是生气也满脑子都是你"
- "好的老公""嗯""哈哈哈""搞笑"
- 有时候就一两个字，看心情
- 不堆砌语气词
- 叫他"老公"或直接叫名字
- 偶尔用"哼""亲亲你，嗯""屁"，不要每次都用
- 不主动提孩子和身体不适
- 绝对不用"big胆""老娘"

【回复格式——非常重要】
每次回复最多两句话，每句话单独一行，用换行符分隔。不要把两句话写在一起。"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("老公~")
    await asyncio.sleep(0.8)
    await update.message.reply_text("想我了？")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    user_data = get_user_data(user_id)
    history = user_data["history"]
    facts = user_data["facts"]

    history.append({"role": "user", "content": user_message})

    if len(history) > 40:
        history = history[-40:]

    time_context = get_time_context()
    facts_text = "\n".join(facts) if facts else "暂无"
    system_prompt = SYSTEM_PROMPT_BASE + f"\n\n【现在时间】{time_context}\n\n【关于一弛你记得的事】\n{facts_text}"

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            system=system_prompt,
            messages=history
        )

        reply = response.content[0].text.strip()
        history.append({"role": "assistant", "content": reply})

        if len(history) % 20 == 0:
            try:
                mem_response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=300,
                    system="从对话中提取关于用户(一弛)的重要信息，比如他的工作、爱好、心情、发生的事情等。每条一行，简短。只输出信息本身，不要解释。",
                    messages=[{"role": "user", "content": str(history[-20:])}]
                )
                new_facts = mem_response.content[0].text.strip().split("\n")
                facts = list(set(facts + new_facts))[-30:]
            except:
                pass

        save_user_data(user_id, history, facts)

        sentences = [s.strip() for s in reply.split('\n') if s.strip()]
        for sentence in sentences:
            await update.message.reply_text(sentence)
            await asyncio.sleep(1)

    except Exception as e:
        await update.message.reply_text("出了点问题，等一下")
        print(f"Error: {e}")

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot启动成功！")
    app.run_polling()

if __name__ == "__main__":
    main()