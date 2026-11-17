# Uso — exemplos reais

Os exemplos abaixo são **saídas reais** do programa, copiadas do terminal. Dois tipos de execução foram usados, e cada bloco diz qual é:

- **[modelo real]** — Ollama 0.40.13 com `qwen3.5:2b` ou `qwen3.5:4b` (Q4_K_M; cada bloco diz qual) e `qwen3-embedding:0.6b`, **só CPU** (8 núcleos, sem GPU), internet de verdade. É um modelo bem menor que o recomendado (`qwen3.5:9b`), escolhido porque a máquina de teste não tinha GPU.
- **[modelo simulado]** — o servidor falso dos testes automáticos (`tests/servidor_falso.py`), que responde de forma roteirizada. Serve para mostrar o fluxo completo de forma reproduzível; a busca na web e a execução dos testes foram reais.

A biblioteca de exemplo tem 7 arquivos: `contrato.docx`, `manual.pdf` (2 páginas), `estoque.xlsx`, `vendas.csv`, `notas.md`, `viagem.txt` e `codigo/motor.py`.

## 1. Perguntar à biblioteca (com citação)  [modelo real: qwen3.5:2b]

```
$ nlr perguntar "Qual é a multa por rescisão antecipada no meu contrato de aluguel?" --modo biblioteca
→ modo: biblioteca
• status: Buscando na biblioteca...
• status: Sintetizando a resposta com 8 fonte(s)...
A multa por rescisão antecipada no contrato de aluguel é de três aluguéis.
...
Fontes
 • [1] (biblioteca) contrato.docx
(+7 fonte(s) consultada(s) e não citada(s))
[18 s]
```

(Resposta correta: o `contrato.docx` diz "A multa por rescisão antecipada é de três aluguéis".)

## 2. Pesquisa profunda biblioteca + internet  [modelo real: qwen3.5:2b]

```
$ nlr pesquisar "Quanto tempo de autonomia tem a bateria do drone segundo meu manual, e o que a internet diz sobre autonomia típica de drones com bateria de lítio?" --fontes ambos --salvar pesquisa.md
• status: Buscando na biblioteca...
• status: Pesquisando na web: ...
• status: Lendo 3 página(s)...
• status: Sintetizando a resposta com 16 fonte(s)...
### Resposta ao Manual do Drone X100
Segundo o manual do drone X100, a autonomia da bateria de litio é de **32 minutos** [1].

### Resposta sobre Autonomia Típica de Drones com Baterias de Litio
A internet e fontes especializadas indicam que a autonomia típica de drones com baterias de litio varia
entre **15 e 35 minutos** [14][15][16].
...
## Biblioteca × Web
| Tema | Concordância | Divergência / Informação Única |
| Duração Típica | O manual diz 32 minutos. | Fontes externas (web) indicam uma faixa de 15 a 35 minutos,
  com a média real sendo ligeiramente menor devido a fatores práticos como vento e peso [14][15][16]. |
| Recomendação de Reserva | O manual não menciona reservas. | Fontes web recomendam sempre uma reserva
  de 20% ... [10]. |
...
Fontes
  [1] (biblioteca) manual.pdf, p. 1
  [9] (web) Drone Battery: Real Autonomy vs Manufacturer Specification ... — https://prowelllife.com/...
  [14] (web) Bateria de Drone: Quanto Tempo Dura e Como Conservar (2026) — https://pickdrones.com/pt/...
  ...
Relatório salvo em pesquisa.md
[55 s]
```

O manual de exemplo diz 32 minutos na página 1 — a citação está certa — e a seção **Biblioteca × Web** compara as duas origens.

## 3. "Pesquise na minha biblioteca e na internet e desenvolva um projeto X"

### 3a. Passo a passo completo  [modelo simulado; web e pytest reais]

