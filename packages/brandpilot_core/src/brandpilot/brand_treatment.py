"""One CTA treatment is carried between weeks; copy and scene may change."""
from copy import deepcopy


def with_cta(identity, palette):
    identity = deepcopy(identity or {})
    if not identity.get("cta_treatment"):
        def luminance(color):
            rgb = [int(color[index:index+2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in rgb]
            return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
        background = min(palette, key=luminance)
        foreground = "#ffffff" if luminance(background) < .179 else "#000000"
        identity["cta_treatment"] = {
            "position": "bottom_center", "box_1080x1350": {"x": 108, "y": 1160, "width": 864, "height": 96},
            "shape": "rounded_rectangle", "corner_radius_px": 24,
            "fill": background, "text_color": foreground, "font_size_px": 32,
            "font_weight": "bold", "font_family": "same campaign family; Arabic-capable companion for Arabic",
            "alignment": "center", "effects": "no gradient, outline, icon or shadow",
        }
    return identity


def cta_instruction(treatment):
    import json
    return ("FIXED BRAND CTA: " + json.dumps(treatment, ensure_ascii=False) +
        ". Use this exact box, shape, fill, font treatment and position for every post, "
        "including regenerated designs. Only CTA wording may change. Reserve this area before composing "
        "the scene; keep product labels and other copy outside it. This contract overrides conflicting "
        "CTA placement/style in the prompt or reference. Do not move or restyle the CTA for Arabic.")
