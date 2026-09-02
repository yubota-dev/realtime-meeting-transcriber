"""ASR model比較benchmark。

manifest JSONL:
{"audio": "refs/ja.wav", "reference": "正解文", "language": "ja", "condition": "noise"}
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from faster_whisper import WhisperModel

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "兩": 2, "两": 2}
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "萬": 10000}
_NUMBER_RE = re.compile(r"[〇零一二三四五六七八九十百千万萬兩两]+")


def _kanji_number(token: str) -> str:
    if not any(c in _UNITS for c in token):
        return "".join(str(_DIGITS[c]) for c in token)
    total = section = number = 0
    for char in token:
        if char in _DIGITS:
            number = _DIGITS[char]
        elif char in ("万", "萬"):
            section += number
            total += (section or 1) * 10000
            section = number = 0
        else:
            unit = _UNITS[char]
            section += (number or 1) * unit
            number = 0
    return str(total + section + number)


def normalize_text(text: str, language: str, opencc_converter=None) -> str:
    """適用順: NFKC -> 小文字 -> 簡繁統一 -> 数字統一 -> 句読点/空白除去。"""
    text = unicodedata.normalize("NFKC", text).lower()
    if language == "zh":
        if opencc_converter is None:
            try:
                from opencc import OpenCC
                opencc_converter = OpenCC("t2s")
            except ImportError as ex:
                raise RuntimeError("中国語評価にはopencc-python-reimplementedが必要です") from ex
        text = opencc_converter.convert(text)
    text = _NUMBER_RE.sub(lambda m: _kanji_number(m.group(0)), text)
    if language in ("ja", "zh", "mixed"):
        return "".join(c for c in text if not c.isspace()
                       and not unicodedata.category(c).startswith(("P", "S")))
    text = "".join(" " if unicodedata.category(c).startswith(("P", "S")) else c
                   for c in text)
    return " ".join(text.split())


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def error_rate(reference: str, hypothesis: str, language: str) -> dict:
    ref = normalize_text(reference, language)
    hyp = normalize_text(hypothesis, language)
    ref_units = ref.split() if language == "en" else list(ref)
    hyp_units = hyp.split() if language == "en" else list(hyp)
    errors = edit_distance(ref_units, hyp_units)
    return {
        "metric": "WER" if language == "en" else "CER",
        "errors": errors,
        "reference_units": len(ref_units),
        "rate": errors / max(len(ref_units), 1),
        "normalized_reference": ref,
        "normalized_hypothesis": hyp,
    }


def load_manifest(path):
    rows = []
    base = Path(path).resolve().parent
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                audio = Path(row["audio"])
                row["audio"] = str(audio if audio.is_absolute() else base / audio)
                rows.append(row)
    return rows


def benchmark(manifest, models, device="cuda", compute_type="float16"):
    rows = load_manifest(manifest)
    report = {"normalization_version": 1, "models": {}}
    for model_name in models:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        details = []
        total_errors = total_units = 0
        for row in rows:
            lang = row.get("language", "auto")
            forced = lang if lang in ("ja", "en", "zh") else None
            segments, info = model.transcribe(
                row["audio"], language=forced, beam_size=5,
                vad_filter=True, condition_on_previous_text=False,
            )
            hypothesis = "".join(s.text for s in segments).strip()
            score_lang = lang if lang != "auto" else info.language
            score = error_rate(row["reference"], hypothesis, score_lang)
            total_errors += score["errors"]
            total_units += score["reference_units"]
            details.append({**row, "hypothesis": hypothesis, **score})
        report["models"][model_name] = {
            "micro_error_rate": total_errors / max(total_units, 1),
            "errors": total_errors,
            "reference_units": total_units,
            "details": details,
        }
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--models", default="large-v3,large-v3-turbo")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--out", default="benchmark_asr_report.json")
    args = ap.parse_args(argv)
    report = benchmark(
        args.manifest, [x.strip() for x in args.models.split(",") if x.strip()],
        args.device, args.compute_type,
    )
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    for name, result in report["models"].items():
        print(f"{name}: {result['micro_error_rate']:.4f}")
    print(f"保存: {args.out}")


if __name__ == "__main__":
    main()