```
$ nlr projeto novo Pesquise na minha biblioteca e na internet sobre calculadoras e desenvolva uma calculadora em Python com testes --nome calculadora --autonomo
Modo autônomo LIGADO nesta execução: comandos da lista de permitidos rodam sem 
perguntar.
• fase: pesquisa
• status: Consultas: calculadoras python
• status: Buscando na biblioteca...
• status: Pesquisando na web: calculadoras python
• status: Lendo 3 página(s)...
• status: Pesquisando na web: calculadoras
• status: Lendo 1 página(s)...
• status: Sintetizando a resposta com 14 fonte(s)...
• status: Pesquisa inicial com 14 fonte(s).
• fase: planejamento
• fase: Plano com 3 tarefa(s): Levantar requisitos; Implementar calc.py; 
Documentar
• fase: tarefa 1/3
• tarefa: Iniciando tarefa 1: Levantar requisitos (tentativa 1)
• ferramenta: buscar_biblioteca({"consulta": "calculadora operações"})
• ferramenta: escrever_arquivo({"caminho": "NOTAS.md", "conteudo": "# 
Notas\n\nRequisitos: somar, subtrair, multiplicar, dividir [1].\n"})
• tarefa: Tarefa 1 executada em 2 passo(s); arquivos: NOTAS.md
• revisao: Tarefa 1 APROVADA.
• fase: tarefa 2/3
• tarefa: Iniciando tarefa 2: Implementar calc.py (tentativa 1)
• ferramenta: escrever_arquivo({"caminho": "calc.py", "conteudo": 
"\"\"\"Calculadora simples.\"\"\"\n\n\ndef somar(a, b):\n    return a + 
b\n\n\ndef...)
• ferramenta: escrever_arquivo({"caminho": "test_calc.py", "conteudo": "from 
calc import dividir, multiplicar, somar, subtrair\nimport pytest\n\n\nd...)
• tarefa: Tarefa 2 executada em 2 passo(s); arquivos: calc.py, test_calc.py
• comando: python -m pytest -q -x --no-header -p no:cacheprovider
• revisao: Verificações da tarefa 2: pytest PASSOU (código 0; 2 passed in 
0.01s):
• revisao: Tarefa 2 APROVADA.
• fase: tarefa 3/3
• tarefa: Iniciando tarefa 3: Documentar (tentativa 1)
• ferramenta: ler_arquivo({"caminho": "calc.py"})
• ferramenta: escrever_arquivo({"caminho": "README.md", "conteudo": "# 
Calculadora\n\nFunções: somar, subtrair, multiplicar, dividir.\n\n## 
Testes\n...)
• tarefa: Tarefa 3 executada em 2 passo(s); arquivos: README.md
• revisao: Tarefa 3 APROVADA.
• fase: finalizacao
• fase: Projeto finalizado (concluido). Relatório: RELATORIO.md
╭────────────────────────────────── Projeto ───────────────────────────────────╮
│ calculadora                                                                  │
│ id: 20261029-calculadora                                                     │
│ status: concluido  fase: fim                                                 │
│ pasta: C:/IA/neuron-local-research/projetos/20261029-calculadora                               │
╰──────────────────────────────────────────────────────────────────────────────╯
  [x] 1. Levantar requisitos (pesquisa)
  [x] 2. Implementar calc.py (codigo)
  [x] 3. Documentar (docs)
```

O que aconteceu, fase por fase:

1. **pesquisa** — o pedido foi limpo ("calculadoras"), a biblioteca e a web foram consultadas e o resultado foi salvo em `PESQUISA.md` com as fontes numeradas.
2. **planejamento** — o planejador devolveu 3 tarefas (validadas como JSON), cada uma com tipo e critérios de aceite; o `PLANO.md` foi escrito.
3. **tarefa 1 (pesquisa)** — o sub-agente pesquisador buscou na biblioteca e escreveu `NOTAS.md`.
4. **tarefa 2 (código)** — o sub-agente desenvolvedor escreveu `calc.py` e `test_calc.py`; o revisor **rodou o pytest de verdade** (permitido porque o comando está na lista e `--autonomo` foi usado) e aprovou.
5. **tarefa 3 (docs)** — o redator leu o código e escreveu `README.md`.
6. **finalização** — `RELATORIO.md` foi gerado e um fato "Projeto 'calculadora' concluído" foi para a memória.

Arquivos resultantes em `projetos/20261029-calculadora/`: `PLANO.md`, `DIARIO.md`, `PESQUISA.md`, `NOTAS.md`, `calc.py`, `test_calc.py`, `README.md`, `RELATORIO.md` e `.agente/` (estado interno).

Sem `--autonomo`, cada comando aparece assim antes de rodar:

```
╭──────────────────── Executar comando? ─────────────────────╮
│ python -m pytest -q -x --no-header -p no:cacheprovider     │
│ (pasta: C:/IA/neuron-local-research/projetos/20261029-calculadora)  │
│ Motivo da pergunta: comandos precisam de confirmação (...) │
╰────────────────────────────────────────────────────────────╯
Autorizar? [y/n] (n):
```

### 3b. O mesmo pedido com um modelo de verdade  [modelo real: qwen3.5:4b]

Rodado com `qwen3.5:4b` (Q4_K_M), só CPU, internet real e `--autonomo`, numa biblioteca igual à de exemplo:

