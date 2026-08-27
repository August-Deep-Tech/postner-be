from __future__ import annotations

import re

MOTION_DURATION_S = 4.5
MOTION_FPS = 30

PRESETS = frozenset({"fade_kenburns"})

_FADE_KENBURNS_CSS = """
<style id="postner-motion">
  #canvas.motion-ready .title,
  #canvas.motion-ready .script,
  #canvas.motion-ready .headline,
  #canvas.motion-ready .copy,
  #canvas.motion-ready .subtitle,
  #canvas.motion-ready .body,
  #canvas.motion-ready .num,
  #canvas.motion-ready .brand {
    animation: postner-fade-up 0.9s ease-out both;
  }
  #canvas.motion-ready .script { animation-delay: 0.05s; }
  #canvas.motion-ready .title,
  #canvas.motion-ready .headline { animation-delay: 0.2s; }
  #canvas.motion-ready .subtitle,
  #canvas.motion-ready .body { animation-delay: 0.45s; }
  #canvas.motion-ready .num { animation-delay: 0.15s; }

  #canvas.motion-ready img {
    transform-origin: center center;
    animation: postner-kenburns 4.5s ease-out both;
  }

  #canvas.motion-ready .pill {
    animation: postner-fade-in 0.7s ease-out 1.1s both;
  }

  @keyframes postner-fade-up {
    from { opacity: 0; transform: translateY(28px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes postner-fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }
  @keyframes postner-kenburns {
    from { transform: scale(1); }
    to { transform: scale(1.06); }
  }
</style>
"""


def apply_motion_preset(html: str, preset: str = "fade_kenburns") -> str:
    """Inject fixed CSS motion into filled HTML for video capture."""
    name = (preset or "fade_kenburns").strip().lower()
    if name not in PRESETS:
        raise ValueError(f"Unknown motion_preset '{preset}'. Available: {sorted(PRESETS)}")

    if 'id="postner-motion"' not in html:
        if re.search(r"</head>", html, flags=re.IGNORECASE):
            html = re.sub(
                r"</head>",
                _FADE_KENBURNS_CSS + "</head>",
                html,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            html = _FADE_KENBURNS_CSS + html

    def _add_motion_class(match: re.Match[str]) -> str:
        tag = match.group(0)
        if "motion-ready" in tag:
            return tag
        if re.search(r"\bclass=", tag):
            return re.sub(
                r'\bclass=(["\'])([^"\']*)\1',
                lambda m: f'class={m.group(1)}{m.group(2)} motion-ready{m.group(1)}',
                tag,
                count=1,
            )
        return tag[:-1] + ' class="motion-ready">'

    html = re.sub(
        r"<[^>]*\bid=['\"]canvas['\"][^>]*>",
        _add_motion_class,
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    return html
