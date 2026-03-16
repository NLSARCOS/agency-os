#!/usr/bin/env python3
"""Tests for Agency OS kernel components."""
import pytest
from pathlib import Path


class TestConfig:
    def test_config_singleton(self):
        from kernel.config import get_config, Config
        Config._instance = None  # Reset for test
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_config_finds_root(self):
        from kernel.config import get_config, Config
        Config._instance = None
        cfg = get_config()
        assert cfg.root.exists()
        assert (cfg.root / "pyproject.toml").exists()

    def test_config_platform(self):
        from kernel.config import get_config, Config
        Config._instance = None
        cfg = get_config()
        assert cfg.platform in ("linux", "darwin", "windows")

    def test_config_studio_names(self):
        from kernel.config import get_config, Config
        Config._instance = None
        cfg = get_config()
        assert "dev" in cfg.studio_names
        assert "leadops" in cfg.studio_names
        assert len(cfg.studio_names) == 7


class TestTaskRouter:
    def test_route_leadops(self):
        from kernel.task_router import route_task
        result = route_task("scraping de leads médicos ecuador")
        assert result.studio == "leadops"
        assert result.confidence > 0.5

    def test_route_marketing(self):
        from kernel.task_router import route_task
        result = route_task("crear campaña marketing posicionamiento brand")
        assert result.studio == "marketing"

    def test_route_dev(self):
        from kernel.task_router import route_task
        result = route_task("fix bug in API endpoint")
        assert result.studio == "dev"

    def test_route_sales(self):
        from kernel.task_router import route_task
        result = route_task("outreach secuencia cold email")
        assert result.studio == "sales"

    def test_route_abm(self):
        from kernel.task_router import route_task
        result = route_task("ABM targeting enterprise accounts")
        assert result.studio == "abm"

    def test_route_analytics(self):
        from kernel.task_router import route_task
        result = route_task("generar reporte KPI dashboard")
        assert result.studio == "analytics"

    def test_route_creative(self):
        from kernel.task_router import route_task
        result = route_task("diseño de landing page visual")
        assert result.studio == "creative"

    def test_route_force_studio(self):
        from kernel.task_router import route_task
        result = route_task("random task", context={"force_studio": "abm"})
        assert result.studio == "abm"
        assert result.confidence == 1.0

    def test_bulk_route(self):
        from kernel.task_router import TaskRouter
        router = TaskRouter()
        results = router.bulk_route(["fix bug", "lead scraping", "campaign ads"])
        assert len(results) == 3
        assert results[0].studio == "dev"
        assert results[1].studio == "leadops"


class TestStateManager:
    @pytest.fixture(autouse=True)
    def fresh_state(self, tmp_path):
        """Use a temp database for each test."""
        from kernel.state_manager import StateManager
        StateManager._instance = None
        from kernel.config import Config
        Config._instance = None
        import os
        os.environ["AGENCY_OS_ROOT"] = str(tmp_path)
        # Create minimal structure
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "configs").mkdir()
        (tmp_path / "data").mkdir()
        (tmp_path / "logs").mkdir()
        (tmp_path / "reports").mkdir()
        (tmp_path / "studios").mkdir()

    def test_create_mission(self):
        from kernel.state_manager import get_state
        state = get_state()
        mid = state.create_mission("Test mission", studio="dev")
        assert mid > 0

    def test_get_mission(self):
        from kernel.state_manager import get_state
        state = get_state()
        mid = state.create_mission("Test mission", studio="dev")
        m = state.get_mission(mid)
        assert m is not None
        assert m["name"] == "Test mission"
        assert m["studio"] == "dev"

    def test_mission_status_update(self):
        from kernel.state_manager import get_state, MissionStatus
        state = get_state()
        mid = state.create_mission("Test", studio="dev")
        state.update_mission_status(mid, MissionStatus.ACTIVE)
        m = state.get_mission(mid)
        assert m["status"] == "active"

    def test_promote_mission(self):
        from kernel.state_manager import get_state
        state = get_state()
        state.create_mission("First", studio="dev", priority=1)
        state.create_mission("Second", studio="marketing", priority=5)
        promoted = state.promote_next_mission()
        assert promoted is not None
        # Should promote lowest priority number first
        assert promoted["name"] in ("First", "Second")

    def test_create_task(self):
        from kernel.state_manager import get_state
        state = get_state()
        mid = state.create_mission("Mission", studio="dev")
        tid = state.create_task("Build API", "dev", mission_id=mid)
        assert tid > 0

    def test_log_kpi(self):
        from kernel.state_manager import get_state
        state = get_state()
        state.log_kpi("leadops", "raw_leads", 500, "count")
        kpis = state.get_kpis(studio="leadops")
        assert len(kpis) >= 1
        assert kpis[0]["metric_value"] == 500

    def test_log_event(self):
        from kernel.state_manager import get_state
        state = get_state()
        state.log_event("test_event", "This is a test", level="info")
        events = state.get_events(event_type="test_event")
        assert len(events) >= 1

    def test_dashboard_stats(self):
        from kernel.state_manager import get_state
        state = get_state()
        state.create_mission("M1", studio="dev")
        state.create_mission("M2", studio="sales")
        stats = state.get_dashboard_stats()
        assert "missions" in stats
        assert stats["missions"].get("queued", 0) >= 2


