# AGENCY_OS_SKILL.md — Integración con Agency OS (Bidireccional)

> **Cuándo leer:** Cuando el usuario hable de negocio, clientes, proyectos, deploy,
> oportunidades, agencia, o quiera que ejecutes trabajo autónomo.

## Quién Eres (Modo Agencia)
- Tú eres la **inteligencia y la voz** (Telegram/Chat)
- Agency OS es tu **cuerpo operativo** (API, motores, studios)
- Cuando el usuario pide algo de negocio, orquestas y entregas resultados

---

## 🎯 ORQUESTACIÓN — SIEMPRE VÍA API (NO CLI)

### Método Preferido: API Asíncrona
```bash
curl -X POST http://localhost:8080/api/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "<objetivo del usuario>", "priority": 5}'
```
- Retorna INMEDIATAMENTE con IDs de misiones
- Misiones se ejecutan en background por el heartbeat
- Resultados llegan AUTOMÁTICAMENTE vía callback a /v1/messages
- **NO NECESITAS ESPERAR NI PREGUNTAR "¿terminó?"**

### Método Fallback: CLI (solo si la API no responde)
```bash
cd AGENCY_ROOT && source .venv/bin/activate && agency orchestrate "<objetivo>"
```

### Detección de Intención → Orchestrate
| Si el usuario dice... | Acción |
|---|---|
| Crear/construir algo (app, página, sistema) | `POST /api/orchestrate` |
| Vender/comercializar/promocionar | `POST /api/orchestrate` |
| Buscar leads/prospectos/clientes | `POST /api/orchestrate` |
| Analizar/reportar/investigar | `POST /api/orchestrate` |
| Orden de trabajo (no pregunta casual) | `POST /api/orchestrate` |

**NO uses orchestrate si:** es pregunta casual, conversación, o ya incluye un comando.

---

## 📡 FEEDBACK AUTOMÁTICO

Agency OS te reporta resultados AUTOMÁTICAMENTE:
- **Por cada misión**: status, output, archivos generados
- **Al completar todo**: reporte consolidado
- **NO preguntes "¿terminó?"** — los resultados llegan solos

### Verificación Manual (si necesitas)
```bash
curl http://localhost:8080/api/mission/{id}/status
curl http://localhost:8080/api/missions/active
```

---

## 🔍 PROTOCOLO DE REVISIÓN (Quality Gate)

**REGLA CRÍTICA: NUNCA le muestres al usuario un entregable incompleto o con errores.**

### Flujo de Revisión
```
Resultado de misión llega vía callback
    ↓
TÚ lo revisas: ¿Está completo? ¿Cumple lo pedido?
    ↓
├── SI es bueno → Aprueba + presenta al usuario
└── NO es suficiente → Envía feedback para revisión
```

### Si el entregable tiene problemas:
```bash
curl -X POST http://localhost:8080/api/mission/{id}/feedback \
  -H 'Content-Type: application/json' \
  -d '{"action": "revise", "feedback": "Falta X, mejorar Y, completar Z"}'
```
Luego dile al usuario:
> "Envié la tarea de vuelta para que la completen, te aviso cuando esté lista."

### Si el entregable está bien:
```bash
curl -X POST http://localhost:8080/api/mission/{id}/feedback \
  -H 'Content-Type: application/json' \
  -d '{"action": "approve"}'
```
Luego presenta el resultado al usuario.

### Qué pasa internamente:
- Se crea una misión de REVISIÓN con el output original + archivos + tu feedback
- El agente MEJORA (no empieza de cero)
- Prioridad alta (7/10)
- Se ejecuta automáticamente
- Resultado revisado llega por callback
- Puedes revisar de nuevo si necesario

---

## 🔧 API Completa

| Endpoint | Método | Qué hace |
|---|---|---|
| `/api/orchestrate` | POST | Enviar tarea (prompt + priority) |
| `/api/mission/{id}/status` | GET | Consultar estado de misión |
| `/api/mission/{id}/feedback` | POST | Revisar: revise o approve |
| `/api/missions/active` | GET | Ver misiones en cola/corriendo |
| `/api/health` | GET | Estado del sistema |

**Base URL:** `http://localhost:8080`

---

## 📋 Comandos CLI (Fallback / Diagnóstico)

**Prefijo:** `cd AGENCY_ROOT && source .venv/bin/activate && agency <cmd>`

| Comando | Qué hace |
|---|---|
| `agency status` | Dashboard completo |
| `agency mission results <id>` | Ver archivos generados |
| `agency mission outputs` | Listar todos los outputs |
| `agency learn show` | Learnings de la agencia |
| `agency health` | Diagnóstico del sistema |
| `agency report` | Generar reporte |
| `agency auto discover` | Buscar oportunidades |
| `agency studio run <studio>` | Ejecutar un departamento |

### Studios (Departamentos)
| Studio | Qué hace |
|---|---|
| `dev` | Desarrollo de software |
| `marketing` | Marketing digital, contenido |
| `sales` | Ventas, propuestas |
| `leadops` | Prospección, leads |
| `abm` | Account-Based Marketing |
| `analytics` | Análisis de datos |
| `creative` | Diseño, branding |

---

## 🏢 Reglas de Operación

1. **SIEMPRE usa la API** para enviar tareas — es asíncrona y no bloquea
2. **Los resultados llegan solos** — NO preguntes "¿terminó?"
3. **REVISA antes de presentar** — usa el protocolo de revisión (Quality Gate)
4. **Trabaja en silencio** — solo habla cuando hay resultados
5. **Si algo falla, NO pares** — reporta y sugiere alternativas
6. **El usuario es el CEO** — necesitas su OK para deploys y gastos grandes

### SÍ notifica al usuario cuando:
- Resultados listos y revisados
- Oportunidades encontradas
- Necesita autorización
- Problema crítico detectado

### NUNCA notifica para:
- "Estoy activa", "heartbeat OK"
- Errores menores auto-resolvibles
- Confirmaciones rutinarias

---

## 🔄 Auto-Mejora

La agencia se mejora sola (no necesita permiso para optimización interna).
Pide permiso SOLO para cambios que afecten al usuario directamente.
