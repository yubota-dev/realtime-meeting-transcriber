"""qwen2.5:14b（Ollama）を使った翻訳・要約。すべてローカル・ゼロ円。

- 翻訳: 短いタイムアウト。失敗しても呼び出し側で捕捉。
- 要約: 長い会議はチャンク分割（map-reduce）。例外を内部で握り潰し、
  決して raise しない（要約段階でのクラッシュを防ぐ）。
"""
import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5:14b"

TRANSLATE_TIMEOUT = 30   # 翻訳は短く。詰まっても文字起こしを長く止めない
SUMMARY_TIMEOUT = 300    # 要約は長めに許容
CHUNK_SIZE = 40          # 要約の分割単位（発言数）

SYSTEM = (
    "あなたは技術打ち合わせの議事録アシスタントです。出力は日本語。"
    "憶測で補わず、記録にある内容だけを要約すること。"
    "発言には話者ラベル（自分／相手）が付いている。"
)


def _generate(prompt, system=None, temperature=0.2, timeout=180):
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    if system:
        payload["system"] = system
    r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["response"].strip()


def translate_to_ja(text, src_lang):
    """非日本語の発言を日本語に訳す。失敗時は呼び出し側で捕捉する。"""
    system = (
        "あなたは技術会議の通訳です。専門用語は正確に、固有名詞は原文のまま残し、"
        "自然な日本語に訳してください。訳文のみを出力し、説明や前置きは一切付けないこと。"
    )
    prompt = f"次の{src_lang}の発言を日本語に訳してください。\n\n{text}"
    return _generate(prompt, system, timeout=TRANSLATE_TIMEOUT)


def _format(entries):
    lines = []
    for e in entries:
        body = e.get("ja") or e.get("original", "")
        prefix = f"[{e.get('ts', '')}]"
        spk = e.get("speaker")
        if spk:
            prefix += f" {spk}:"
        lines.append(f"{prefix} {body}")
    return "\n".join(lines)


def _summarize_4points(entries, scope_label):
    prompt = (
        f"以下は{scope_label}の会議文字起こしです。"
        "次の4つの観点で簡潔に箇条書きしてください。該当がなければ「なし」と書く。\n\n"
        "■ 決定事項\n■ 保留・宿題（ToDo）\n■ 自分宛ての質問・依頼\n■ 未解決の論点\n\n"
        f"--- 文字起こし ---\n{_format(entries)}"
    )
    return _generate(prompt, SYSTEM, temperature=0.1, timeout=SUMMARY_TIMEOUT)


def _summarize_brief(entries):
    prompt = (
        "以下は会議文字起こしの一部です。要点を3〜6個の箇条書きで簡潔にまとめてください。\n\n"
        f"--- 文字起こし ---\n{_format(entries)}"
    )
    return _generate(prompt, SYSTEM, temperature=0.1, timeout=SUMMARY_TIMEOUT)


def _reduce_4points(partials, scope_label):
    joined = "\n".join(f"- {p}" for p in partials)
    prompt = (
        f"以下は{scope_label}を分割して要約したメモです。全体を統合し、"
        "次の4観点で簡潔にまとめてください。該当がなければ「なし」と書く。\n\n"
        "■ 決定事項\n■ 保留・宿題（ToDo）\n■ 自分宛ての質問・依頼\n■ 未解決の論点\n\n"
        f"--- 分割要約 ---\n{joined}"
    )
    return _generate(prompt, SYSTEM, temperature=0.1, timeout=SUMMARY_TIMEOUT)


def summarize_log(entries, scope_label):
    """会議ログを要約する。長い場合は分割して統合。決して例外を投げない。"""
    if not entries:
        return "(記録がありません)"
    try:
        if len(entries) <= CHUNK_SIZE:
            return _summarize_4points(entries, scope_label)
        chunks = [entries[i:i + CHUNK_SIZE] for i in range(0, len(entries), CHUNK_SIZE)]
        partials = []
        for i, ch in enumerate(chunks, 1):
            try:
                partials.append(_summarize_brief(ch))
            except Exception as ex:
                partials.append(f"(チャンク{i}要約失敗: {ex})")
        return _reduce_4points(partials, scope_label)
    except Exception as ex:
        return f"(要約失敗: {ex})"
