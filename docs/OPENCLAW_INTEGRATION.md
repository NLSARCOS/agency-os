# Agency OS + OpenClaw Integration

## Objetivo
Agency OS está diseñado para correr **encima de OpenClaw**. No reemplaza OpenClaw: lo usa como runtime, router de modelos, tooling layer y scheduler asistido.

## Dependencias clave de OpenClaw
- modelos configurados en `openclaw models list`
- skills locales en `workspace/skills/`
- cron/jobs vía shell del host
- subagentes cuando estén disponibles
- herramientas: exec, read, write, edit, browser, gh, etc.

## Principio operativo
1. OpenClaw provee runtime + herramientas.
2. Agency OS provee kernel + studios + jobs + políticas.
3. Los studios ejecutan tareas usando los modelos disponibles en OpenClaw.

## Modelos actuales previstos
- Claude / Gemini / Codex (si están activos)
- Ollama cloud/local: Kimi K2.5, MiniMax M2.5
- OpenRouter free: trinity-mini, step-3.5-flash, nemotron-3-super, y fallbacks configurados

## Portabilidad
El repo Agency OS debe poder clonar y bootstrapear en Linux/Mac siempre que:
- OpenClaw esté instalado
- variables API estén presentes
- cron o launchd esté configurado

## Flujo de instalación deseado
1. Instalar OpenClaw
2. Clonar repo `agencyos`
3. Ejecutar bootstrap (`install/install_linux.sh` o `install/install_mac.sh`)
4. Configurar proveedores/modelos
5. Activar jobs continuos
