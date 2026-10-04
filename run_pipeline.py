import sys
from pathlib import Path
from typing import TypedDict, List
from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END

llm = ChatOllama(
    model="qwen2.5-coder:7b",
    temperature=0.2,
    num_ctx=8192
)


class AvaliacaoAuditorGeral(BaseModel):
    approved: bool = Field(description="True if the code meets 100% of the requirements without grave pending issues.")
    consolidated_opnion: str = Field(description="Summary of reasons for approval or list of pending issues requiring refactoring")


class PipelineState(TypedDict):
    file_name: str
    project_context: str
    actual_code: str
    analysis: str
    tests: str
    expert_reviews: List[str]
    final audit: str
    aprovado: bool
    iteracao: int
    max_iteracoes: int

def carregar_prompt(file_name: str) -> str:
    caminho = Path("prompts") / file_name
    if caminho.exists():
        return caminho.read_text(encoding="utf-8")
    return "Você é um engenheiro sênior de software."

# --- NÓS DOS AGENTES ---
def agente_analista(state: PipelineState):
    iteracao = state.get("iteracao", 0) + 1
    print(f"\n🚀 [Ciclo {iteracao}/{state['max_iteracoes']}] 1. Analista Global inspecionando código...")
    prompt_sistema = carregar_prompt("1_analyst.md")
    
    instrucao = f"Contexto:\n{state['project_context']}\n\nCódigo Atual:\n{state['actual_code']}"
    if state.get("final audit") and not state.get("aprovado"):
        instrucao += f"\n\nO AUDITOR REPROVOU A VERSÃO ANTERIOR:\n{state['final audit']}\nFoque a análise em solucionar estes pontos críticos."
        
    resposta = llm.invoke([("system", prompt_sistema), ("user", instrucao)])
    return {"analysis": resposta.content, "iteracao": iteracao, "expert_reviews": []}

def agente_tests(state: PipelineState):
    print("🧪 2. Engenheiro de tests desenhando suíte de validação e edge cases...")
    resposta = llm.invoke([
        ("system", carregar_prompt("2_tester.md")),
        ("user", f"Código:\n{state['actual_code']}\n\nAnálise de arquitetura:\n{state['analysis']}")
    ])
    return {"tests": resposta.content}

def agente_refatorador(state: PipelineState):
    print("🛠️  3. Engenheiro Implementador aplicando correções no código...")
    instrucao = f"""
    Código Original:
    {state['actual_code']}
    
    Diretrizes do Analista:
    {state['analysis']}
    
    Suíte de tests/Requisitos:
    {state['tests']}
    
    Retorne o arquivo de código completo atualizado e funcional.
    """
    resposta = llm.invoke([("system", carregar_prompt("3_refactor.md")), ("user", instrucao)])
    return {"actual_code": resposta.content}

