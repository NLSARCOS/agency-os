# Model Routing — Agency OS

## Objetivo
Usar varios modelos según el tipo de trabajo para mantener Agency OS 24/7 con costo/velocidad/calidad controlados.

## Available pools
### Ollama / cloud
- kimi-k2.5:cloud
- minimax-m2.5:cloud

### OpenRouter free
- openrouter/arcee-ai/trinity-mini:free
- openrouter/stepfun/step-3.5-flash:free
- openrouter/nvidia/nemotron-3-super-120b-a12b:free
- openrouter/free
- openrouter/healer-alpha
- openrouter/hunter-alpha

### Premium/other (si están activos)
- Claude / Gemini / Codex

## Routing policy
- Research / scouting -> Kimi + OpenRouter free
- Classification / cleanup -> MiniMax + OpenRouter free
- Architecture / hard debugging -> Claude/Codex/Gemini
- Copy / marketing reasoning -> marketing-strategy-pmm + OpenRouter free
- Fallback -> siguiente modelo del pool

## Rule
Nunca depender de un solo modelo. Si uno falla o da peor rendimiento, cambiar al siguiente del pool.
