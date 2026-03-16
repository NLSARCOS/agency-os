# Blockers

## Técnicos
- Algunos skills de ClawHub fallan por rate limit o banderas de seguridad.
- `agents_list` externo sigue limitado; se resuelve con roles internos y subagentes puntuales.

## Operativos
- Parte de los pipelines sigue viviendo en `agency-v1`; falta migración completa a `agency-os`.

## Estrategia
- crear skills locales
- usar múltiples modelos (OpenRouter/Ollama/premium)
- mover el core a `agency-os`
