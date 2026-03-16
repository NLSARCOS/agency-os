#!/usr/bin/env python3
"""
LeadOps Studio — Lead Generation Pipeline

Uses: .agent/agents/explorer-agent.md
Skills: systematic-debugging (for data analysis), python-patterns
"""
from __future__ import annotations

import csv
import hashlib
import json
from io import StringIO
from pathlib import Path
from typing import Any

from studios.base_studio import BaseStudio


class Studio(BaseStudio):
    name = "leadops"
    description = "Lead generation, scraping, enrichment, dedup, scoring"
    agent_ref = "explorer-agent"
    skills_refs = ["python-patterns", "systematic-debugging"]

    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        """Parse leadops task: detect operation type."""
        task_lower = task.lower()
        operation = "discovery"
        if any(w in task_lower for w in ["scrape", "scraping", "crawl"]):
            operation = "scraping"
        elif any(w in task_lower for w in ["enrich", "enrichment", "complete"]):
            operation = "enrichment"
        elif any(w in task_lower for w in ["dedupe", "dedup", "duplicate", "clean"]):
            operation = "dedup"
        elif any(w in task_lower for w in ["score", "scoring", "rank", "priority"]):
            operation = "scoring"
        elif any(w in task_lower for w in ["report", "summary", "status"]):
            operation = "reporting"

        # Extract target vertical/geography
        vertical = ""
        for v in ["médico", "medico", "medical", "doctor", "salud", "health",
                   "legal", "lawyer", "tech", "fintech", "saas", "ecommerce"]:
            if v in task_lower:
                vertical = v
                break

        geography = ""
        for g in ["ecuador", "colombia", "méxico", "mexico", "spain", "usa",
                   "latam", "chile", "perú", "peru", "argentina"]:
            if g in task_lower:
                geography = g
                break

        return {
            "task": task,
            "description": description,
            "operation": operation,
            "vertical": vertical,
            "geography": geography,
        }

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        """Create leadops execution plan."""
        operation = intake_result["operation"]

        steps = {
            "discovery": [
                "Define target ICP (Ideal Customer Profile)",
                "Identify data sources (directories, registries, APIs)",
                "Plan search queries and filters",
                "Set quantity and quality targets",
            ],
            "scraping": [
                "Configure target sources",
                "Extract raw lead data",
                "Parse and normalize fields",
                "Initial quality filter",
                "Save raw output",
            ],
            "enrichment": [
                "Load existing leads",
                "Cross-reference with additional sources",
                "Fill missing fields (email, phone, specialty)",
                "Validate enriched data",
                "Save enriched output",
            ],
            "dedup": [
                "Load lead dataset",
                "Generate dedup keys (email, name+city hash)",
                "Identify and remove duplicates",
                "Merge partial records",
                "Report dedup stats",
            ],
            "scoring": [
                "Load clean leads",
                "Apply scoring criteria (completeness, relevance, recency)",
                "Rank leads by score",
                "Segment into tiers (hot/warm/cold)",
                "Generate scored output",
            ],
            "reporting": [
                "Aggregate pipeline metrics",
                "Calculate conversion rates",
                "Identify bottlenecks",
                "Generate report",
            ],
        }

        return {
            **intake_result,
            "steps": steps.get(operation, steps["discovery"]),
        }

    def execute(self, plan: dict[str, Any], task_id: int | None = None) -> dict[str, Any]:
        """Execute leadops pipeline."""
        operation = plan["operation"]

        # For dedup and scoring, try to work with local CSV files
        if operation == "dedup":
            return self._execute_dedup(plan, task_id)
        elif operation == "scoring":
            return self._execute_scoring(plan, task_id)

        # For discovery/scraping/enrichment, use AI
        prompt = (
            f"## LeadOps Task — {operation.upper()}\n"
            f"**Task:** {plan['task']}\n"
            f"**Vertical:** {plan.get('vertical', 'General')}\n"
            f"**Geography:** {plan.get('geography', 'Global')}\n\n"
            f"## Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + f"\n\nExecute this {operation} operation. "
            f"Provide structured output with sources, data formats, and next actions."
        )

        output = self.ai_call(prompt, task_id=task_id)
        return {
            "output": output,
            "operation": operation,
            "kpis": [
                {"name": f"{operation}_executed", "value": 1, "unit": "count"},
            ],
        }

    def _execute_dedup(self, plan: dict, task_id: int | None) -> dict:
        """Local dedup operation on CSV files."""
        data_dir = self.cfg.root / "data"
        csv_files = list(data_dir.glob("*.csv")) if data_dir.exists() else []

        if not csv_files:
            return {
                "output": "No CSV files found in data/ directory. Upload leads first.",
                "operation": "dedup",
                "kpis": [{"name": "dedup_executed", "value": 0, "unit": "count"}],
            }

        total_raw = 0
        total_clean = 0
        for csv_file in csv_files:
            try:
                content = csv_file.read_text(encoding="utf-8", errors="replace")
                reader = csv.DictReader(StringIO(content))
                rows = list(reader)
                total_raw += len(rows)

                # Dedup by email or name hash
                seen = set()
                clean_rows = []
                for row in rows:
                    key = row.get("email", "").lower().strip()
                    if not key:
                        name = row.get("name", row.get("nombre", "")).lower().strip()
                        city = row.get("city", row.get("ciudad", "")).lower().strip()
                        key = hashlib.md5(f"{name}:{city}".encode()).hexdigest()
                    if key and key not in seen:
                        seen.add(key)
                        clean_rows.append(row)

                total_clean += len(clean_rows)

                # Save deduped file
                if clean_rows:
                    out_path = data_dir / f"{csv_file.stem}_deduped.csv"
                    with open(out_path, "w", encoding="utf-8", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=clean_rows[0].keys())
                        writer.writeheader()
                        writer.writerows(clean_rows)
            except Exception as e:
                self.state.log_event("dedup_error", str(e), source="leadops", level="warning")

        removed = total_raw - total_clean
        return {
            "output": (
                f"Dedup complete: {total_raw} raw → {total_clean} clean "
                f"({removed} duplicates removed, {removed/total_raw*100:.1f}% reduction)"
                if total_raw > 0 else "No records processed"
            ),
            "operation": "dedup",
            "kpis": [
                {"name": "raw_leads", "value": total_raw, "unit": "count"},
                {"name": "clean_leads", "value": total_clean, "unit": "count"},
                {"name": "duplicates_removed", "value": removed, "unit": "count"},
            ],
        }

    def _execute_scoring(self, plan: dict, task_id: int | None) -> dict:
        """Score leads based on data completeness and fields."""
        data_dir = self.cfg.root / "data"
        csv_files = list(data_dir.glob("*deduped*.csv")) or list(data_dir.glob("*.csv"))

        if not csv_files:
            return {
                "output": "No CSV files found. Run dedup first.",
                "operation": "scoring",
                "kpis": [],
            }

        total_scored = 0
        hot = warm = cold = 0

        for csv_file in csv_files[:1]:  # Process first file
            try:
                content = csv_file.read_text(encoding="utf-8", errors="replace")
                reader = csv.DictReader(StringIO(content))
                rows = list(reader)
                scored_rows = []

                for row in rows:
                    score = 0
                    if row.get("email"):
                        score += 30
                    if row.get("phone", row.get("telefono")):
                        score += 20
                    if row.get("name", row.get("nombre")):
                        score += 15
                    if row.get("city", row.get("ciudad")):
                        score += 10
                    if row.get("specialty", row.get("especialidad")):
                        score += 15
                    if row.get("website", row.get("url")):
                        score += 10

                    tier = "cold"
                    if score >= 70:
                        tier = "hot"
                        hot += 1
                    elif score >= 40:
                        tier = "warm"
                        warm += 1
                    else:
                        cold += 1

                    row["score"] = str(score)
                    row["tier"] = tier
                    scored_rows.append(row)
                    total_scored += 1

                # Save scored file
                if scored_rows:
                    out_path = data_dir / f"{csv_file.stem}_scored.csv"
                    with open(out_path, "w", encoding="utf-8", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=scored_rows[0].keys())
                        writer.writeheader()
                        writer.writerows(scored_rows)
            except Exception as e:
                self.state.log_event("scoring_error", str(e), source="leadops", level="warning")

        return {
            "output": (
                f"Scoring complete: {total_scored} leads scored — "
                f"🔥 Hot: {hot}, 🟡 Warm: {warm}, 🔵 Cold: {cold}"
            ),
            "operation": "scoring",
            "kpis": [
                {"name": "leads_scored", "value": total_scored, "unit": "count"},
                {"name": "hot_leads", "value": hot, "unit": "count"},
                {"name": "warm_leads", "value": warm, "unit": "count"},
                {"name": "cold_leads", "value": cold, "unit": "count"},
            ],
        }
