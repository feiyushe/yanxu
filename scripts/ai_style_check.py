#!/usr/bin/env python3
"""
gzh AI风格检测器
检测文章中的AI味特征，给出评分和修改建议

用法：
  python3 ai_style_check.py <文章路径>
  python3 ai_style_check.py --text "文章文本"

输出 JSON：
  { "score": 0-100, "issues": [...], "suggestions": [...] }
  score 越高越像AI写的，越低越像人写的
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_text(path: str = None, text: str = None) -> str:
    if text:
        return text
    if path:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # strip frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:].strip()
        return content
    return ""


def check_ai_style(text: str) -> dict:
    """检测AI风格特征，返回评分和问题列表"""
    issues = []
    score = 0  # 0=很人, 100=很AI

    lines = text.split("\n")
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip() and not p.startswith('---') and not p.startswith('![')]

    # ── 检测1: 序号分段（一、二、三、四） ──
    numbered = re.findall(r'^#{1,2}\s*[一二三四五六七八九十]+\s*$', text, re.MULTILINE)
    if numbered:
        score += len(numbered) * 8
        issues.append(f"❌ 序号分段: 发现 {len(numbered)} 处（一、二、三...），真人不会这么写")

    # ── 检测2: 段落长度过于均匀 ──
    if len(paragraphs) >= 4:
        lengths = [len(p) for p in paragraphs]
        avg_len = sum(lengths) / len(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        std_dev = variance ** 0.5
        if std_dev < 40:
            score += 15
            issues.append(f"❌ 段落长度太均匀（标准差={std_dev:.0f}），真人写段落长短差异更大")

    # ── 检测3: AI常见句式 ──
    ai_patterns = [
        (r'其实[,，]', '「其实」'),
        (r'不得不说', '「不得不说」'),
        (r'值得一提的是', '「值得一提的是」'),
        (r'这大概就是', '「这大概就是」'),
        (r'你有没有想过', '「你有没有想过」'),
        (r'让我们来看看|让我们来谈谈|让我们走进', '「让我们…」'),
        (r'总的来说', '「总的来说」'),
        (r'由此可见', '「由此可见」'),
        (r'综上所述', '「综上所述」'),
        (r'正如我们所', '「正如我们所」'),
        (r'无一不体现|无一不彰显|无一不透露出', '「无一不…」排比'),
        (r'不仅.*而且.*更[^是]', '「不仅…而且…更」排比三连'),
        (r'一方面.*另一方面', '「一方面…另一方面」'),
        (r'标志着[^0-9A-Za-z]', '「标志着」意义膨胀'),
        (r'奠定了[^0-9A-Za-z]', '「奠定了」意义膨胀'),
        (r'关键[^词]的[角环作]', '「关键的」意义膨胀'),
        (r'充当着|扮演着|被誉为|被视[作为]', '「充当着/扮演着」回避"是"'),
        (r'不可忽视|不容忽视', '「不可忽视」'),
        (r'日益|愈发', '「日益/愈发」'),
        (r'深深[深地]?烙印|刻下[了]?印记|留下[了]?[深不]?可?磨?[灭掉]?的?印记', '烙印/印记套话'),
        (r'希望[对你].*[帮助受益].*[如有如需]|如需.*帮助|感谢.*阅读', '「希望有所帮助/感谢阅读」协作语气'),
        (r'未来.*充满|前景.*光明|充满.*希望.*未来', '「未来充满希望」积极结尾'),
        (r'据了解|根据现有资料|根据公开信息|据不完全统计', '「据了解」知识截止声明'),
        (r'为了.*需要|由于.*的原因|基于.*的考虑', '「为了…需要/由于…的原因」填充废话'),
        (r'在.*的[背景浪潮时代]下', '「在…的背景下」套话'),
        (r'本质上[^的]|归根结底|说到底[^，,]', '「本质上/归根结底」说教话术'),
        (r'这不[仅仅光]?是.*更[是]?|这不[仅仅光]是.*还', '「这不只是…更是…」否定平行结构'),
    ]
    for pattern, label in ai_patterns:
        matches = re.findall(pattern, text)
        if matches:
            score += len(matches) * 5
            issues.append(f"❌ AI句式: 发现 {len(matches)} 处{label}")

    # ── 检测4: 排比结构 ──
    sentences = re.split(r'[。！？\n]', text)
    for i in range(len(sentences) - 2):
        trio = sentences[i:i+3]
        if all(len(s) > 10 for s in trio):
            # 排除列表项（以●、-、•、数字开头）
            if any(t.strip() and t.strip()[0] in '●-•·' for t in trio):
                continue
            first_chars = [s.strip()[0] if s.strip() else '' for s in trio]
            if len(set(first_chars)) == 1 and len(first_chars[0]) > 0:
                score += 10
                issues.append(f"❌ 排比句: 「{trio[0][:20]}...」开头重复")
                break

    # ── 检测5: 破折号滥用 ──
    em_dash_count = text.count('——')
    if em_dash_count > 3:
        score += 6
        issues.append(f"⚠️ 破折号过多: {em_dash_count} 个，真人很少每段都用破折号")
    elif em_dash_count > 5:
        score += 10
        issues.append(f"❌ 破折号严重滥用: {em_dash_count} 个")

    # ── 检测6: 结尾升华 ──
    last_para = paragraphs[-1] if paragraphs else ""
    if re.search(r'(这就是|这就是说|所以|因此|总之|归根结底|生活就是|人生就是)', last_para):
        score += 8
        issues.append(f"❌ 结尾升华: 「{last_para[:30]}...」像在写议论文结尾")

    # ── 检测7: 感叹号过多 ──
    exclaim_count = text.count('！') + text.count('!')
    if exclaim_count > 5:
        score += 5
        issues.append(f"⚠️ 感叹号过多: {exclaim_count} 个")

    # ── 检测8: 粗体/Markdown格式过重 ──
    bold_count = len(re.findall(r'\*\*[^*]+\*\*', text))
    if bold_count > 4:
        score += 5
        issues.append(f"⚠️ 粗体过多: {bold_count} 处，真人写公众号很少加粗")

    # ── 检测9: 字数 ──
    char_count = len(text)
    if char_count < 800:
        issues.append(f"⚠️ 篇幅偏短: {char_count} 字，公众号文章通常1200-1500字")
    elif char_count > 2500:
        issues.append(f"⚠️ 篇幅偏长: {char_count} 字")

    # ── 检测10: 缺少第一人称 ──
    first_person = len(re.findall(r'(我|我们|我家|我妈|我爸|我自己)', text))
    if first_person < 3 and char_count > 500:
        score += 8
        issues.append(f"⚠️ 缺少第一人称: 仅 {first_person} 处，真人写生活杂谈会更多用「我」")

    # ── 检测11: 缺少具体细节 ──
    specific_details = len(re.findall(r'(\d+[块|元|岁|年|个|次|天|度]|[\u4e00-\u9fff]{2,4}说|网友[^\s]{2,6})', text))
    if specific_details < 3 and char_count > 500:
        score += 5
        issues.append(f"⚠️ 缺少具体细节: 数字/引述/场景描写偏少（{specific_details} 处）")

    # 封顶
    score = min(score, 100)

    # 建议
    suggestions = []
    if score > 30:
        suggestions.append("去掉所有序号分段（一、二、三），用自然过渡")
        suggestions.append("缩短部分段落，让长短差异更大")
        suggestions.append("加入更多第一人称的具体经历")
        suggestions.append("结尾不要升华，用一句闲话或突然截断")
    if score > 50:
        suggestions.append("重写：先想一个真实场景，从那个场景开始写，不要从概念出发")

    return {
        "score": score,
        "label": "很AI" if score > 60 else "有些AI味" if score > 30 else "比较自然",
        "issues": issues,
        "suggestions": suggestions,
        "stats": {
            "char_count": char_count,
            "paragraph_count": len(paragraphs),
            "first_person_count": first_person,
            "specific_detail_count": specific_details,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="检测文章AI风格")
    parser.add_argument("path", nargs="?", help="文章路径")
    parser.add_argument("--text", help="直接传入文本")
    args = parser.parse_args()

    text = load_text(args.path, args.text)
    if not text:
        print("请提供文章路径或 --text 参数")
        sys.exit(1)

    result = check_ai_style(text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
