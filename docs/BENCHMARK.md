# Benchmark

```
nlr benchmark [--rapido] [--historico]
```

**PT** — Mede velocidade (tok/s), taxa de JSON válido (5 esquemas), sucesso em tarefas com ferramentas (3, em pasta temporária) e taxa de inhearsay; recomenda perfil e contexto e salva em `dados/benchmarks/*.json`. `--historico` lista execuções anteriores. Também disponível em Configurações na interface.

Exemplo (qwen2.5:1.5b, CPU do servidor de testes): 8,3 tok/s · JSON 100% · ferramentas 67% · inhearsay 0% → perfil "pequeno", contexto 8192.

**EN** — Measures speed, JSON validity, tool-task success and inhearsay rate; recommends a profile/context and saves results. `--historico` shows history.
