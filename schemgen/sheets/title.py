"""Титульный лист документа."""
from __future__ import annotations

from ..model import Project
from ..pen import Pen, wrap

CENTER_X = 616.5


def title_page(pr: Project):
    def draw(p: Pen) -> None:
        size = 29.8
        lines = wrap(pr.system_name, 640, size)
        y = 213.5
        for ln in lines:
            p.text(CENTER_X, y, ln, size, "center")
            y += 35.8
        p.text(98.7, 480.5, "Исполнитель:", size)
        p.text(306.1, 483.3, pr.contractor, size, max_width=860)
        p.text(98.7, 551.3, "Заказчик:", size)
        p.text(307.6, 551.3, pr.customer, size, max_width=860)
    return draw
