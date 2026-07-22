from __future__ import annotations

import math

from mesa import Model
from mesa.datacollection import DataCollector
from mesa.space import MultiGrid, PropertyLayer

from .agents import YouthAgent
from .config import (
    AFTER_SCHOOL_HOURS,
    DEFAULT_MAX_TICKS,
    DEFAULT_SEED,
    DEFAULT_YOUTH_COUNT,
    EVENING_HOURS,
    FAMILY_INFLUENCE_LOWER_GATE,
    FAMILY_INFLUENCE_UPPER_GATE,
    HOME_Y_MAX,
    HOME_Y_MIN,
    INDIVIDUAL_FACTOR_STDDEV,
    NEIGHBORHOOD_Y_MAX,
    NEIGHBORHOOD_Y_MIN,
    PARAMETER_SPECS,
    PATCH_OPPORTUNITY_MAX,
    PATCH_OPPORTUNITY_MIN,
    PIPELINE_STAGE_ORDER,
    PROBABILITY_DELTA,
    PRO_OPP_LAYER_NAME,
    REGION_CODES,
    REGION_LAYER_NAME,
    RISK_OPP_LAYER_NAME,
    SCHOOL_HOURS,
    SCHOOL_Y_MAX,
    SCHOOL_Y_MIN,
    TALLY_INCREMENT,
    WORLD_BOUNDS,
    YOUTH_COLORS,
    YOUTH_FACTOR_MAX,
    YOUTH_FACTOR_MIN,
    YOUTH_TURN_PROBABILITY,
    grid_to_netlogo,
    netlogo_to_grid,
    world_dimensions,
)
from .randomness import bounded_exponential, bounded_normal


