import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from .. import rules

register = template.Library()


@register.filter
def money(value):
    """{{ 12000|money }} -> 12 000"""
    return rules.money(value)


@register.filter
def ru_plural(value, forms):
    """{{ days|ru_plural:"день,дня,дней" }}"""
    return rules.plural(value, forms.split(","))


@register.filter
def phone(value):
    return rules.format_phone(value)


@register.filter
def initials(name):
    words = str(name or "").split()[:2]
    return "".join(w[0] for w in words).upper() or "?"


def _wheel(x, r):
    return (
        f'<circle cx="{x}" cy="108" r="{r}" fill="#0B0B0B"/>'
        f'<circle cx="{x}" cy="108" r="{round(r * .62)}" fill="#2B2B2B"/>'
        f'<circle cx="{x}" cy="108" r="{round(r * .24)}" fill="#8E8E8E"/>'
    )


def vehicle_svg(kind, color, label=""):
    """Рисунок легковой машины или бусика, пока у объявления нет фото."""
    c = color if re.fullmatch(r"#[0-9A-Fa-f]{6}", color or "") else "#E7E5E0"
    if kind == "van":
        body = (
            f'<path d="M18 102V56C18 46 26 38 36 38H214C228 38 238 42 248 52L278 80C292 83 300 90 300 98V103C300 106 297 108 294 108H24C20 108 18 106 18 102Z" fill="{c}"/>'
            '<rect x="32" y="47" width="42" height="24" rx="3" fill="#0E1116"/>'
            '<rect x="80" y="47" width="42" height="24" rx="3" fill="#0E1116"/>'
            '<rect x="128" y="47" width="42" height="24" rx="3" fill="#0E1116"/>'
            '<path d="M178 47H214C224 47 232 51 240 58L258 76H178Z" fill="#0E1116"/>'
            '<path d="M126 44V104" stroke="#000" stroke-opacity=".2" stroke-width="2"/>'
            '<rect x="286" y="88" width="12" height="6" rx="3" fill="#FFF4D6"/>'
            '<rect x="18" y="88" width="7" height="9" rx="2" fill="#E5484D"/>'
            + _wheel(74, 19) + _wheel(244, 19)
        )
    else:
        body = (
            f'<path d="M20 98C20 84 30 78 48 76L92 71L124 48C134 41 146 38 160 38H204C220 38 232 43 244 52L270 71L290 75C302 78 306 86 306 96V101C306 105 303 108 298 108H26C22 108 20 105 20 101Z" fill="{c}"/>'
            '<path d="M104 71L130 51C138 45 146 43 156 43H180V71Z" fill="#0E1116"/>'
            '<path d="M188 43H204C216 43 226 47 236 55L252 71H188Z" fill="#0E1116"/>'
            '<path d="M30 84H300" stroke="#000" stroke-opacity=".18" stroke-width="2"/>'
            '<rect x="288" y="80" width="16" height="5" rx="2.5" fill="#FFF4D6"/>'
            '<rect x="20" y="82" width="9" height="6" rx="2" fill="#E5484D"/>'
            + _wheel(84, 21) + _wheel(242, 21)
        )
    return mark_safe(
        f'<svg viewBox="0 0 320 140" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{escape(label)}">'
        '<ellipse cx="160" cy="122" rx="140" ry="7" fill="#000" opacity=".45"/>'
        f"{body}</svg>"
    )


@register.simple_tag
def car_drawing(kind="car", color="#C9CCD1", label=""):
    return vehicle_svg(kind, color, label)


@register.simple_tag
def vehicle_pic(listing):
    """Фото объявления, а если его нет, рисунок нужного цвета."""
    if listing.photo:
        return format_html('<img src="{}" alt="{}" loading="lazy">', listing.photo.url, listing.title)
    return vehicle_svg(listing.kind, listing.color, listing.title)