def revisor_perf(state: PipelineState):
    print("⚡ 4. Revisor Especialista em Performance auditando...")
    resposta = llm.invoke([("system", carregar_prompt("4_review_perf.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[PERFORMANCE]: {resposta.content}"]}

def revisor_io(state: PipelineState):
    print("🛡️  5. Revisor de Timeouts e I/O auditando...")
    resposta = llm.invoke([("system", carregar_prompt("5_review_errors.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[ERROS/IO]: {resposta.content}"]}

def revisor_clean(state: PipelineState):
    print("✨ 6. Revisor de Clean Code e Tipagem auditando...")
    resposta = llm.invoke([("system", carregar_prompt("6_review_clean.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[CLEAN CODE]: {resposta.content}"]}

def revisor_seg(state: PipelineState):
    print("🔒 7. Revisor de Segurança de Recursos auditando...")
    resposta = llm.invoke([("system", carregar_prompt("7_review_safety.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[SEGURANÇA]: {resposta.content}"]}

def agente_auditor_geral(state: PipelineState):
    print("⚖️  8. Auditor-Geral consolidando pareceres do comitê...")
    pareceres = "\n\n".join(state["expert_reviews"])
    instrucao = f"""
    Código Atual:
    {state['actual_code']}
    
    Pareceres dos 4 Especialistas:
    {pareceres}
    
    Avalie se o código está pronto para produção sem pendências graves.
    """
    auditor_llm = llm.with_structured_output(AvaliacaoAuditorGeral)
    avaliacao = auditor_llm.invoke([("system", carregar_prompt("8_general_audit.md")), ("user", instrucao)])
    return {"aprovado": avaliacao.aprovado, "final audit": avaliacao.parecer_consolidado}

def avaliar_condicao(state: PipelineState):
    if state["aprovado"]:
        print(f"\n🎉 [SUCESSO]: Código aprovado pelo Auditor-Geral na iteração {state['iteracao']}!")
        return END
    if state["iteracao"] >= state["max_iteracoes"]:
        print(f"\n⚠️  [AVISO]: Limite de {state['max_iteracoes']} iterações atingido. Entregando última versão.")
        return END
    print(f"\n🔄 [RETORNO]: Auditor reprovou o código. Motivo:\n{state['final audit']}")
    return "analista"

# 3. Montagem do Grafo LangGraph
builder = StateGraph(PipelineState)
builder.add_node("analista", agente_analista)
builder.add_node("tests", agente_tests)
builder.add_node("refatorador", agente_refatorador)
builder.add_node("rev_perf", revisor_perf)
builder.add_node("rev_io", revisor_io)
builder.add_node("rev_clean", revisor_clean)
builder.add_node("rev_seg", revisor_seg)
builder.add_node("auditor_geral", agente_auditor_geral)

builder.set_entry_point("analista")
builder.add_edge("analista", "tests")
builder.add_edge("tests", "refatorador")
builder.add_edge("refatorador", "rev_perf")
builder.add_edge("rev_perf", "rev_io")
builder.add_edge("rev_io", "rev_clean")
builder.add_edge("rev_clean", "rev_seg")
builder.add_edge("rev_seg", "auditor_geral")

builder.add_conditional_edges("auditor_geral", avaliar_condicao, {
    "analista": "analista",
    END: END
})

pipeline = builder.compile()

# --- EXECUÇÃO VIA TERMINAL ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python run_pipeline.py <caminho_do_arquivo> [contexto_opcional]")
        print("Exemplo: python run_pipeline.py aruco_follower.py 'Controle de navegação robótica'")
        sys.exit(1)

    caminho_arquivo = Path(sys.argv[1])
    if not caminho_arquivo.exists():
        print(f"Erro: Arquivo '{caminho_arquivo}' não encontrado.")
        sys.exit(1)

    conteudo = caminho_arquivo.read_text(encoding="utf-8")
    contexto = sys.argv[2] if len(sys.argv) > 2 else "Módulo crítico de engenharia."

    print(f"Iniciando pipeline de 8 agentes para: {caminho_arquivo.name} ({len(conteudo)} caracteres)")

    payload = {
        "file_name": caminho_arquivo.name,
        "project_context": contexto,
        "actual_code": conteudo,
        "analysis": "",
        "tests": "",
        "expert_reviews": [],
        "final audit": "",
        "aprovado": False,
        "iteracao": 0,
        "max_iteracoes": 3
    }

    resultado = pipeline.invoke(payload)

    # Salva a versão otimizada em um novo arquivo (ex: aruco_follower_perfect.py)
    arquivo_saida = caminho_arquivo.parent / f"{caminho_arquivo.stem}_perfect{caminho_arquivo.suffix}"
    arquivo_saida.write_text(resultado["actual_code"], encoding="utf-8")

    # Salva também a suíte de tests gerada pelo Agente 2
    arquivo_tests = caminho_arquivo.parent / f"test_{caminho_arquivo.stem}.py"
    arquivo_tests.write_text(resultado["tests"], encoding="utf-8")

    print(f"\n Concluído com sucesso!")
    print(f" Código otimizado salvo em: {arquivo_saida.name}")
    print(f" Suíte de tests salva em: {arquivo_tests.name}")