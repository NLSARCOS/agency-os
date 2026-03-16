# Agents and Models — Agency OS

## Filosofía
Agency OS no depende de un solo modelo. Funciona como **mesa de especialistas**.

## Roles lógicos
### Orchestrator
- responsable: Botsi
- decide prioridad, ruta, fallback y entregable

### Architect
- problemas complejos, diseño de sistema, decisiones de estructura
- preferencia: modelos fuertes (Claude/Codex/Gemini)

### Builder
- implementación práctica, scripts, glue code
- preferencia: Codex / Kimi / MiniMax según costo-velocidad

### QA
- validación, consistencia, checklists, humo vs realidad
- preferencia: modelos rápidos y sistemáticos

### Scout
- descubrimiento de fuentes, ideas, research dirigido
- preferencia: OpenRouter free + Kimi + búsqueda directa

### LeadOps
- scraping, normalización, dedupe, scoring
- preferencia: scripts + modelos rápidos para clasificación

### Closer
- empaquetado, outreach, mensajes, secuencias
- preferencia: marketing-strategy-pmm + modelos de copy

## Modelos actuales operables
### OpenClaw configurados
- Ollama: `kimi-k2.5:cloud`, `minimax-m2.5:cloud`
- OpenRouter free: `arcee-ai/trinity-mini:free`, `stepfun/step-3.5-flash:free`, `nvidia/nemotron-3-super-120b-a12b:free`, etc.
- otros modelos configurados en OpenClaw según host

## Routing sugerido
- exploración / brainstorming ligero -> OpenRouter free / Kimi
- limpieza / clasificación -> MiniMax / Kimi
- arquitectura / debugging crítico -> Claude/Codex/Gemini
- copy / estrategia -> marketing-strategy-pmm + OpenRouter free

## Regla
Ningún modelo es “dueño” del sistema. El kernel decide cuál usar por costo, velocidad y calidad esperada.
