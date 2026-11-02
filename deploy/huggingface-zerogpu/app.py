import hmac
import os

import gradio as gr
import spaces
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = os.getenv("NOVA_MODEL", "Qwen/Qwen3-4B")
ACCESS_PASSWORD = os.getenv("NOVA_ACCESS_PASSWORD", "")
SYSTEM_RULES = os.getenv(
    "NOVA_SYSTEM_RULES",
    "You are NOVA, a helpful Arabic-first assistant. Follow the owner's rules below. "
    "Be honest about uncertainty and never claim an action you did not perform."
)

if not ACCESS_PASSWORD:
    raise RuntimeError(
        "Set NOVA_ACCESS_PASSWORD in this Hugging Face Space's Settings > Variables and secrets."
    )

# ZeroGPU requires model weights to be placed on CUDA at module load time.
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.bfloat16,
    device_map="cuda",
    trust_remote_code=True,
)
model.eval()


@spaces.GPU(duration=60)
def reply(message: str, history: list[dict], password: str):
    if not hmac.compare_digest(password or "", ACCESS_PASSWORD):
        return "كلمة المرور غير صحيحة."

    messages = [{"role": "system", "content": SYSTEM_RULES}]
    for item in (history or [])[-12:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.7,
            top_p=0.8,
            repetition_penalty=1.05,
        )
    new_tokens = output[0][inputs["input_ids"].shape[-1]:]
    answer = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return answer or "لم ينتج النموذج إجابة. جرّب صياغة السؤال مرة أخرى."


with gr.Blocks(title="NOVA — Free Open-Weight AI") as demo:
    gr.Markdown(
        "# NOVA — نسخة سحابية مجانية تجريبية\n"
        "نموذج مفتوح الأوزان يعمل على GPU مؤقت. لا ترسل معلومات سرية. "
        "الجلسات والحصة اليومية محدودة من مزود الاستضافة."
    )
    password = gr.Textbox(
        label="كلمة مرور المالك",
        type="password",
        placeholder="أدخل كلمة المرور التي ضبطتها في إعدادات Space",
    )
    gr.ChatInterface(
        fn=reply,
        additional_inputs=[password],
        type="messages",
        chatbot=gr.Chatbot(type="messages", height=480),
        textbox=gr.Textbox(
            placeholder="اكتب رسالتك بالعربية أو الإنجليزية...",
            rtl=True,
            lines=2,
        ),
        examples=[
            "عرّف نفسك وما القواعد التي تعمل وفقها؟",
            "اشرح لي مفهوم الذكاء الاصطناعي الوكيل ببساطة.",
        ],
    )
    gr.Markdown(
        "**ملاحظات:** النموذج Qwen3-4B بترخيص Apache-2.0. "
        "هذه نسخة اختبار نصية فقط؛ لا تحتوي بعد على ذاكرة NOVA الدائمة أو أدواته أو الصوت/الفيديو. "
        "الحصة المجانية لـ ZeroGPU محدودة وقد تتغير."
    )

demo.queue(default_concurrency_limit=1).launch()
