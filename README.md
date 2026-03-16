# 🫀 Agency OS v5.0

> Sistema Operativo autónomo para agencias de IA — desarrollo, marketing, ventas, prospección, ABM, analytics y creatividad.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## ¿Qué es Agency OS?

Una **agencia de IA que opera 24/7** de forma autónoma. Busca oportunidades de negocio, ejecuta campañas de marketing, genera propuestas de venta, despliega código y se auto-mejora — todo sin intervención humana (salvo aprobaciones críticas).

Se integra con [OpenClaw](https://openclaw.ai) como cerebro conversacional (Telegram, CLI) y usa modelos de IA via OpenRouter, OpenAI, Anthropic u Ollama.

## Arquitectura

```
┌─────────────────────────────────────────────────┐
│  OpenClaw (Telegram/CLI)  ←→  Agency OS Kernel  │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Heartbeat│  │ Model    │  │ Notifier │       │
│  │ (24/7)   │  │ Router   │  │ (TG/File)│       │
│  └────┬─────┘  └────┬─────┘  └──────────┘       │
│       │              │                            │
│  ┌────▼──────────────▼────────────────────┐      │
│  │           Studios (Departamentos)       │      │
│  │  dev · marketing · sales · leadops     │      │
│  │  abm · analytics · creative            │      │
│  └────────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘
```

## Instalación

### Requisitos
- Python 3.12+
- [OpenClaw](https://openclaw.ai) (recomendado, no obligatorio)
- API key de OpenRouter (gratis) o cualquier proveedor de IA

### Setup automático

```bash
git clone https://github.com/NLSARCOS/agency-os.git
cd agency-os
bash install/setup.sh
```

El setup detecta automáticamente:
- 🐙 OpenClaw (gateway + Telegram bot + modelos)
- 🦙 Ollama (modelos locales)
- 🖥️ LM Studio (modelos locales)
- ☁️ API keys (OpenRouter, OpenAI, Anthropic, Gemini)
- 📱 Telegram (bot token + chat ID desde OpenClaw)

Si OpenClaw está instalado, **integra Agency OS directamente** en su identidad (SOUL.md) para comunicación bidireccional via Telegram.

## Uso

### Iniciar la agencia (24/7)
```bash
source .venv/bin/activate
agency start --daemon
```

### Comandos principales
```bash
agency status              # Dashboard completo
agency auto discover       # Buscar oportunidades de negocio
agency auto evolve         # Auto-mejorar el código
agency studio run dev      # Ejecutar studio de desarrollo
agency studio run marketing # Ejecutar marketing
agency report              # Generar reporte
agency health              # Diagnóstico del sistema
agency mission list        # Ver misiones activas
agency events              # Ver eventos recientes
```

### Estudios en paralelo
```bash
agency studio run dev &
agency studio run marketing &
agency studio run leadops &
wait
agency report
```

## Integración con OpenClaw

Agency OS se integra **bidireccionalmente** con OpenClaw:

| Dirección | Cómo funciona |
|---|---|
| **Tú → Agencia** | Escribes al bot de Telegram → OpenClaw ejecuta comandos de Agency OS |
| **Agencia → Tú** | Heartbeat encuentra oportunidades → te notifica por Telegram |

La agencia solo te escribe cuando:
- ✅ Encuentra oportunidades de negocio
- ✅ Completa tareas importantes
- ✅ Necesita tu autorización
- ❌ Nunca spam de "estoy activa"

## Modelos de IA

Por defecto usa modelos **gratuitos** de OpenRouter:

| Modelo | Contexto | Uso |
|---|---|---|
| Hunter Alpha | 1M tokens | Conversación, análisis |
| Qwen3 Coder | 262K tokens | Desarrollo, código |
| Nemotron 3 Super 120B | 262K tokens | Analytics, razonamiento |
| Healer Alpha | 262K tokens | Fallback general |

Si tienes API keys de OpenAI, Anthropic o Gemini, se usan como fallback premium.

## Configuración

### Variables de entorno (`.env`)

```bash
# Idioma de la agencia (en/es)
AGENCY_LANGUAGE=es

# OpenRouter (gratis)
OPENROUTER_API_KEY=sk-or-...

# Telegram (auto-detectado desde OpenClaw)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Opcional (premium)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

### Modelos (`configs/models.yaml`)

Cada studio tiene su pool de modelos con fallback automático. Puedes personalizar qué modelos usa cada departamento.

## Estructura del proyecto

```
agency-os/
├── kernel/           # Motores core
│   ├── heartbeat.py  # Daemon 24/7 (hustle + evolve)
│   ├── model_router.py # Router multi-proveedor con fallback
│   ├── notifier.py   # Telegram, file, console, OpenClaw
│   ├── config.py     # Configuración centralizada
│   └── openclaw_bridge.py # Integración con OpenClaw
├── studios/          # Departamentos
│   ├── dev/          # Desarrollo de software
│   ├── marketing/    # Marketing digital
│   ├── sales/        # Ventas
│   ├── leadops/      # Generación de leads
│   ├── abm/          # Account-Based Marketing
│   ├── analytics/    # Análisis de datos
│   └── creative/     # Diseño y creatividad
├── configs/          # models.yaml, routing.yaml
├── install/          # setup.sh + OpenClaw integration
├── data/             # SQLite (agency.db, heartbeat state)
├── tests/            # 44+ tests
└── .env              # Variables de entorno
```

## Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

## Licencia

MIT — úsalo, modifícalo, compártelo.