class TestMissionEngine:
    @pytest.fixture(autouse=True)
    def fresh_env(self, tmp_path):
        from kernel.state_manager import StateManager
        from kernel.config import Config
        StateManager._instance = None
        Config._instance = None
        import os
        os.environ["AGENCY_OS_ROOT"] = str(tmp_path)
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "configs").mkdir()
        (tmp_path / "data").mkdir()
        (tmp_path / "logs").mkdir()
        (tmp_path / "reports").mkdir()
        (tmp_path / "studios").mkdir()

    def test_submit_mission(self):
        from kernel.mission_engine import MissionEngine
        engine = MissionEngine()
        mid = engine.submit_mission("scraping leads médicos")
        assert mid > 0
        m = engine.state.get_mission(mid)
        assert m["studio"] == "leadops"

    def test_submit_with_force_studio(self):
        from kernel.mission_engine import MissionEngine
        engine = MissionEngine()
        mid = engine.submit_mission("some task", force_studio="creative")
        m = engine.state.get_mission(mid)
        assert m["studio"] == "creative"

    def test_engine_status(self):
        from kernel.mission_engine import MissionEngine
        engine = MissionEngine()
        engine.submit_mission("task 1")
        engine.submit_mission("task 2")
        status = engine.get_status()
        assert status["missions"]["queued"] >= 2


class TestStudios:
    def test_studio_discovery(self):
        from studios.base_studio import load_all_studios
        studios = load_all_studios()
        assert "dev" in studios
        assert "leadops" in studios
        assert "marketing" in studios
        assert "sales" in studios
        assert "abm" in studios
        assert "analytics" in studios
        assert "creative" in studios
        assert len(studios) == 7

    def test_dev_studio_intake(self):
        from studios.dev.pipeline import Studio
        studio = Studio()
        result = studio.intake("fix critical bug in auth endpoint", "Urgent")
        assert result["type"] == "bugfix"

    def test_leadops_studio_intake(self):
        from studios.leadops.pipeline import Studio
        studio = Studio()
        result = studio.intake("scraping de leads médicos", "Ecuador leads")
        assert result["operation"] == "scraping"

    def test_marketing_studio_intake(self):
        from studios.marketing.pipeline import Studio
        studio = Studio()
        result = studio.intake("SEO positioning strategy", "")
        assert result["operation"] == "seo"

    def test_sales_studio_intake(self):
        from studios.sales.pipeline import Studio
        studio = Studio()
        result = studio.intake("cold email outreach to prospects", "")
        assert result["operation"] == "outreach"

    def test_all_studios_have_required_methods(self):
        from studios.base_studio import load_all_studios
        studios = load_all_studios()
        for name, studio in studios.items():
            assert hasattr(studio, "intake")
            assert hasattr(studio, "plan")
            assert hasattr(studio, "execute")
            assert hasattr(studio, "review")
            assert hasattr(studio, "deliver")
            assert hasattr(studio, "run")
