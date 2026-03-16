# Autonomy Policy

1. Si una táctica no mejora KPI neto, cambiar táctica automáticamente.
2. Nunca reportar solo volumen bruto; siempre neto útil.
3. Si un bloque termina, seguir con el siguiente bloque sin esperar instrucción.
4. Si un job falla, reintentar una vez y luego fallback.
5. El sistema debe poder correr en Linux y Mac con bootstrap reproducible.
6. Agency OS tiene prioridad operativa principal; tareas puntuales no deben romper el estado del sistema.
