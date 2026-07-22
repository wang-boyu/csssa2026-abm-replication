from __future__ import annotations

from mesa import Agent

from .config import YOUTH_COLORS


class YouthAgent(Agent):
    def __init__(self, model):
        super().__init__(model)
        self.location_band = "home"
        self.heading_degrees = 0
        self.xcor = 0.0
        self.ycor = 0.0
        self.family_risk = 0.0
        self.family_pro = 0.0
        self.individual_risk = 0.0
        self.individual_pro = 0.0
        self.prosocial = 0.0
        self.antisocial = 0.0
        self.visual_color = YOUTH_COLORS["setup"]
        self.marker = "o"
        self.size = 36

    def step(self) -> None:
        return
