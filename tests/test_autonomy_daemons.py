import asyncio
import pytest
from kernel.heartbeat import AgencyHeartbeat, HeartbeatConfig
from kernel.skill_evaluator import SkillEvaluator


def test_heartbeat_initialization():
    """Test that heartbeat initializes correctly."""
    hb = AgencyHeartbeat(config=HeartbeatConfig(tick_interval=1))
    assert not hb.is_running
    assert hb.config.tick_interval == 1
    assert hb.config.hustle_interval_hours == 12
    assert hb.config.evolution_interval_hours == 24


@pytest.mark.asyncio
async def test_heartbeat_tick_logic():
    """Test the internal tick logic simulates correctly."""
    hb = AgencyHeartbeat(config=HeartbeatConfig(tick_interval=1))
    
    # We shouldn't actually trigger external API calls here, 
    # but we can verify the tick advances time delta tests.
    hb.last_hustle = 0  # Force a hustle
    
    # Just run a single tick to ensure no syntax errors and state updates
    await hb._tick()
    assert hb.last_hustle > 0


def test_skill_evaluator_tracking():
    """Test that the skill evaluator correctly tracks failures and triggers evaluation."""
    evaluator = SkillEvaluator()
    
    # Simulate robust success
    for _ in range(5):
        evaluator._on_phase_complete(type("MockEvent", (), {"payload": {"studio": "dev", "status": "completed"}})())
        
    perf = evaluator._performance.get("dev")
    assert perf is not None
    assert perf.total_runs == 5
    assert perf.failures == 0
    
    # Simulate continuous failure
    for _ in range(3):
        evaluator._on_phase_complete(type("MockEvent", (), {"payload": {"studio": "sales", "status": "failed"}})())
        
    perf_sales = evaluator._performance.get("sales")
    # Evaluating a studio with 3 failures triggers the reset/restructure logic
    # so failures should reset to 0 in our mock memory if evaluate_studio ran.
    # We just want to ensure it caught it safely.
    assert perf_sales is not None 
    assert perf_sales.failures == 0  # It was reset by the restructure trigger
    assert perf_sales.total_runs == 0