class YaTASERPSModel(Model):
    def __init__(
        self,
        *,
        risk_level: int = PARAMETER_SPECS["risk_level"].default,
        promotive_level: int = PARAMETER_SPECS["promotive_level"].default,
        schools_risk: int = PARAMETER_SPECS["schools_risk"].default,
        schools_promotive: int = PARAMETER_SPECS["schools_promotive"].default,
        neighborhood_risk: int = PARAMETER_SPECS["neighborhood_risk"].default,
        neighborhood_promotive: int = PARAMETER_SPECS["neighborhood_promotive"].default,
        num_youth: int = DEFAULT_YOUTH_COUNT,
        max_ticks: int = DEFAULT_MAX_TICKS,
        seed: int | None = DEFAULT_SEED,
        collect_time_series: bool = True,
        record_pipeline_trace: bool = True,
        refresh_visuals: bool = True,
    ) -> None:
        super().__init__(seed=seed)

        self.seed_value = seed
        self.risk_level = risk_level
        self.promotive_level = promotive_level
        self.schools_risk = schools_risk
        self.schools_promotive = schools_promotive
        self.neighborhood_risk = neighborhood_risk
        self.neighborhood_promotive = neighborhood_promotive
        self.num_youth = num_youth
        self.max_ticks = max_ticks
        self.collect_time_series = collect_time_series
        self.record_pipeline_trace = record_pipeline_trace
        self.refresh_visuals = refresh_visuals

        self.world_bounds = WORLD_BOUNDS
        self.world_size = world_dimensions()
        self.grid = self._build_grid()
        self.region_positions = self._build_region_positions()
        self.region_position_sets = {
            band: set(positions) for band, positions in self.region_positions.items()
        }

        self.day = 0
        self.current_stage = "ready"
        self.current_substep = 0
        self.pipeline_stage_order = PIPELINE_STAGE_ORDER
        self.last_pipeline_trace: list[str] = []

        self._populate_region_layer()
        self._populate_setup_layers()
        self._create_agents()

        self.datacollector: DataCollector | None = None
        if self.collect_time_series:
            self.datacollector = DataCollector(
                model_reporters={
                    "Percent Antisocial": lambda m: m.percent_antisocial_share,
                    "Percent Prosocial": lambda m: m.percent_prosocial_share,
                    # The literal v1.0.0 NetLogo plot also tracks ties as a third pen.
                    "Percent Equal": lambda m: m.percent_equal_share,
                }
            )
            self.datacollector.collect(self)

    @property
    def youths(self) -> list[YouthAgent]:
        return list(self.agents_by_type.get(YouthAgent, []))

    @property
    def mean_prosocial(self) -> float:
        return self._mean_for_youths("prosocial")

    @property
    def mean_antisocial(self) -> float:
        return self._mean_for_youths("antisocial")

    @property
    def mean_family_risk(self) -> float:
        return self._mean_for_youths("family_risk")

    @property
    def mean_family_pro(self) -> float:
        return self._mean_for_youths("family_pro")

    @property
    def mean_individual_risk(self) -> float:
        return self._mean_for_youths("individual_risk")

    @property
    def mean_individual_pro(self) -> float:
        return self._mean_for_youths("individual_pro")

    @property
    def mean_school_risk_opp(self) -> float:
        return self._mean_for_band_layer("school", RISK_OPP_LAYER_NAME)

    @property
    def mean_school_pro_opp(self) -> float:
        return self._mean_for_band_layer("school", PRO_OPP_LAYER_NAME)

    @property
    def mean_neighborhood_risk_opp(self) -> float:
        return self._mean_for_band_layer("neighborhood", RISK_OPP_LAYER_NAME)

    @property
    def mean_neighborhood_pro_opp(self) -> float:
        return self._mean_for_band_layer("neighborhood", PRO_OPP_LAYER_NAME)

    @property
    def youths_at_home_count(self) -> int:
        return self._count_youths_in_band("home")

    @property
    def youths_in_neighborhood_count(self) -> int:
        return self._count_youths_in_band("neighborhood")

    @property
    def youths_at_school_count(self) -> int:
        return self._count_youths_in_band("school")

    @property
    def percent_antisocial_share(self) -> float:
        youths = self.youths
        if not youths:
            return 0.0
        count = sum(agent.antisocial > agent.prosocial for agent in youths)
        return count / len(youths)

    @property
    def percent_prosocial_share(self) -> float:
        youths = self.youths
        if not youths:
            return 0.0
        count = sum(agent.prosocial > agent.antisocial for agent in youths)
        return count / len(youths)

    @property
    def percent_equal_share(self) -> float:
        youths = self.youths
        if not youths:
            return 0.0
        count = sum(agent.prosocial == agent.antisocial for agent in youths)
        return count / len(youths)

    @property
    def current_stage_label(self) -> str:
        if self.current_substep:
            return f"{self.current_stage} ({self.current_substep})"
        return self.current_stage

    @property
    def pipeline_definition_text(self) -> str:
        return " -> ".join(
            (
                f"school ({SCHOOL_HOURS})",
                f"after_school ({AFTER_SCHOOL_HOURS})",
                f"evening ({EVENING_HOURS})",
                "step_day",
            )
        )

    @property
    def last_pipeline_trace_text(self) -> str:
        if not self.last_pipeline_trace:
            return "not stepped yet"
        return " -> ".join(self.last_pipeline_trace)

    def step(self) -> None:
        if not self.running:
            return

        self.last_pipeline_trace = []
        self.school()
        self.after_school()
        self.evening()
        self.step_day()

    def school(self) -> None:
        self._move_agents_to_band(self.youths, "school")
        for hour in range(1, SCHOOL_HOURS + 1):
            self._set_stage("school", hour)
            for youth in self.youths:
                if youth.location_band == "school":
                    self._youth_leaves_early(youth)
                if youth.location_band == "neighborhood":
                    self._youth_in_neighborhood(youth)
        for youth in self.youths:
            self._resolve_school_day_outcome(youth)

    def after_school(self) -> None:
        for hour in range(1, AFTER_SCHOOL_HOURS + 1):
            self._set_stage("after_school", hour)
            for youth in self.youths:
                self._youth_in_neighborhood(youth)

    def evening(self) -> None:
        for hour in range(1, EVENING_HOURS + 1):
            self._set_stage("evening", hour)
            for youth in self.youths:
                if youth.location_band == "home":
                    self._youth_at_home(youth)
                else:
                    self._move_agent_to_band(youth, "home")
        if self.refresh_visuals:
            self._refresh_all_youth_visuals()

    def step_day(self) -> None:
        self._set_stage("step_day", 1)
        self.day = self.steps
        if self.datacollector is not None:
            self.datacollector.collect(self)
        if self.day >= self.max_ticks:
            self.running = False

    def _build_grid(self) -> MultiGrid:
        width, height = self.world_size
        region_layer = PropertyLayer(REGION_LAYER_NAME, width, height, -1, dtype=int)
        risk_opp_layer = PropertyLayer(
            RISK_OPP_LAYER_NAME, width, height, 0.0, dtype=float
        )
        pro_opp_layer = PropertyLayer(
            PRO_OPP_LAYER_NAME, width, height, 0.0, dtype=float
        )
        return MultiGrid(
            width=width,
            height=height,
            torus=False,
            property_layers=[region_layer, risk_opp_layer, pro_opp_layer],
        )

    def _build_region_positions(self) -> dict[str, list[tuple[int, int]]]:
        positions = {"home": [], "neighborhood": [], "school": []}
        for x in range(WORLD_BOUNDS.min_x, WORLD_BOUNDS.max_x + 1):
            for y in range(WORLD_BOUNDS.min_y, WORLD_BOUNDS.max_y + 1):
                if HOME_Y_MIN <= y <= HOME_Y_MAX:
                    band = "home"
                elif SCHOOL_Y_MIN <= y <= SCHOOL_Y_MAX:
                    band = "school"
                elif NEIGHBORHOOD_Y_MIN <= y <= NEIGHBORHOOD_Y_MAX:
                    band = "neighborhood"
                else:
                    continue
                positions[band].append(netlogo_to_grid(x, y))
        return positions

    def _populate_region_layer(self) -> None:
        region_layer = self.grid.properties[REGION_LAYER_NAME]
        for band, positions in self.region_positions.items():
            code = REGION_CODES[band]
            for x, y in positions:
                region_layer.data[x, y] = code

    def _populate_setup_layers(self) -> None:
        self._set_band_layer_values("home", RISK_OPP_LAYER_NAME, 1.0)
        self._set_band_layer_values("home", PRO_OPP_LAYER_NAME, 1.0)
        self._initialize_random_band_layer(
            "school", RISK_OPP_LAYER_NAME, self.schools_risk
        )
        self._initialize_random_band_layer(
            "school", PRO_OPP_LAYER_NAME, self.schools_promotive
        )
        self._initialize_random_band_layer(
            "neighborhood", RISK_OPP_LAYER_NAME, self.neighborhood_risk
        )
        self._initialize_random_band_layer(
            "neighborhood", PRO_OPP_LAYER_NAME, self.neighborhood_promotive
        )

    def _set_band_layer_values(self, band: str, layer_name: str, value: float) -> None:
        layer = self.grid.properties[layer_name]
        for x, y in self.region_positions[band]:
            layer.data[x, y] = value

    def _initialize_random_band_layer(
        self,
        band: str,
        layer_name: str,
        mean_percent: int,
    ) -> None:
        layer = self.grid.properties[layer_name]
        for x, y in self.region_positions[band]:
            layer.data[x, y] = bounded_exponential(
                self.random,
                mean_percent / 100,
                PATCH_OPPORTUNITY_MIN,
                PATCH_OPPORTUNITY_MAX,
            )

    def _create_agents(self) -> None:
        for _ in range(self.num_youth):
            agent = YouthAgent(self)
            self._initialize_youth(agent)
            self._move_agent_to_band(agent, "home")

    def _initialize_youth(self, agent: YouthAgent) -> None:
        agent.family_risk = bounded_exponential(
            self.random,
            self.risk_level / 100,
            YOUTH_FACTOR_MIN,
            YOUTH_FACTOR_MAX,
        )
        agent.family_pro = bounded_exponential(
            self.random,
            self.promotive_level / 100,
            YOUTH_FACTOR_MIN,
            YOUTH_FACTOR_MAX,
        )
        agent.individual_risk = bounded_normal(
            self.random,
            agent.family_risk,
            INDIVIDUAL_FACTOR_STDDEV,
            YOUTH_FACTOR_MIN,
            YOUTH_FACTOR_MAX,
        )
        agent.individual_pro = bounded_normal(
            self.random,
            agent.family_pro,
            INDIVIDUAL_FACTOR_STDDEV,
            YOUTH_FACTOR_MIN,
            YOUTH_FACTOR_MAX,
        )
        agent.prosocial = 0.0
        agent.antisocial = 0.0
        agent.visual_color = YOUTH_COLORS["setup"]

    def _move_agents_to_band(self, agents: list[YouthAgent], band: str) -> None:
        for agent in agents:
            self._move_agent_to_band(agent, band)

    def _move_agent_to_band(self, agent: YouthAgent, band: str) -> None:
        position = self.random.choice(self.region_positions[band])
        xcor, ycor = grid_to_netlogo(*position)
        self._place_agent(
            agent,
            position,
            band=band,
            xcor=float(xcor),
            ycor=float(ycor),
        )

    def _place_agent(
        self,
        agent: YouthAgent,
        position: tuple[int, int],
        *,
        band: str,
        xcor: float,
        ycor: float,
    ) -> None:
        current_pos = getattr(agent, "pos", None)
        if current_pos is not None:
            self.grid.move_agent(agent, position)
        else:
            self.grid.place_agent(agent, position)
        agent.xcor = xcor
        agent.ycor = ycor
        agent.location_band = band

    def _youth_leaves_early(self, youth: YouthAgent) -> None:
        if youth.location_band != "school":
            return
        if self.random.random() < self._layer_value_at_agent(youth, PRO_OPP_LAYER_NAME):
            self._move_agent_to_band(youth, "school")
        elif self.random.random() < self._layer_value_at_agent(
            youth, RISK_OPP_LAYER_NAME
        ):
            if self.random.random() < youth.individual_risk:
                self._move_agent_to_band(youth, "neighborhood")

    def _resolve_school_day_outcome(self, youth: YouthAgent) -> None:
        if youth.location_band == "school":
            if self.random.random() < self._layer_value_at_agent(
                youth, PRO_OPP_LAYER_NAME
            ):
                youth.prosocial += TALLY_INCREMENT
            self._move_agent_to_band(youth, "neighborhood")
        elif youth.location_band == "neighborhood":
            if self.random.random() < self._layer_value_at_agent(
                youth, RISK_OPP_LAYER_NAME
            ):
                youth.antisocial += TALLY_INCREMENT

    def _youth_in_neighborhood(self, youth: YouthAgent) -> None:
        self._move_youth_within_neighborhood(youth)
        if youth.location_band != "neighborhood" or youth.pos is None:
            return

        if self.random.random() < self._layer_value_at_agent(youth, PRO_OPP_LAYER_NAME):
            self._youth_meets_positive_influence(youth)
        elif self.random.random() < self._layer_value_at_agent(
            youth, RISK_OPP_LAYER_NAME
        ):
            self._youth_meets_negative_influence(youth)

    def _move_youth_within_neighborhood(self, youth: YouthAgent) -> None:
        if youth.location_band != "neighborhood" or youth.pos is None:
            return

        if self.random.random() < YOUTH_TURN_PROBABILITY:
            youth.heading_degrees = self.random.randrange(360)

        next_xcor, next_ycor = self._point_ahead(
            youth.xcor,
            youth.ycor,
            youth.heading_degrees,
            distance=1,
        )
        next_position = self._patch_from_point(next_xcor, next_ycor)
        if next_position is None:
            return
        if not self._is_position_in_band(next_position, "neighborhood"):
            return

        self._place_agent(
            youth,
            next_position,
            band="neighborhood",
            xcor=next_xcor,
            ycor=next_ycor,
        )

    def _youth_meets_positive_influence(self, youth: YouthAgent) -> None:
        if self.random.random() < youth.individual_pro:
            youth.prosocial += TALLY_INCREMENT

    def _youth_meets_negative_influence(self, youth: YouthAgent) -> None:
        if self.random.random() < youth.individual_risk:
            youth.antisocial += TALLY_INCREMENT

    def _youth_at_home(self, youth: YouthAgent) -> None:
        if youth.location_band != "home":
            return

        if (
            self.random.random() < youth.family_risk
            and youth.individual_risk < FAMILY_INFLUENCE_UPPER_GATE
            and youth.individual_risk > youth.individual_pro
        ):
            youth.individual_risk = self._clamp_probability(
                youth.individual_risk + PROBABILITY_DELTA
            )
        elif (
            youth.individual_risk > FAMILY_INFLUENCE_LOWER_GATE
            and youth.individual_risk < youth.individual_pro
        ):
            youth.individual_risk = self._clamp_probability(
                youth.individual_risk - PROBABILITY_DELTA
            )

        if (
            self.random.random() < youth.family_pro
            and youth.individual_pro < FAMILY_INFLUENCE_UPPER_GATE
            and youth.individual_pro > youth.individual_risk
        ):
            youth.individual_pro = self._clamp_probability(
                youth.individual_pro + PROBABILITY_DELTA
            )
        elif (
            youth.individual_pro > FAMILY_INFLUENCE_LOWER_GATE
            and youth.individual_pro < youth.individual_risk
        ):
            youth.individual_pro = self._clamp_probability(
                youth.individual_pro - PROBABILITY_DELTA
            )

    def _point_ahead(
        self,
        xcor: float,
        ycor: float,
        heading_degrees: int,
        *,
        distance: int,
    ) -> tuple[float, float]:
        radians = math.radians(heading_degrees)
        dx = math.sin(radians)
        dy = math.cos(radians)
        return xcor + dx * distance, ycor + dy * distance

    def _patch_from_point(self, xcor: float, ycor: float) -> tuple[int, int] | None:
        patch_x = self._netlogo_round(xcor)
        patch_y = self._netlogo_round(ycor)
        if not (
            WORLD_BOUNDS.min_x <= patch_x <= WORLD_BOUNDS.max_x
            and WORLD_BOUNDS.min_y <= patch_y <= WORLD_BOUNDS.max_y
        ):
            return None
        return netlogo_to_grid(patch_x, patch_y)

    def _netlogo_round(self, value: float) -> int:
        if value >= 0:
            return int(math.floor(value + 0.5))
        return int(math.ceil(value - 0.5))

    def _is_valid_position(self, position: tuple[int, int]) -> bool:
        x, y = position
        width, height = self.world_size
        return 0 <= x < width and 0 <= y < height

    def _is_position_in_band(self, position: tuple[int, int], band: str) -> bool:
        return position in self.region_position_sets[band]

    def _layer_value_at_agent(self, agent: YouthAgent, layer_name: str) -> float:
        if agent.pos is None:
            raise ValueError(
                "Agent must be placed before reading a property layer value."
            )
        layer = self.grid.properties[layer_name]
        x, y = agent.pos
        return float(layer.data[x, y])

    def _refresh_all_youth_visuals(self) -> None:
        for youth in self.youths:
            self._refresh_youth_visual(youth)

    def _set_stage(self, stage: str, substep: int) -> None:
        self.current_stage = stage
        self.current_substep = substep
        if self.record_pipeline_trace:
            self.last_pipeline_trace.append(f"{stage}:{substep}")

    def _mean_for_youths(self, attribute_name: str) -> float:
        youths = self.youths
        if not youths:
            return 0.0
        return sum(getattr(agent, attribute_name) for agent in youths) / len(youths)

    def _mean_for_band_layer(self, band: str, layer_name: str) -> float:
        positions = self.region_positions[band]
        if not positions:
            return 0.0
        layer = self.grid.properties[layer_name]
        total = sum(layer.data[x, y] for x, y in positions)
        return float(total) / len(positions)

    def youth_attribute_values(self, attribute_name: str) -> list[float]:
        return [float(getattr(youth, attribute_name)) for youth in self.youths]

    def band_layer_values(self, band: str, layer_name: str) -> list[float]:
        layer = self.grid.properties[layer_name]
        return [float(layer.data[x, y]) for x, y in self.region_positions[band]]

    def _count_youths_in_band(self, band: str) -> int:
        return sum(youth.location_band == band for youth in self.youths)

    def _clamp_probability(self, value: float) -> float:
        return min(max(value, YOUTH_FACTOR_MIN), YOUTH_FACTOR_MAX)

    def _refresh_youth_visual(self, youth: YouthAgent) -> None:
        if youth.antisocial > youth.prosocial:
            youth.visual_color = YOUTH_COLORS["antisocial"]
        else:
            youth.visual_color = YOUTH_COLORS["prosocial"]
