# Pesquisa profunda / Deep research

```
nlr pesquisar "pergunta" --profunda [--profundidade 2] [--largura 4] [--formatos md,docx,pdf]
```

**PT** — Fluxo: (1) o modelo divide a pergunta em subperguntas; (2) cada rodada busca na web e/ou biblioteca, lê as páginas e extrai achados; (3) uma revisão aponta lacunas e contradições e gera novas buscas para a próxima rodada; (4) o relatório é redigido por seções, com citações numeradas **verificadas** (citações sem fonte real são removidas; frases que coincidem com uma fonte recebem citação automática) e seções Contradições, Lacunas, Fontes e Método. Salvo em `relatorios/` como .md (docx/pdf opcionais, via `python-docx`/`fpdf2`).

Padrões por perfil (profundidade, largura): pequeno (1,3), médio (2,4), grande (3,6). Configure em `config.yaml`, bloco `profunda:` (`profundidade`, `largura`, `pausa_segundos` — limite de taxa entre buscas —, `pasta_relatorios`, `formatos`). Páginas lidas ficam em cache durante a execução. Na interface: modo "Pesquisa profunda" com progresso ao vivo.

Exemplo real (qwen2.5:1.5b, CPU): `docs/exemplos/relatorio-pesquisa-profunda-qwen1.5b.md` — 819 palavras, 5 fontes citadas.

**EN** — Same pipeline: sub-questions → rounds of search/read/extract → gap & contradiction review → sectioned report with verified numbered citations, saved as md (optionally docx/pdf). Defaults adapt to the hardware profile; tune under `profunda:` in config.yaml. Available in the UI as "Deep research" mode with live progress.
