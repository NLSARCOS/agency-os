import logging
logging.basicConfig(level=logging.INFO)

from kernel.agent_manager import AgentManager
from kernel.tool_executor import get_tool_executor

def test_minimal():
    print("Iniciando prueba mínima directa (touch + timestamp)...")
    
    mgr = AgentManager()
    mgr.load_agents()
    agent_id = "backend-specialist"
    
    task_prompt = "Crea el archivo '/home/nelson/Documentos/GitHub/agency-os/EXECUTE_TEST.txt' con el timestamp actual. DEBES USAR OBLIGATORIAMENTE LA HERRAMIENTA 'write_file'. NO RESPONDAS CON TEXTO, SOLO CORRE LA HERRAMIENTA."
    
    print(f"2. Ejecutando AgentManager.execute_task con agent: {agent_id}")
    result = mgr.execute_task(
        agent_id=agent_id,
        task=task_prompt,
        context="No hay contexto.",
        tools_enabled=True,
        studio="dev"
    )
    
    print("\n--- RESULTADO FINAL ---")
    import json
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    test_minimal()