```
$ nlr projeto novo "Pesquise na minha biblioteca e na internet sobre o arquivo vendas.csv e desenvolva um script Python (só biblioteca padrão) que calcule o total de vendas por produto a partir de um CSV, com testes pytest" --nome vendas --autonomo
Modo autônomo LIGADO nesta execução: comandos da lista de permitidos rodam sem perguntar.
• fase: pesquisa
• status: Pesquisando na web: vendas.csv total por produto python
• status: Pesquisa inicial com 18 fonte(s).
• fase: Plano com 5 tarefa(s): Pesquisar vendas.csv; Criar script_vendas.py; Criar test_vendas.py; Rodar testes; Documentar README.md
• ferramenta: buscar_biblioteca({"consulta": "vendas.csv especificações separadores formato ...", "k": 5})
• revisao: Tarefa 1 REPROVADA (tentativa 1): A tarefa foi reprovada porque o arquivo `PESQUISA.md` não foi criado ou alterado. ...
  (...)
• ferramenta: escrever_arquivo({"caminho": "docs/README.md", ...})
• revisao: Tarefa 5 APROVADA.
• fase: Projeto finalizado (concluido_com_falhas). Relatório: RELATORIO.md
  [!] 1. Pesquisar vendas.csv (pesquisa)
  [x] 2. Criar script_vendas.py (codigo)
  [F] 3. Criar test_vendas.py (teste)
  [!] 4. Rodar testes (comando)
  [x] 5. Documentar README.md (docs)
[levou cerca de 19 minutos]
```

**Resultado honesto:** com um modelo de 4 B em CPU, o projeto terminou **com falhas**. O `script_vendas.py` (54 linhas) foi criado e aprovado, mas o `test_vendas.py` gerado esqueceu um `import` (3 testes passam, 2 falham com `NameError`), e o revisor apontou isso corretamente e marcou as tarefas como `[F]`/`[!]`. Isso mostra o sistema de revisão funcionando, e também o limite de modelos pequenos. Com um modelo maior (`qwen3.5:9b` na GPU) o resultado tende a ser melhor; e você pode corrigir o que faltou com:

```
$ nlr projeto continuar 20261029-vendas "corrija o import que falta em test_vendas.py e rode os testes"
```

## 4. Retomar e continuar

```
$ nlr projeto listar
$ nlr projeto retomar 20261029-vendas          # continua de onde parou (Ctrl+C, queda de energia...)
$ nlr projeto continuar 20261029-calculadora "adicione potência e raiz quadrada, com testes"
```

`retomar` usa o *checkpoint* do LangGraph (`dados/checkpoints.db`); se ele não existir, reconstrói o estado a partir de `.agente/tarefas.json`. `continuar` planeja só as tarefas novas, mantendo as concluídas. Ambos são cobertos pelos testes automáticos.

## 5. Chat no terminal

```
$ nlr chat
Neuron Local Research — digite /ajuda para ver os comandos.
você> /lembrar eu prefiro exemplos em Python e respostas curtas
Memorizado (id 1).
você> o que meus documentos dizem sobre o IPCA e o que a internet diz?
→ modo: ambos
...
você> /agente liste os arquivos .py da área de trabalho e conte as linhas de cada um
você> /projeto crie um conversor de moedas de linha de comando
```

O modo é escolhido automaticamente (conversa, biblioteca, web, ambos, agente com ferramentas ou sugestão de projeto); os comandos `/web`, `/biblioteca`, `/ambos` e `/agente` forçam um modo. A cada 4 mensagens o agente extrai fatos e preferências para a memória de longo prazo (`nlr memoria listar`). `nlr chat --sessao <id>` retoma uma conversa.

## 6. Interface web

`nlr ui` (ou `iniciar.bat`) → http://127.0.0.1:7860

| Aba | O que tem |
|---|---|
| Conversa | Chat com seletor de modo e respostas em tempo real |
| Pesquisa profunda | Pergunta + escolha de fontes (biblioteca / web / ambos), relatório com citações |
| Projetos | Criar, retomar, continuar e acompanhar projetos (caixa "modo autônomo") |
| Biblioteca | Adicionar pasta, indexar, testar a busca |
| Memória | Ver, adicionar e apagar lembranças |
| Sistema | Diagnóstico (`doctor`) |

## 7. Receitas úteis

```bash
nlr perguntar "resuma o manual" --modo biblioteca
nlr perguntar "quais as novidades do Gemma 4?" --modo web
nlr pesquisar "compare meu contrato com a lei do inquilinato" --fontes ambos --salvar comparacao.md
nlr projeto novo "leia minhas notas de estudo e gere um resumo em Markdown com perguntas de revisão"
nlr memoria adicionar "meu projeto Erebos usa Godot 4 e pixel art 480x270" --tipo fato
agente -v projeto retomar 20261029-vendas     # -v mostra o raciocínio e as observações das ferramentas
```

## Dicas para bons resultados com modelos locais

- Seja específico no objetivo: linguagem, bibliotecas permitidas ("só biblioteca padrão"), formato da entrega.
- Use o `qwen3.5:9b` (ou `gemma4:e4b`) para projetos; modelos de 2–4B servem para perguntas e pesquisas, mas planejam e programam pior (veja 3b).
- Projetos grandes: quebre em vários `continuar` em vez de um único pedido enorme.
